import asyncio
import base64
import json
import os
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import SchemaError
from pydantic import ValidationError

from ai_workbench.core.harness import ToolRegistry, register_builtin_tools
from ai_workbench.core.harness import network
from ai_workbench.core.harness.builtins import CODEC_MAX_BYTES
from ai_workbench.core.harness.schema import ToolExecutionContext, ToolExecutionError, ToolSpec
from ai_workbench.core.harness.settings import HarnessSettings
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.message_parts import make_tool_call_part, make_tool_result_part, validate_message_part, MessagePartValidationError
from ai_workbench.core.network_policy import NetworkPolicy, NetworkPolicyError
from ai_workbench.core.schema.message import MessageSchema


@pytest.fixture
def tool_env(tmp_path):
    registry = ToolRegistry()
    register_builtin_tools(registry)
    context = ToolExecutionContext(repo_root=tmp_path, network_policy=NetworkPolicy(), harness_settings=HarnessSettings())
    return registry, context


def execute(env, name, arguments):
    registry, context = env
    return asyncio.run(registry.execute(name, arguments, context))


def test_registry_schema_allowlist_and_catalog(tool_env):
    registry, _ = tool_env
    assert len(registry.catalog()) == 6
    assert {item.name for item in registry.list() if item.requires_approval} == {"read_file", "web_search", "fetch_url"}
    for name in ("Bad", "has-dash", "_prefix", "x" * 65):
        with pytest.raises(ValueError):
            registry.register(ToolSpec(name, "invalid", {"type": "object"}, lambda *_: None))
    with pytest.raises(ValueError):
        registry.register(registry.get("read_file"))
    with pytest.raises(SchemaError):
        registry.register(ToolSpec("invalid", "invalid", {"type": "invalid"}, lambda *_: None))
    with pytest.raises(ValueError):
        registry.register(ToolSpec("invalid", "invalid", {"type": "array"}, lambda *_: None))
    with pytest.raises(ValueError):
        registry.validate_allowlist(["read_file", "read_file"])
    with pytest.raises(ToolExecutionError):
        registry.validate_allowlist(["unknown"])
    catalog = registry.catalog()
    catalog[0]["parameters"].clear()
    assert registry.catalog()[0]["parameters"]["type"] == "object"


@pytest.mark.parametrize("name,args", [
    ("read_file", {}), ("read_file", {"path": 3}), ("read_file", {"path": "x", "max_bytes": True}),
    ("read_file", {"path": "x", "max_bytes": 0}), ("base64_encode", {"value": "x", "extra": True}),
    ("fetch_url", {"url": "not a URI"}), ("base64_encode", {"value": float("nan")}),
])
def test_strict_tool_arguments(tool_env, name, args):
    with pytest.raises(ToolExecutionError) as error:
        execute(tool_env, name, args)
    assert error.value.code == "TOOL_INVALID_ARGUMENTS"


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"x":{"a":1,"a":2}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'])
def test_strict_json_rejects_ambiguous_values(raw):
    with pytest.raises(ValueError):
        strict_json_loads(raw)


def test_tool_parts_and_roles_are_strict():
    call = make_tool_call_part("id", "read_file", {"path": "data/knowledge/a.txt"})
    result = make_tool_result_part("id", "read_file", "success", {"content": "untrusted"}, truncated=True)
    assert validate_message_part(result)["truncated"] is True
    for invalid in ({**call, "extra": True}, {**call, "arguments": []}, {**result, "status": "oops"}, {**result, "data": float("nan")}):
        with pytest.raises(MessagePartValidationError):
            validate_message_part(invalid)
    with pytest.raises(ValidationError):
        MessageSchema(message_id="m", session_id="s", role="system", parts=[result])
    with pytest.raises(ValidationError):
        MessageSchema(message_id="m", session_id="s", role="tool", parts=[call])


def test_file_read_bounds_and_truncation(tool_env):
    _, context = tool_env
    path = context.repo_root / "data/knowledge/a.txt"
    path.parent.mkdir(parents=True)
    path.write_text("abcdef", encoding="utf-8")
    result = execute(tool_env, "read_file", {"path": "data/knowledge/a.txt", "max_bytes": 3})
    assert result == {"path": "data/knowledge/a.txt", "content": "abc", "size_bytes": 6, "truncated": True}
    assert execute(tool_env, "read_file", {"path": "data\\knowledge\\a.txt"})["content"] == "abcdef"
    for raw in (str(path), "../outside.txt", "data/knowledge/../outside", "/etc/passwd", "C:\\secret.txt", "\\\\server\\share\\file", "data/knowledge/a.txt:stream"):
        with pytest.raises(ToolExecutionError) as error:
            execute(tool_env, "read_file", {"path": raw})
        assert error.value.code == "FILE_PATH_FORBIDDEN"
        assert str(context.repo_root) not in str(error.value)


def test_file_symlink_or_junction_escape_is_blocked(tool_env):
    _, context = tool_env
    outside = context.repo_root / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = context.repo_root / "data/knowledge/escape"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    with pytest.raises(ToolExecutionError) as error:
        execute(tool_env, "read_file", {"path": "data/knowledge/escape/secret.txt"})
    assert error.value.code == "FILE_PATH_FORBIDDEN"
    link.unlink() if link.is_symlink() else link.rmdir()


def test_codec_size_unicode_and_invalid_data(tool_env):
    assert execute(tool_env, "base64_encode", {"value": "中文"})["value"] == base64.b64encode("中文".encode()).decode()
    assert execute(tool_env, "base64_decode", {"value": "5Lit5paH"})["value"] == "中文"
    for name, value, code in (
        ("base64_encode", "x" * (CODEC_MAX_BYTES + 1), "CODEC_INPUT_TOO_LARGE"),
        ("base64_encode", "x" * CODEC_MAX_BYTES, "CODEC_OUTPUT_TOO_LARGE"),
        ("base64_decode", "x" * (CODEC_MAX_BYTES + 1), "CODEC_INPUT_TOO_LARGE"),
        ("base64_decode", "?!", "CODEC_INVALID_BASE64"), ("base64_decode", "/w==", "CODEC_INVALID_UTF8"),
    ):
        with pytest.raises(ToolExecutionError) as error:
            execute(tool_env, name, {"value": value})
        assert error.value.code == code


def test_knowledge_search_uses_only_resolved_bindings(tool_env):
    _, context = tool_env
    calls = []
    async def search(**kwargs):
        calls.append(kwargs)
        return {"results": []}
    context.knowledge_service = SimpleNamespace(search=search)
    context.session_id = "s"
    context.knowledge_base_ids = ["kb2", "kb1"]
    execute(tool_env, "knowledge_search", {"query": " q "})
    assert calls[-1]["knowledge_base_ids"] == ["kb2", "kb1"]
    assert calls[-1]["query"] == "q" and calls[-1]["include_debug"] is False
    execute(tool_env, "knowledge_search", {"query": "q", "knowledge_base_ids": []})
    assert calls[-1]["knowledge_base_ids"] == []
    with pytest.raises(ToolExecutionError) as error:
        execute(tool_env, "knowledge_search", {"query": "q", "knowledge_base_ids": ["other"]})
    assert error.value.code == "KNOWLEDGE_SCOPE_FORBIDDEN" and len(calls) == 2


def mock_network(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(network.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.parametrize("url", ["file:///secret", "http://localhost", "http://127.0.0.1", "http://10.0.0.1", "http://169.254.169.254", "http://[::1]", "http://[::ffff:127.0.0.1]", "http://u:secret@example.org"])
def test_network_blocks_non_public_urls(url):
    with pytest.raises(NetworkPolicyError):
        NetworkPolicy().resolve_url(url)


def test_dns_all_addresses_are_checked_and_connection_is_pinned(monkeypatch):
    answers = ["8.8.8.8", "127.0.0.1"]
    lookups = []
    def resolve(host, port, **kwargs):
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer, port)) for answer in answers]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(NetworkPolicyError) as error:
        NetworkPolicy().resolve_url("https://public.test/a")
    assert error.value.code == "NETWORK_ADDRESS_FORBIDDEN"
    answers[:] = ["8.8.8.8"]
    def handler(request):
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "public.test"
        assert request.extensions["sni_hostname"] == "public.test"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, text="ok")
    mock_network(monkeypatch, handler)
    result = asyncio.run(network.fetch_bytes("https://public.test/a", NetworkPolicy()))
    assert result[:2] == (b"ok", "https://public.test/a") and lookups == ["public.test", "public.test"]


@pytest.mark.parametrize("case,code", [("redirect", "NETWORK_REDIRECT_LIMIT"), ("private", "NETWORK_ADDRESS_FORBIDDEN"),
    ("length", "NETWORK_RESPONSE_TOO_LARGE"), ("stream", "NETWORK_RESPONSE_TOO_LARGE"), ("http", "NETWORK_HTTP_ERROR")])
def test_network_redirect_and_response_limits(monkeypatch, case, code):
    calls = []
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(5):
                yield b"a" * 300_000
    def handler(request):
        calls.append(request)
        if case == "redirect":
            return httpx.Response(302, headers={"location": "/again"})
        if case == "private":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        if case == "length":
            return httpx.Response(200, headers={"content-length": str(2 * 1024 * 1024)}, text="small")
        if case == "stream":
            return httpx.Response(200, stream=Chunks())
        return httpx.Response(503)
    mock_network(monkeypatch, handler)
    with pytest.raises(ToolExecutionError) as error:
        asyncio.run(network.fetch_bytes("http://8.8.8.8/test", NetworkPolicy()))
    assert error.value.code == code
    assert len(calls) == (4 if case == "redirect" else 1)


def test_search_configuration_json_and_fetch_text(tool_env, monkeypatch):
    with pytest.raises(ToolExecutionError) as error:
        execute(tool_env, "web_search", {"query": "test"})
    assert error.value.code == "TOOL_NOT_CONFIGURED"
    _, context = tool_env
    context.harness_settings = HarnessSettings(searxng_base_url="https://8.8.8.8")
    def handler(request):
        if request.url.path == "/search":
            assert request.url.params["q"] == "测试 & hello"
            return httpx.Response(200, json={"results": [{"title": "blocked", "url": "http://127.0.0.1"},
                {"title": "result", "url": "https://8.8.4.4/x", "content": "snippet"}]})
        return httpx.Response(200, headers={"content-type": 'text/html; charset="utf-8"'},
                              content=b"<p>Hello</p><script>hidden</script><p>world</p>")
    mock_network(monkeypatch, handler)
    result = execute(tool_env, "web_search", {"query": "测试 & hello", "limit": 1})
    assert result["results"] == [{"title": "result", "url": "https://8.8.4.4/x", "snippet": "snippet"}]
    fetched = execute(tool_env, "fetch_url", {"url": "https://8.8.8.8/page?token=private-secret", "max_chars": 5})
    assert fetched["content"] == "Hello" and fetched["truncated"] is True
    assert "private-secret" not in json.dumps(fetched)


def test_network_with_local_http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write("local response".encode())
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    class TestPolicy(NetworkPolicy):
        def resolve_url(self, url):
            # Only this test substitutes transport routing; the production
            # policy rejects loopback in the tests above.
            return url, ["127.0.0.1"]
    try:
        result = asyncio.run(network.fetch_bytes(f"http://local.test:{server.server_port}/", TestPolicy()))
        assert result[0] == b"local response"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

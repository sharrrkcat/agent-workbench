import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from jsonschema import SchemaError
from pydantic import ValidationError

from ai_workbench.core.harness import ToolRegistry
from tests.tool_fixtures import register_test_tools
from ai_workbench.core.harness import network
from ai_workbench.core.harness.schema import ToolExecutionContext, ToolExecutionError, ToolSpec
from ai_workbench.core.json_data import strict_json_loads
from ai_workbench.core.message_parts import make_tool_call_part, make_tool_result_part, validate_message_part, MessagePartValidationError
from ai_workbench.core.network_policy import NetworkPolicy, NetworkPolicyError
from ai_workbench.core.schema.message import MessageSchema


@pytest.fixture
def tool_env():
    registry = ToolRegistry()
    register_test_tools(registry)
    context = ToolExecutionContext()
    return registry, context


def execute(env, name, arguments):
    registry, context = env
    return asyncio.run(registry.execute(name, arguments, context))


def test_registry_schema_allowlist_and_catalog(tool_env):
    registry, _ = tool_env
    assert {tool["name"] for tool in registry.catalog()} == {"test_echo", "test_other"}
    assert all(tool["scope"] == "general" for tool in registry.catalog())
    assert {item.name for item in registry.list() if item.requires_approval} == set()
    for name in ("Bad", "has-dash", "_prefix", "x" * 65):
        with pytest.raises(ValueError):
            registry.register(ToolSpec(name, "invalid", {"type": "object"}, lambda *_: None))
    with pytest.raises(ValueError):
        registry.register(registry.get("test_echo"))
    with pytest.raises(SchemaError):
        registry.register(ToolSpec("invalid", "invalid", {"type": "invalid"}, lambda *_: None))
    with pytest.raises(ValueError):
        registry.register(ToolSpec("invalid", "invalid", {"type": "array"}, lambda *_: None))
    with pytest.raises(ValueError):
        registry.validate_allowlist(["test_echo", "test_echo"])
    with pytest.raises(ToolExecutionError):
        registry.validate_allowlist(["unknown"])
    catalog = registry.catalog()
    catalog[0]["parameters"].clear()
    assert registry.catalog()[0]["parameters"]["type"] == "object"


@pytest.mark.parametrize("name,args", [
    ("test_echo", {}), ("test_echo", {"value": 3}), ("test_other", {"value": True}),
    ("test_echo", {"value": "x", "extra": True}), ("test_echo", {"value": float("nan")}),
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
    call = make_tool_call_part("id", "test_echo", {"value": "untrusted"})
    result = make_tool_result_part("id", "test_echo", "success", {"content": "untrusted"}, truncated=True)
    assert validate_message_part(result)["truncated"] is True
    for invalid in ({**call, "extra": True}, {**call, "arguments": []}, {**result, "status": "oops"}, {**result, "data": float("nan")}):
        with pytest.raises(MessagePartValidationError):
            validate_message_part(invalid)
    with pytest.raises(ValidationError):
        MessageSchema(message_id="m", session_id="s", role="system", parts=[result])
    with pytest.raises(ValidationError):
        MessageSchema(message_id="m", session_id="s", role="tool", parts=[call])


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

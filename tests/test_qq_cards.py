"""NapCat card text survives ingress, positional projection and model history."""
import json

import pytest

from ai_workbench.core.qq_context import build_qq_context
from ai_workbench.core.qq_protocol import normalize
from ai_workbench.core.qq_segments import ordered_segments, public_segments
from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.db.qq_models import QQBatch, QQMedia
from tests.test_qqbot import qq_client, child, configure_execution, event, freeze, ingest
from tests.tool_fixtures import completion, ok, tool_call


URL = "https://example.test/bot?q=[一,二]&literal=&#91;"
LINK = {"app": "com.tencent.structmsg", "prompt": "fallback", "meta": {
    "news": {"title": " 链接\n标题 ", "jumpUrl": URL}}}
MINIAPP = {"app": "com.tencent.miniapp_01", "prompt": " 小程序\n摘要 ", "meta": {
    "detail_1": {"title": "应用名称", "qqdocurl": URL, "jumpUrl": "ignored", "url": "ignored"}}}
CARDS = [
    ({"type": "share", "data": {"title": " 链接\n标题 ", "url": URL}}, f"[分享链接: 链接 标题 ({URL})]"),
    ({"type": "json", "data": {"data": LINK}}, f"[分享链接: 链接 标题 ({URL})]"),
    ({"type": "json", "data": {"data": MINIAPP}}, f"[小程序: 小程序 摘要 ({URL})]"),
    ({"type": "lightapp", "data": {"data": MINIAPP}}, f"[小程序: 小程序 摘要 ({URL})]"),
    ({"type": "lightapp", "data": {"content": MINIAPP}}, f"[小程序: 小程序 摘要 ({URL})]"),
]


def wire_message(segments, wire):
    if wire == "objects":
        return segments
    serialized = [{"type": segment["type"], "data": {
        key: json.dumps(value, ensure_ascii=False) if key in {"data", "content"} and not isinstance(value, str) else value
        for key, value in segment["data"].items()}} for segment in segments]
    if wire == "json-strings":
        return serialized

    def escape(value):
        return value.replace("&", "&amp;").replace("[", "&#91;").replace("]", "&#93;").replace(",", "&#44;")

    return "".join(escape(segment["data"]["text"]) if segment["type"] == "text" else
        "[CQ:" + segment["type"] + "".join("," + key + "=" + escape(value)
            for key, value in segment["data"].items()) + "]" for segment in serialized)


@pytest.mark.parametrize("wire", ["objects", "json-strings", "cq"])
@pytest.mark.parametrize("card,expected", CARDS)
def test_card_formats_preserve_text_and_do_not_supply_keywords(wire, card, expected):
    values, keywords, media = normalize({**event(), "message": wire_message([card], wire)})
    assert values["text"] == expected
    assert keywords == "" and media == []
    assert json.loads(values["references_json"]) == []
    assert [part.model_dump() for part in public_segments(values["text"], values["references_json"], [])] == [
        {"type": "text", "text": expected}]


@pytest.mark.parametrize("kind,data,expected", [
    ("share", {"title": " title\t\nonly "}, "[分享链接: title only]"),
    ("share", {"url": " https://example.test "}, "[分享链接: https://example.test]"),
    ("share", {}, "[分享链接]"),
    ("share", {"title": 123, "url": {"secret": "hidden"}}, "[分享链接]"),
    ("share", {"title": False, "url": ["hidden"]}, "[分享链接]"),
    ("share", {"title": None, "url": "\n\t "}, "[分享链接]"),
    ("json", {"data": {"prompt": " fallback ", "meta": {"news": {"title": []}}}}, "[分享链接: fallback]"),
    ("json", {"data": {"meta": {"news": {"jumpUrl": URL}}}}, f"[分享链接: {URL}]"),
    ("json", {"data": {"meta": {"news": {}}}}, "[分享链接]"),
    ("json", {"data": {"app": "com.tencent.miniapp_02", "prompt": "\t", "meta": {
        "detail_1": {"title": " 名称 ", "qqdocurl": [], "jumpUrl": URL, "url": "ignored"}}}}, f"[小程序: 名称 ({URL})]"),
    ("json", {"data": {"app": "com.tencent.miniapp", "meta": {
        "detail_1": {"qqdocurl": " ", "jumpUrl": False, "url": URL}}}}, f"[小程序: {URL}]"),
    ("json", {"data": {"app": "com.tencent.miniapp_01", "meta": []}}, "[小程序]"),
    ("json", {"data": {"app": "com.tencent.miniapp_01", "prompt": "摘要", "meta": {"detail_1": None}}}, "[小程序: 摘要]"),
    ("lightapp", {"data": {"meta": {"detail_1": {"title": "名称"}}}}, "[小程序: 名称]"),
    ("lightapp", {"content": {}}, "[小程序]"),
    ("json", {"data": {"app": "other", "prompt": "hidden"}}, "[非文字消息]"),
    ("json", {"data": {"app": [], "meta": {"news": "hidden"}}}, "[非文字消息]"),
    ("json", {"data": {"meta": None}}, "[非文字消息]"),
    ("json", {}, "[非文字消息]"),
    ("json", {"data": "{broken"}, "[非文字消息]"),
    ("json", {"data": "[]"}, "[非文字消息]"),
    ("json", {"data": '"hidden"'}, "[非文字消息]"),
    ("json", {"data": None}, "[非文字消息]"),
    ("json", {"data": 123}, "[非文字消息]"),
    ("lightapp", {"content": "{broken"}, "[非文字消息]"),
])
def test_partial_unknown_and_malformed_cards_preserve_adjacent_text(kind, data, expected):
    values, keywords, media = normalize({**event(), "message": [
        {"type": "text", "data": {"text": "Before"}}, {"type": kind, "data": data},
        {"type": "text", "data": {"text": "After"}}]})
    assert values["text"] == "Before" + expected + "After"
    assert keywords == "beforeafter" and media == []


@pytest.mark.parametrize("wire", ["objects", "cq"])
def test_cards_keep_mention_and_media_spans_without_interpreting_literal_markers(wire):
    title = "bot [图片] [CQ:at,qq=666]"
    card = {"type": "share", "data": {"title": title, "url": URL}}
    prefix = f"😀[分享链接: {title} ({URL})]"
    mini = CARDS[2][1]
    message = wire_message([
        {"type": "text", "data": {"text": "😀"}}, card,
        {"type": "at", "data": {"qq": "42"}},
        {"type": "image", "data": {"url": "https://example.test/image"}}, CARDS[2][0],
        {"type": "reply", "data": {"id": "original"}},
        {"type": "face", "data": {"id": "0"}},
        {"type": "text", "data": {"text": "END"}},
    ], wire)
    values, keywords, media = normalize({**event(), "message": message})
    assert values["text"] == prefix + "@42[图片]" + mini + "[引用:original][表情包]END"
    assert keywords == "😀@42end"
    refs = json.loads(values["references_json"])
    assert (refs[0]["start"], refs[0]["end"]) == (len(prefix), len(prefix) + 3)
    assert refs[1] == {"type": "reply", "id": "original"}
    assert [(item["text_start"], item["text_end"]) for item in media] == [
        (len(prefix) + 3, len(prefix) + 7),
        (len(values["text"]) - 8, len(values["text"]) - 3),
    ]
    refs[0]["name"] = "Long member name"
    references = json.dumps(refs, ensure_ascii=False)
    records = [QQMedia(id=i + 1, message_id=1, **item) for i, item in enumerate(media)]
    parts = public_segments(values["text"], references, records)
    assert [part.type for part in parts] == ["text", "image", "text", "image", "text"]
    assert parts[0].text == prefix + "@Long member name"
    assert parts[2].text == mini + "[引用:original]"
    assert parts[4].text == "END"
    assert [part.kind for part in parts if part.type == "image"] == ["image", "face"]
    model_parts = ordered_segments(values["text"], references, records, for_model=True)
    assert model_parts[0] == prefix + "@Long member name（QQ:42）"
    assert model_parts[2] == mini + "[引用:original]"


@pytest.mark.parametrize("private", [False, True])
def test_card_text_reaches_api_batch_model_and_history_without_keyword_trigger(qq_client, private):
    client, state, upstream = qq_client
    p, session, connection = configure_execution(client, state)
    if private:
        session = child(client, p, "9999", "friend")
    sid = session["session_id"]
    cards = [card for card, _ in CARDS]
    expected = "".join(text for _, text in CARDS)
    incoming = {**event(kind="private" if private else "group"), "message": cards}
    ingest(client, state, p, incoming, 0)
    row = ok(client.get(f"/api/qq/sessions/{sid}/messages"))["items"][0]
    assert row["text"] == expected
    assert row["segments"] == [{"type": "text", "text": expected}]
    if not private:
        assert freeze(state, session, 5) is None  # Every card URL contains the configured keyword.
        ingest(client, state, p, event(2, "BoT"), 6)
    batch = freeze(state, session, 11)
    assert batch.trigger_kind == ("private" if private else "keyword")
    assert expected in batch.text
    upstream.turns = [completion(tool_call("qq_send_message", {"text": "ack"})), completion(content="")]
    client.portal.call(state.qq.execute, batch)
    saved = state.qq.store.get(QQBatch, batch.id)
    assert saved.status == "done", saved.error_code
    assert len(connection.calls) == 1
    model_input = upstream.calls[0]["messages"][-1]["content"]
    assert expected in model_input
    history = build_qq_context(state.qq.store, state.messages, sid, "next", ContextPolicy(), None)
    assert any(message["role"] == "user" and message["content"] == model_input for message in history.messages)
    refreshed = ok(client.get(f"/api/qq/sessions/{sid}/messages"))["items"]
    assert next(item for item in refreshed if item["external_id"] == "1")["segments"] == row["segments"]

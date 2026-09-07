"""Scripted OpenAI-compatible responses for harness behavior tests."""

import json

import httpx

from tests.model_fixtures import MockOpenAI


def tool_call(name="base64_encode", arguments=None, call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {
        "name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments or {"value": "hello"}),
    }}


def completion(*calls, content=None, finish=None):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = list(calls)
    return {"message": message, "finish_reason": finish or ("tool_calls" if calls else "stop")}


class ToolOpenAI(MockOpenAI):
    def __init__(self, *turns):
        super().__init__()
        self.turns = list(turns)
        self.stream_chunks = None

    async def handle(self, request):
        if not request.url.path.endswith("/chat/completions"):
            return await super().handle(request)
        data = json.loads(request.content)
        self.calls.append(data)
        turn = self.turns.pop(0) if self.turns else completion(content="finished")
        if callable(turn):
            turn = turn(data)
        if not data.get("stream"):
            return httpx.Response(200, json={"choices": [{"index": 0, **turn}]})
        if self.stream_chunks is not None:
            chunks = self.stream_chunks
            self.stream_chunks = None
        else:
            chunks = []
            message = turn["message"]
            if message.get("reasoning_content"):
                chunks.append({"reasoning_content": message["reasoning_content"]})
            content = message.get("content")
            if content:
                chunks.extend([{"content": content[:2]}, {"content": content[2:]}])
            calls = message.get("tool_calls", [])
            # Interleave indices, split both function name and JSON arguments.
            if calls:
                chunks.append({"tool_calls": [{"index": i, "id": call["id"], "type": "function", "function": {
                    "name": call["function"]["name"][:3], "arguments": call["function"]["arguments"][:4],
                }} for i, call in reversed(list(enumerate(calls)))]})
                chunks.append({"tool_calls": [{"index": i, "function": {
                    "name": call["function"]["name"][3:], "arguments": call["function"]["arguments"][4:],
                }} for i, call in enumerate(calls)]})
            if message.get("refusal"):
                chunks.append({"refusal": message["refusal"]})
        events = [{"choices": [{"index": 0, "delta": chunk, "finish_reason": None}]} for chunk in chunks]
        events.append({"choices": [{"index": 0, "delta": {}, "finish_reason": turn["finish_reason"]}]})
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=body)


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()

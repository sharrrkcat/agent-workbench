from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_api import create_session, make_client, post_message


def create_image_profile(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Agent Image Model",
        "alias": "agent-image",
        "architecture": "sdxl",
        "checkpoint_ref": "image_generation/checkpoints/agent-image.safetensors",
    }
    payload.update(overrides)
    response = client.post("/api/image-generation/model-profiles", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def find_message_with_part(messages: list[dict], part_type: str) -> dict:
    return next(message for message in messages if any(part.get("type") == part_type for part in message.get("parts", [])))


def find_part(message: dict, part_type: str) -> dict:
    return next(part for part in message.get("parts", []) if part.get("type") == part_type)


def test_image_generator_form_reports_missing_profiles() -> None:
    client = make_client()
    session = create_session(client, default_agent_id="image_generator")

    payload = post_message(client, session["session_id"], "@image_generator")
    assistant = payload["messages"][-1]

    assert assistant["role"] == "assistant"
    assert assistant["parts"][0]["type"] == "text"
    assert "Image generation unavailable" in assistant["parts"][0]["text"]


def test_image_generator_default_and_form_render_txt2img_form() -> None:
    client = make_client()
    create_image_profile(client)
    session = create_session(client, default_agent_id="image_generator")

    payload = post_message(client, session["session_id"], "@image_generator secret castle")
    form_message = find_message_with_part(payload["messages"], "form")
    form = find_part(form_message, "form")
    fields = {field["name"]: field for field in form["fields"]}

    assert form["form_id"] == "image_generation_txt2img"
    assert form["submit"]["action_id"] == "generate_from_form"
    assert fields["profile_id_or_alias"]["value"] == "agent-image"
    assert fields["positive_prompt"]["value"] == "secret castle"
    assert fields["loras"]["type"] == "json"


def test_image_generator_form_submit_saves_attachment_and_compact_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_WORKBENCH_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    client = make_client()
    create_image_profile(client)
    session = create_session(client, default_agent_id="image_generator")
    payload = post_message(client, session["session_id"], "@image_generator:form")
    form_message = find_message_with_part(payload["messages"], "form")

    response = client.post(
        f"/api/sessions/{session['session_id']}/forms/submit",
        json={
            "source_message_id": form_message["message_id"],
            "form_id": "image_generation_txt2img",
            "values": {
                "profile_id_or_alias": "agent-image",
                "positive_prompt": "secret castle",
                "negative_prompt": "hidden negative",
                "width": 64,
                "height": 64,
                "steps": 8,
                "cfg": 4.5,
                "sampler": "euler",
                "scheduler": "normal",
                "seed": 42,
                "batch_size": 1,
                "loras": [{"ref": "image_generation/loras/style.safetensors", "weight": 0.8}],
            },
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assistant = find_message_with_part(result["messages"], "media_group")
    media_group = find_part(assistant, "media_group")
    attachment = assistant["metadata"]["attachments"][0]
    metadata = assistant["metadata"]["image_generation"]
    run_metadata = result["run"]["metadata"]["image_generation"]

    assert media_group["items"] == [
        {
            "type": "image",
            "url": attachment["url"],
            "attachment_id": attachment["id"],
            "alt": attachment["name"],
            "title": attachment["name"],
        }
    ]
    assert attachment["type"] == "image"
    assert attachment["mime_type"] == "image/png"
    assert attachment["metadata"]["source"] == "image_generation"
    assert metadata["backend"] == "fake"
    assert metadata["real_generation"] is False
    assert metadata["request"]["seed"] == 42
    assert metadata["request"]["lora_count"] == 1
    assert metadata["queue"]["status"] == "completed"
    assert metadata["queue"]["request_id"] == metadata["request_id"]
    assert isinstance(metadata["queue"]["queue_wait_ms"], int)
    assert metadata["attachment_ids"] == [attachment["id"]]
    assert run_metadata == metadata
    assert "data_base64" not in str(assistant["metadata"])
    assert "secret castle" not in str(assistant["metadata"])
    assert "hidden negative" not in str(assistant["metadata"])
    assert "style.safetensors" not in str(assistant["metadata"])
    assert str(tmp_path) not in str(assistant["metadata"])


def test_image_generator_form_submit_action_is_not_user_callable() -> None:
    client = make_client()
    create_image_profile(client)
    session = create_session(client, default_agent_id="image_generator")

    response = client.post(
        f"/api/sessions/{session['session_id']}/messages",
        json={"content": "@image_generator:generate_from_form"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ACTION_NOT_CALLABLE"

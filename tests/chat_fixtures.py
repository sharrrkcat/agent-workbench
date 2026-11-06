"""Native Character-owned normal chat setup for domain tests."""


def create_chat(client, *, overrides=None, title="", character_id=None):
    if character_id is None:
        owner = client.post("/api/characters", json={"kind": "normal", "name": "Test assistant"})
        assert owner.status_code == 200, owner.text
        character_id = owner.json()["id"]
    return client.post(f"/api/characters/{character_id}/sessions",
        json={"title": title, "overrides": overrides or {}})


def normal_character(client, **values):
    response = client.post("/api/characters", json={"kind": "normal", "name": "Test assistant", **values})
    assert response.status_code == 200, response.text
    return response.json()


def child(client, owner, **values):
    response = client.post(f"/api/characters/{owner['id']}/sessions", json=values)
    assert response.status_code == 200, response.text
    return response.json()


async def create_chat_async(client, *, overrides=None, title=""):
    owner = await client.post("/api/characters", json={"kind": "normal", "name": "Test assistant"})
    assert owner.status_code == 200, owner.text
    return await client.post(f"/api/characters/{owner.json()['id']}/sessions",
        json={"title": title, "overrides": overrides or {}})

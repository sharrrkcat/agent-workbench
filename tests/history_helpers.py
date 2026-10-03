"""Assertions over the current bounded conversation response."""
def history_messages(page):
    messages = [message for item in page["items"] for message in
                ([item["message"]] if item["kind"] == "message" else item["messages"])]
    return sorted(messages, key=lambda m: (m["created_at"], m["message_id"]))


def history_runs(page):
    return [item["run"] for item in page["items"] if item["kind"] == "reply"]

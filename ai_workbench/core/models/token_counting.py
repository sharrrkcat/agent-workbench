"""Offline reference counting for providers with unknown native tokenizers."""
import base64
from functools import lru_cache
import json
from pathlib import Path

import tiktoken


@lru_cache(maxsize=1)
def reference_encoding():
    # The vocabulary is an installation asset. Never use tiktoken's URL loader.
    lines = (Path(__file__).parent / "token_data" / "o200k_base.tiktoken").read_bytes().splitlines()
    ranks = {base64.b64decode(token): int(rank) for token, rank in (line.split() for line in lines)}
    pattern = "|".join([
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
    ])
    return tiktoken.Encoding(name="cogita_o200k_base", pat_str=pattern, mergeable_ranks=ranks, special_tokens={})


def estimate_input_tokens(payload: dict) -> int:
    messages, images = [], 0
    for message in payload["messages"]:
        message = dict(message)
        if isinstance(message.get("content"), list):
            content = []
            for part in message["content"]:
                if part["type"] == "image_url":
                    images += 1
                else:
                    content.append(part)
            message["content"] = content
        messages.append(message)
    text = json.dumps({"messages": messages, **({"tools": payload["tools"]} if payload.get("tools") else {})},
                      ensure_ascii=False, separators=(",", ":"))
    return len(reference_encoding().encode_ordinary(text)) + images * 4096

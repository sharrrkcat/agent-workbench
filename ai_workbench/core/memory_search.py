"""Deterministic literal recall shared by both memory stores."""

import re
import unicodedata
from collections import Counter


def terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    result = set(re.findall(r"[a-z0-9_]+", normalized))
    for sequence in re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", normalized):
        result.update(sequence)
        result.update(sequence[i:i + 2] for i in range(len(sequence) - 1))
    return result


def entry_terms(summary: str, body: str) -> dict[str, int]:
    weights = Counter({term: 1 for term in terms(body)})
    weights.update({term: 3 for term in terms(summary)})
    return dict(weights)


def query_terms(query: str) -> list[str]:
    # Prefer longer terms when a user submits a whole message.
    return sorted(terms(query), key=lambda term: (-len(term), term))[:128]

from __future__ import annotations

import re
from typing import Iterable


PROFILE_ALIAS_PATTERN_DESCRIPTION = "lowercase letters, numbers, underscores, and hyphens only"
PROFILE_ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def validate_profile_alias(value: str) -> str:
    alias = str(value or "").strip().lower()
    if not alias:
        raise ValueError("Alias must not be empty.")
    if not PROFILE_ALIAS_RE.fullmatch(alias):
        raise ValueError(f"Alias must use {PROFILE_ALIAS_PATTERN_DESCRIPTION}.")
    return alias


def profile_alias_base(*values: object, fallback: str = "profile") -> str:
    for value in values:
        candidate = _slugify(value)
        if candidate:
            return candidate
    return validate_profile_alias(fallback)


def unique_profile_alias(base: str, existing: Iterable[str]) -> str:
    normalized_base = validate_profile_alias(base)
    existing_aliases = {str(item or "").strip().lower() for item in existing if str(item or "").strip()}
    if normalized_base not in existing_aliases:
        return normalized_base
    index = 2
    while f"{normalized_base}-{index}" in existing_aliases:
        index += 1
    return f"{normalized_base}-{index}"


def _slugify(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    text = re.sub(r"[-_]+", lambda match: "-" if "-" in match.group(0) else "_", text)
    text = text.strip("-_")
    if not text or not re.match(r"[a-z0-9]", text):
        return ""
    return validate_profile_alias(text)

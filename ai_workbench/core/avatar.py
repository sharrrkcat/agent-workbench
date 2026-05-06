from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse
import unicodedata

from ai_workbench.core.schema.agent import AgentSchema


AvatarType = Literal["image", "emoji", "text", "initials"]

AVATAR_CANDIDATES = (
    "avatar.png",
    "avatar.jpg",
    "avatar.jpeg",
    "avatar.webp",
    "avatar.svg",
    "agent.png",
    "agent.jpg",
)

AVATAR_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


@dataclass(frozen=True)
class ResolvedAvatar:
    avatar: Optional[str]
    avatar_type: AvatarType
    avatar_url: Optional[str] = None
    file_path: Optional[Path] = None
    content_type: Optional[str] = None

    def public_dict(self) -> dict:
        return {
            "avatar": self.avatar,
            "avatar_type": self.avatar_type,
            "avatar_url": self.avatar_url,
        }


def resolve_agent_avatar(agent: AgentSchema, agent_dir: str | Path | None = None) -> ResolvedAvatar:
    directory = Path(agent_dir).resolve() if agent_dir is not None else None
    if directory is not None:
        discovered = _resolve_discovered_avatar(agent.id, directory)
        if discovered is not None:
            return discovered

    manifest_avatar = (agent.avatar or "").strip()
    if not manifest_avatar:
        return ResolvedAvatar(avatar=None, avatar_type="initials")

    if _is_http_url(manifest_avatar):
        return ResolvedAvatar(avatar=None, avatar_type="image", avatar_url=manifest_avatar)

    if directory is not None and _looks_like_local_image_path(manifest_avatar):
        local = _resolve_manifest_avatar_path(agent.id, directory, manifest_avatar)
        if local is not None:
            return local
        return ResolvedAvatar(avatar=None, avatar_type="initials")

    if _looks_like_emoji(manifest_avatar):
        return ResolvedAvatar(avatar=manifest_avatar, avatar_type="emoji")

    return ResolvedAvatar(avatar=manifest_avatar, avatar_type="text")


def _resolve_discovered_avatar(agent_id: str, agent_dir: Path) -> ResolvedAvatar | None:
    for filename in AVATAR_CANDIDATES:
        path = (agent_dir / filename).resolve()
        if not _is_inside(path, agent_dir) or not path.is_file():
            continue
        content_type = AVATAR_CONTENT_TYPES.get(path.suffix.lower())
        if content_type is None:
            continue
        return ResolvedAvatar(
            avatar=None,
            avatar_type="image",
            avatar_url=f"/api/agents/{agent_id}/avatar",
            file_path=path,
            content_type=content_type,
        )
    return None


def _resolve_manifest_avatar_path(agent_id: str, agent_dir: Path, value: str) -> ResolvedAvatar | None:
    raw_path = Path(value)
    if raw_path.is_absolute() or ".." in raw_path.parts:
        return None
    path = (agent_dir / raw_path).resolve()
    if not _is_inside(path, agent_dir) or not path.is_file():
        return None
    content_type = AVATAR_CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        return None
    return ResolvedAvatar(
        avatar=None,
        avatar_type="image",
        avatar_url=f"/api/agents/{agent_id}/avatar",
        file_path=path,
        content_type=content_type,
    )


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_local_image_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.startswith("./") or "/" in normalized:
        return True
    return Path(normalized).suffix.lower() in AVATAR_CONTENT_TYPES


def _looks_like_emoji(value: str) -> bool:
    if len(value) > 4:
        return False
    return any(unicodedata.category(char).startswith("S") and ord(char) > 0x2500 for char in value)

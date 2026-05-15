from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re


FONT_EXTENSIONS = {".woff2", ".woff", ".ttf", ".otf"}
FONT_MIME_TYPES = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}


@dataclass(frozen=True)
class FontAsset:
    id: str
    filename: str
    display_name: str
    extension: str
    size_bytes: int
    mtime: float
    css_family: str
    url: str
    path: Path

    def response(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "display_name": self.display_name,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "css_family": self.css_family,
            "url": self.url,
        }


def fonts_root(repo_root: Path) -> Path:
    return (repo_root / "data" / "assets" / "fonts").resolve()


def ensure_fonts_directory(repo_root: Path) -> Path:
    root = fonts_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def scan_font_assets(repo_root: Path) -> list[FontAsset]:
    root = ensure_fonts_directory(repo_root)
    items: list[FontAsset] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not _is_inside(resolved, root):
            continue
        extension = path.suffix.lower()
        if extension not in FONT_EXTENSIONS:
            continue
        filename = path.name
        asset_id = _font_id(filename)
        stat = resolved.stat()
        items.append(
            FontAsset(
                id=asset_id,
                filename=filename,
                display_name=_display_name(path.stem),
                extension=extension,
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                css_family=f"AW Local Font {asset_id}",
                url=f"/api/assets/fonts/{asset_id}",
                path=resolved,
            )
        )
    return items


def resolve_font_asset(repo_root: Path, font_id: str) -> FontAsset | None:
    if not re.fullmatch(r"[a-f0-9]{16}", font_id or ""):
        return None
    return next((asset for asset in scan_font_assets(repo_root) if asset.id == font_id), None)


def _font_id(filename: str) -> str:
    return sha256(filename.encode("utf-8")).hexdigest()[:16]


def _display_name(stem: str) -> str:
    cleaned = re.sub(r"[_-]+", " ", stem).strip()
    return cleaned or "Local font"


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

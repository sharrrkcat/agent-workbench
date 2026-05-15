from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


FONT_EXTENSIONS = {".woff2", ".woff", ".ttf", ".otf"}
FONT_MIME_TYPES = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

FONT_SUFFIXES: tuple[tuple[str, int, str], ...] = (
    ("ExtraLightItalic", 200, "italic"),
    ("SemiBoldItalic", 600, "italic"),
    ("ExtraBoldItalic", 800, "italic"),
    ("ThinItalic", 100, "italic"),
    ("LightItalic", 300, "italic"),
    ("MediumItalic", 500, "italic"),
    ("BlackItalic", 900, "italic"),
    ("BoldItalic", 700, "italic"),
    ("ExtraLight", 200, "normal"),
    ("SemiBold", 600, "normal"),
    ("ExtraBold", 800, "normal"),
    ("Regular", 400, "normal"),
    ("Medium", 500, "normal"),
    ("Italic", 400, "italic"),
    ("Black", 900, "normal"),
    ("Light", 300, "normal"),
    ("Thin", 100, "normal"),
    ("Bold", 700, "normal"),
)

STATIC_WEIGHT_RANGES = {
    100: "1 149",
    200: "150 249",
    300: "250 349",
    400: "350 449",
    500: "450 549",
    600: "550 649",
    700: "650 749",
    800: "750 849",
    900: "850 1000",
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


@dataclass(frozen=True)
class FontFace:
    file: str
    weight: int | str
    style: str
    url: str
    registered_weight: str

    def response(self) -> dict:
        return {
            "file": self.file,
            "weight": self.weight,
            "style": self.style,
            "url": self.url,
            "registered_weight": self.registered_weight,
        }


@dataclass(frozen=True)
class FontFamilyAsset:
    id: str
    display_name: str
    css_family: str
    faces: list[FontFace]

    def response(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "css_family": self.css_family,
            "faces": [face.response() for face in self.faces],
        }


@dataclass(frozen=True)
class FontAssetScan:
    files: list[FontAsset]
    families: list[FontFamilyAsset]


def fonts_root(repo_root: Path) -> Path:
    return (repo_root / "data" / "assets" / "fonts").resolve()


def ensure_fonts_directory(repo_root: Path) -> Path:
    root = fonts_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def scan_font_assets(repo_root: Path) -> FontAssetScan:
    root = ensure_fonts_directory(repo_root)
    files: list[FontAsset] = []
    families: list[FontFamilyAsset] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        resolved = path.resolve()
        if not _is_inside(resolved, root):
            continue
        if path.is_dir():
            family = _scan_font_family(path, root)
            if family:
                families.append(family)
            continue
        if not path.is_file():
            continue
        extension = path.suffix.lower()
        if extension not in FONT_EXTENSIONS:
            continue
        filename = path.name
        asset_id = _font_id(filename)
        stat = resolved.stat()
        files.append(
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
    return FontAssetScan(files=files, families=families)


def resolve_font_asset(repo_root: Path, font_id: str) -> FontAsset | None:
    if not re.fullmatch(r"[a-f0-9]{16}", font_id or ""):
        return None
    return next((asset for asset in scan_font_assets(repo_root).files if asset.id == font_id), None)


def resolve_font_family_face(repo_root: Path, family_id: str, filename: str) -> Path | None:
    if not re.fullmatch(r"[a-f0-9]{16}", family_id or ""):
        return None
    if not filename or Path(filename).name != filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
        return None
    root = ensure_fonts_directory(repo_root)
    for folder in root.iterdir():
        if not folder.is_dir() or _font_id(folder.name) != family_id:
            continue
        resolved_folder = folder.resolve()
        if not _is_inside(resolved_folder, root):
            return None
        face_path = (resolved_folder / filename).resolve()
        if not _is_inside(face_path, resolved_folder) or face_path.suffix.lower() not in FONT_EXTENSIONS or not face_path.is_file():
            return None
        return face_path
    return None


def _font_id(filename: str) -> str:
    return sha256(filename.encode("utf-8")).hexdigest()[:16]


def _display_name(stem: str) -> str:
    cleaned = re.sub(r"[_-]+", " ", stem).strip()
    return cleaned or "Local font"


def _scan_font_family(folder: Path, root: Path) -> FontFamilyAsset | None:
    resolved_folder = folder.resolve()
    if not _is_inside(resolved_folder, root):
        return None
    manifest = _load_font_manifest(resolved_folder / "font.json")
    family_id = _font_id(folder.name)
    css_family = str(manifest.get("family") or f"AW Local Font Family {family_id}").strip()
    display_name = str(manifest.get("display_name") or manifest.get("family") or _display_name(folder.name)).strip()
    faces = _manifest_faces(resolved_folder, family_id, manifest) if manifest else []
    if not faces:
        faces = _inferred_faces(resolved_folder, family_id)
    if not faces:
        return None
    return FontFamilyAsset(id=family_id, display_name=display_name or _display_name(folder.name), css_family=css_family, faces=faces)


def _load_font_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_faces(folder: Path, family_id: str, manifest: dict[str, Any]) -> list[FontFace]:
    raw_faces = manifest.get("faces")
    if not isinstance(raw_faces, list):
        return []
    faces: list[FontFace] = []
    for item in raw_faces:
        if not isinstance(item, dict):
            continue
        filename = item.get("file")
        if not isinstance(filename, str) or not _valid_face_file(folder, filename):
            continue
        weight = _normalize_manifest_weight(item.get("weight"))
        style = _normalize_style(item.get("style"))
        if weight is None:
            weight = 400
        faces.append(_face(family_id, filename, weight, style, explicit_range=isinstance(weight, str)))
    return sorted(faces, key=lambda face: (str(face.weight), face.style, face.file.lower()))


def _inferred_faces(folder: Path, family_id: str) -> list[FontFace]:
    faces: list[FontFace] = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() not in FONT_EXTENSIONS:
            continue
        resolved = path.resolve()
        if not _is_inside(resolved, folder.resolve()):
            continue
        weight, style = _infer_weight_style(path.stem)
        faces.append(_face(family_id, path.name, weight, style, explicit_range=False))
    return faces


def _valid_face_file(folder: Path, filename: str) -> bool:
    if Path(filename).name != filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
        return False
    path = (folder / filename).resolve()
    return _is_inside(path, folder.resolve()) and path.is_file() and path.suffix.lower() in FONT_EXTENSIONS


def _normalize_manifest_weight(value: Any) -> int | str | None:
    if isinstance(value, int) and 1 <= value <= 1000:
        return value
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{1,4}\s+\d{1,4}", text):
            left, right = [int(part) for part in text.split()]
            if 1 <= left <= right <= 1000:
                return f"{left} {right}"
        if re.fullmatch(r"\d{1,4}", text):
            number = int(text)
            if 1 <= number <= 1000:
                return number
    return None


def _normalize_style(value: Any) -> str:
    return "italic" if value == "italic" else "normal"


def _infer_weight_style(stem: str) -> tuple[int, str]:
    normalized = re.sub(r"[\s_-]+", "", stem).lower()
    for suffix, weight, style in FONT_SUFFIXES:
        if normalized.endswith(suffix.lower()):
            return weight, style
    return 400, "normal"


def _face(family_id: str, filename: str, weight: int | str, style: str, explicit_range: bool) -> FontFace:
    registered_weight = weight if isinstance(weight, str) else STATIC_WEIGHT_RANGES.get(weight, str(weight))
    if explicit_range:
        registered_weight = str(weight)
    return FontFace(
        file=filename,
        weight=weight,
        style=style,
        registered_weight=str(registered_weight),
        url=f"/api/assets/font-families/{family_id}/{filename}",
    )


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

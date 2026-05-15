from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ai_workbench.api.deps import RuntimeState, get_state
from ai_workbench.api.errors import raise_error
from ai_workbench.core.font_assets import FONT_MIME_TYPES, resolve_font_asset, resolve_font_family_face, scan_font_assets


router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/fonts")
def list_fonts(state: RuntimeState = Depends(get_state)) -> dict:
    scanned = scan_font_assets(state.repo_root)
    files = [asset.response() for asset in scanned.files]
    families = [family.response() for family in scanned.families]
    return {"fonts": files, "files": files, "families": families}


@router.get("/fonts/{font_id}")
def get_font(font_id: str, state: RuntimeState = Depends(get_state)):
    asset = resolve_font_asset(state.repo_root, font_id)
    if asset is None:
        raise_error(404, "FONT_ASSET_NOT_FOUND", "Font asset not found.")
    return FileResponse(asset.path, media_type=FONT_MIME_TYPES.get(asset.extension, "application/octet-stream"), filename=asset.filename)


@router.get("/font-families/{family_id}/{filename}")
def get_font_family_face(family_id: str, filename: str, state: RuntimeState = Depends(get_state)):
    path = resolve_font_family_face(state.repo_root, family_id, filename)
    if path is None:
        raise_error(404, "FONT_ASSET_NOT_FOUND", "Font asset not found.")
    return FileResponse(path, media_type=FONT_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"), filename=path.name)

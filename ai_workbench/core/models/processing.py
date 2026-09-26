"""Static image preparation at the public/internal service boundary."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.runtimes.schema import model_path
from ai_workbench.core.models.schema import ImageOutput

MAX_PROCESS_PIXELS = 8_388_608
MAX_PROCESS_BYTES = 64 * 1024 * 1024


def processor_resource(root, reference):
    directory = model_path(root, reference)
    resource = directory / "nvngx_dlssnr.dll"
    if not resource.resolve().is_relative_to((root / "data/models").resolve()):
        raise ModelError("INVALID_REQUEST", "Processor resource escapes data/models.", 422)
    if not resource.is_file():
        raise ModelError("MODEL_NOT_FOUND", "Place nvngx_dlssnr.dll in the processor model directory.", 404)
    return directory


def prepare_process_image(data: bytes) -> ImageOutput:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "is_animated", False):
                raise ModelError("INVALID_IMAGE", "Upload one static PNG, JPEG or WebP image.", 422)
            if max(source.size) > 16384 or source.width * source.height > MAX_PROCESS_PIXELS:
                raise ModelError("REQUEST_TOO_LARGE", "Images must fit 8,388,608 pixels and 16,384 pixels per axis.", 413)
            oriented = ImageOps.exif_transpose(source)
            rgba = oriented.convert("RGBA")
            output = io.BytesIO()
            rgba.save(output, format="PNG")
            return ImageOutput(data=output.getvalue(), width=rgba.width, height=rgba.height)
    except Image.DecompressionBombError as exc:
        raise ModelError("REQUEST_TOO_LARGE", "Image exceeds the decoded pixel limit.", 413) from exc
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise ModelError("INVALID_IMAGE", "The uploaded image cannot be decoded.", 422) from exc


def validate_process_output(data: bytes, original: ImageOutput) -> ImageOutput:
    with Image.open(io.BytesIO(data)) as output, Image.open(io.BytesIO(original.data)) as source:
        if (output.format != "PNG" or output.mode != "RGBA" or output.size != source.size
                or getattr(output, "is_animated", False)
                or output.getchannel("A").tobytes() != source.getchannel("A").tobytes()):
            raise ValueError("Worker result must preserve oriented dimensions and alpha")
        return ImageOutput(data=data, width=output.width, height=output.height)

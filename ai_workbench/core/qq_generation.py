"""Generate and stage one QQ image; shared resources are committed after delivery."""
import asyncio
import base64
import hashlib
from dataclasses import dataclass, replace

from PIL import Image, UnidentifiedImageError

from ai_workbench.core.attachments import save_attachment_from_upload
from ai_workbench.core.harness.network import fetch_bytes
from ai_workbench.core.harness.schema import ToolExecutionError
from ai_workbench.core.models.errors import ModelError
from ai_workbench.core.models.schema import ImageGenerationRequest
from ai_workbench.core.qq_media import decode_image
from ai_workbench.core.schema.qq import QQImageAttachment
from ai_workbench.db.qq_models import QQMediaAsset


@dataclass
class PreparedQQImage:
    data: bytes
    asset: QQMediaAsset

    @property
    def attachment_ids(self):
        return {a.id for a in (self.asset.attachment, self.asset.model_attachment) if a is not None}


async def prepare_image(state, prompt, context):
    created = set()
    try:
        settings = state.app_settings.get()
        limit = settings.max_image_size_mb * 1024 * 1024
        profile = state.model_manager.profile(context.qq_image_generation_model_profile_id, "image_generation")
        result = await state.model_manager.generate_images(profile.id, ImageGenerationRequest(
            model=profile.alias, prompt=prompt, n=1, **context.qq_image_generation_options.model_dump()))
        image = result.data[0]
        if image.url is not None:
            data, _, _ = await fetch_bytes(image.url, replace(state.network_policy, max_response_bytes=limit), max_bytes=limit)
        else:
            if len(image.b64_json) > ((limit + 2) // 3) * 4:
                raise ToolExecutionError("QQ_IMAGE_TOO_LARGE", "Generated image exceeds the image size limit.")
            data = base64.b64decode(image.b64_json, validate=True)
        if len(data) > limit:
            raise ToolExecutionError("QQ_IMAGE_TOO_LARGE", "Generated image exceeds the image size limit.")
        mime, suffix, width, height, model_data = await asyncio.to_thread(decode_image, data)

        def save(content, content_type, extension):
            saved = save_attachment_from_upload("qq-generated" + extension, content_type, content, settings)
            attachment_id = saved["uri"].removeprefix("local://attachments/")
            created.add(attachment_id)
            return QQImageAttachment(id=attachment_id,
                **{key: saved[key] for key in ("name", "mime_type", "size", "uri")},
                width=width, height=height).model_dump_json()

        original = save(data, mime, suffix)
        model = original if model_data is None else (save(model_data, "image/png", ".png") if len(model_data) <= limit else None)
        prepared = PreparedQQImage(data, QQMediaAsset(sha256=hashlib.sha256(data).hexdigest(),
            attachment_json=original, model_attachment_json=model, description=prompt))
        created.clear()
        return prepared
    except (ModelError, ToolExecutionError) as exc:
        raise ToolExecutionError("QQ_IMAGE_GENERATION_FAILED", "No image was sent. " + exc.message,
            {"cause": exc.code}) from exc
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            SyntaxError, EOFError, OSError) as exc:
        raise ToolExecutionError("QQ_IMAGE_GENERATION_FAILED", "Could not prepare the generated image; no image was sent.") from exc
    finally:
        state.qq.media.cleanup(created)

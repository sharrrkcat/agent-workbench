# Attachments and vision contract

Uploads and serving use the configured local attachment directory. General
settings own size/count/type limits. Message parts retain ids, MIME type,
name, size and compact metadata; image data URLs are not persisted in messages
or logs. Orphan cleanup is an explicit, separate operation.

Supported parts remain file, image, audio, video and media_group. Current
image attachments become OpenAI image_url parts through the selected llm
profile and ModelManager. The profile must advertise capabilities.vision;
otherwise the run reports UNSUPPORTED_CAPABILITY. No alternate vision model
or silent display-only inference path is selected.

General settings control text-file context and per-file/per-message byte
limits. Other attachments contribute a bounded descriptive marker. Historical
attachment bytes are not resent; normal context projection remains in force.

The standalone vision and image_embedding profile kinds are distinct from
LLM image input. They execute in the managed Python worker using bounded PNG,
JPEG or WebP data URLs. It never fetches image URLs or model weights. The old
/v1/vision and multimodal embedding APIs remain deleted. Managed llama image
input is rejected until projector configuration is implemented; external
vision-capable connections retain their existing behavior.

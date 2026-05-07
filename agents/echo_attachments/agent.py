async def run(ctx):
    wrote = False
    text = ctx.input.text
    if text.strip():
        await ctx.reply_text(text)
        wrote = True

    for attachment in ctx.input.attachments:
        attachment_type = attachment.get("type")
        name = attachment.get("name") or "attachment"
        mime_type = attachment.get("mime_type") or "application/octet-stream"
        size = attachment.get("size")
        if attachment_type == "image":
            try:
                data_url = ctx.attachment_as_data_url(attachment)
                caption = f"{name} | {mime_type} | {size} bytes" if isinstance(size, int) else f"{name} | {mime_type}"
                await ctx.reply_image(data_url, alt=name, title=name, caption=caption)
            except Exception as exc:
                await ctx.reply_text(f"Could not read image attachment {name}: {exc}")
            wrote = True
            continue

        if attachment_type == "file":
            try:
                payload = ctx.read_attachment_text(attachment)
                await ctx.reply_file_content(**payload)
            except Exception as exc:
                await ctx.reply_text(f"Could not read file attachment {name}: {exc}")
            wrote = True

    if not wrote:
        await ctx.reply_text("No input.")

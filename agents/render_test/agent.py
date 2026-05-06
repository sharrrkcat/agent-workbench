async def run(ctx):
    if ctx.action_id == "image":
        await ctx.reply_image(
            "https://picsum.photos/seed/agent-workbench-single/960/540",
            alt="Demo landscape",
            title="Single image",
            caption="A single image output from a script agent.",
        )
        await ctx.reply_blocks(
            [
                {"type": "markdown", "text": "## Mixed content\nThis message combines markdown, an image, and plain text."},
                {
                    "type": "image",
                    "url": "https://picsum.photos/seed/agent-workbench-rich/900/520",
                    "alt": "Mixed content demo",
                    "caption": "Image block inside rich content.",
                },
                {"type": "text", "text": "Plain text block after the image."},
            ]
        )
        await ctx.reply_images(
            [
                {
                    "url": "https://picsum.photos/seed/agent-workbench-a/640/480",
                    "alt": "Gallery image A",
                    "title": "Gallery A",
                    "caption": "First gallery item.",
                },
                {
                    "url": "https://picsum.photos/seed/agent-workbench-b/640/480",
                    "alt": "Gallery image B",
                    "title": "Gallery B",
                    "caption": "Second gallery item.",
                },
                {
                    "url": "https://picsum.photos/seed/agent-workbench-c/640/480",
                    "alt": "Gallery image C",
                    "title": "Gallery C",
                    "caption": "Third gallery item.",
                },
            ]
        )
        return
    if ctx.action_id == "json":
        await ctx.reply_json({"echo": ctx.input.text, "items": [1, 2]})
        return
    if ctx.action_id == "text":
        await ctx.reply_text(ctx.input.text)
        return
    if ctx.action_id == "llm":
        await ctx.reply_text(await ctx.llm.text(system="Echo briefly.", user=ctx.input.text))
        return
    await ctx.reply_markdown(f"# Render Test\n\n- {ctx.input.text}")

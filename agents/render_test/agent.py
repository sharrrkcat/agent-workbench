async def run(ctx):
    if ctx.action_id == "form_submit":
        await ctx.reply_json(
            {
                "received_prefill": ctx.input.prefill,
                "source_message_id": ctx.input.source_message_id,
                "form_id": ctx.input.form_id,
            }
        )
        return
    if ctx.action_id == "form":
        await ctx.reply_blocks(
            [
                {"type": "markdown", "text": "## Demo form\nFill the fields and submit to echo the values."},
                {
                    "type": "action_form",
                    "form_id": "demo",
                    "title": "Demo Form",
                    "description": "A generic form used to verify Script Agent form submissions.",
                    "fields": [
                        {
                            "name": "prompt",
                            "type": "textarea",
                            "label": "Prompt",
                            "description": "Short text to process.",
                            "required": True,
                            "value": "hello",
                            "placeholder": "Describe the task...",
                        },
                        {
                            "name": "count",
                            "type": "integer",
                            "label": "Count",
                            "minimum": 1,
                            "maximum": 10,
                            "step": 1,
                            "value": 2,
                        },
                        {
                            "name": "mode",
                            "type": "enum",
                            "label": "Mode",
                            "options": [
                                {"value": "fast", "label": "Fast"},
                                {"value": "quality", "label": "Quality"},
                            ],
                            "value": "fast",
                        },
                        {
                            "name": "enabled",
                            "type": "boolean",
                            "label": "Enabled",
                            "value": True,
                        },
                        {
                            "name": "config_json",
                            "type": "json",
                            "label": "Config JSON",
                            "value": {"size": "small"},
                        },
                    ],
                    "submit": {
                        "label": "Run",
                        "action_id": "form_submit",
                        "message": "Submitted form: Demo Form",
                    },
                },
            ]
        )
        return
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

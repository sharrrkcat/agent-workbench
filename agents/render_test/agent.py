async def run(ctx):
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

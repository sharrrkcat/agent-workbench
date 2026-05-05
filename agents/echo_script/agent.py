async def run(ctx):
    async with ctx.step("encoding"):
        base64_capability = ctx.capability("base64")
        encoded = await base64_capability.encode(text=ctx.input.text)
        if not encoded.success:
            raise RuntimeError(encoded.error or "base64 encode failed")

    await ctx.reply(encoded.data)


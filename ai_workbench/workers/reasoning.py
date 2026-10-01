"""Native template evidence for reasoning modes; no model-name assumptions or inference."""
UNKNOWN_REASONING_SUPPORT = {"instant": "unknown", "reasoning": "unknown"}
SUPPORT_STATES = {"supported", "unsupported", "unknown"}
# These are prompt delimiters, not output filters. Other formats stay unknown.
THINKING_DELIMITERS = (("<think>", "</think>"), ("[THINK]", "[/THINK]"),
                       ("<|channel>thought", "<channel|>"))


def skip_reasoning_check(reasoning, instant_declared, reasoning_declared):
    return instant_declared != reasoning_declared and (
        reasoning_declared if reasoning else instant_declared)


def generation_prefix(prompt, without_generation):
    if isinstance(prompt, str) and isinstance(without_generation, str) and prompt.startswith(without_generation):
        return prompt[len(without_generation):]
    return None


def template_reasoning_support(template, prefixes, *, delimiters=THINKING_DELIMITERS):
    """Classify only explicit open/empty-closed native prefills.

    A response parser alone is not evidence of mode control. Missing renders,
    unfamiliar reasoning syntax and conditional natural-language instructions
    remain unknown, including when a template ignores enable_thinking.
    """
    states = dict(UNKNOWN_REASONING_SUPPORT)
    modes = {}
    for enabled, prefix in prefixes.items():
        mode = None
        if prefix is not None:
            for opening, closing in delimiters:
                start = prefix.rfind(opening)
                end = prefix.rfind(closing)
                if start > end:
                    mode = True
                    break
                if start >= 0 and end > start and not prefix[start + len(opening):end].strip():
                    mode = False
                    break
        modes[enabled] = mode
    # Switchable templates may omit the entire thinking prefix in instant mode.
    if (isinstance(template, str) and "enable_thinking" in template
            and modes.get(True) is True and modes.get(False) is None and prefixes.get(False) is not None):
        disabled = prefixes[False]
        if disabled != prefixes[True] and not any(token in disabled for pair in delimiters for token in pair):
            modes[False] = False
    for enabled, mode in modes.items():
        if mode is not None:
            states["reasoning" if enabled else "instant"] = "supported" if mode == enabled else "unsupported"
    return states

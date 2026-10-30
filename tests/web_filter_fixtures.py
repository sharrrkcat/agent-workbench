"""Explicit offline subscription downloads for automated acceptance."""


async def empty_subscription(_url: str) -> str:
    return "# Offline subscription fixture.\n"


def install_offline_subscriptions(state):
    state.web_tools.filters.download = empty_subscription


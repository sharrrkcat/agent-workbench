"""Initial web-search filters; persisted settings own subsequent edits."""

DEFAULT_CUSTOM_RULES = "\n".join(f"*://*.{host}/*" for host in (
    "youtube.com", "instagram.com", "facebook.com", "tiktok.com",
    "flipboard.com", "fb.watch", "baidu.com", "ifeng.com",
))
DEFAULT_SUBSCRIPTIONS = (
    ("default-1", "BadWebsiteBlocklist", "https://raw.githubusercontent.com/popcar2/BadWebsiteBlocklist/refs/heads/main/uBlacklist.txt"),
    ("default-2", "uBlacklist Pinterest", "https://raw.githubusercontent.com/rjaus/ublacklist-pinterest/main/ublacklist-pinterest.txt"),
    ("default-3", "GitHub Translation", "https://raw.githubusercontent.com/arosh/ublacklist-github-translation/master/uBlacklist.txt"),
    ("default-4", "uBlock-Origin dev filter", "https://raw.githubusercontent.com/quenhus/uBlock-Origin-dev-filter/main/dist/other_format/uBlacklist/all.txt"),
)
MAX_FILTER_BYTES = 16 * 1024 * 1024


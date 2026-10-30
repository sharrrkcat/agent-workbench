"""The URL-match-pattern subset of uBlacklist, indexed without a JS runtime."""
from dataclasses import dataclass
from collections.abc import Iterable
import re

import httpx


_LABEL = r"[0-9A-Za-z](?:[0-9A-Za-z-]*[0-9A-Za-z])?"
_PATTERN = re.compile(
    rf"(?P<scheme>\*|https?)://(?P<host>(?:\*|{_LABEL})(?:\.{_LABEL})*)"
    r"(?P<path>/(?:\*|[0-9A-Za-z._~:/?\[\]@!$&'()+,;=\-]|%[0-9A-Fa-f]{2})*)", re.IGNORECASE | re.ASCII)
_SCHEMES = {"http": 1, "https": 2, "*": 3}


class FilterRuleError(ValueError):
    def __init__(self, line: int, message="Expected an HTTP(S) match pattern or @ exception."):
        self.line = line
        super().__init__(f"Line {line}: {message}")


@dataclass(frozen=True, slots=True)
class Rule:
    allow: bool
    scheme: int
    host: str
    subdomains: bool
    path: str


def parse_rules(text: str) -> Iterable[Rule]:
    first, header = True, None
    for number, raw in enumerate(text.removeprefix("\ufeff").splitlines(), 1):
        line = raw.strip()
        if first and not line:
            continue
        if first and line == "---":
            first, header = False, number
            continue
        first = False
        if header is not None:
            if line == "---":
                header = None
            continue
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        allow = line.startswith("@")
        if allow:
            line = line[1:]
        if line == "<all_urls>":
            yield Rule(allow, 3, "", True, "/*")
            continue
        match = _PATTERN.fullmatch(line)
        if match is None:
            raise FilterRuleError(number)
        host = match["host"].lower()
        subdomains = host == "*" or host.startswith("*.")
        host = "" if host == "*" else host.removeprefix("*.")
        yield Rule(allow, _SCHEMES[match["scheme"].lower()], host, subdomains, match["path"])
    if header is not None:
        raise FilterRuleError(header, "Subscription frontmatter is missing its closing ---.")


def _path_matches(parts: tuple[str, ...], path: str) -> bool:
    if len(parts) == 1:
        return path == parts[0]
    if not path.startswith(parts[0]):
        return False
    position = len(parts[0])
    for part in parts[1:-1]:
        found = path.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return len(path) - len(parts[-1]) >= position and path.endswith(parts[-1])


class _PathNode:
    """Radix tree of literal prefixes, with glob tails only at matching nodes."""
    __slots__ = ("prefix", "children", "rules")

    def __init__(self, prefix=""):
        self.prefix = prefix
        self.children: dict[str, _PathNode] = {}
        self.rules: list[tuple[int, tuple[str, ...]]] = []

    def add(self, path: str, scheme: int):
        parts = tuple(path.split("*"))
        prefix, node = parts[0], self
        while prefix:
            child = node.children.get(prefix[0])
            if child is None:
                child = _PathNode(prefix)
                node.children[prefix[0]] = child
                node = child
                break
            common = 0
            for left, right in zip(prefix, child.prefix):
                if left != right:
                    break
                common += 1
            if common < len(child.prefix):
                split = _PathNode(child.prefix[:common])
                child.prefix = child.prefix[common:]
                split.children[child.prefix[0]] = child
                node.children[prefix[0]] = split
                child = split
            prefix, node = prefix[common:], child
        node.rules.append((scheme, parts))

    def matches(self, path: str, scheme: int) -> bool:
        node, position = self, 0
        while True:
            if any(mask & scheme and _path_matches(parts, path) for mask, parts in node.rules):
                return True
            if position == len(path):
                return False
            child = node.children.get(path[position])
            if child is None or not path.startswith(child.prefix, position):
                return False
            position += len(child.prefix)
            node = child


class _Bucket:
    __slots__ = ("schemes", "paths")

    def __init__(self):
        self.schemes = 0
        self.paths: _PathNode | None = None

    def add(self, rule: Rule):
        if rule.path == "/*":
            self.schemes |= rule.scheme
        else:
            if self.paths is None:
                self.paths = _PathNode()
            self.paths.add(rule.path, rule.scheme)

    def matches(self, path: str, scheme: int) -> bool:
        return bool(self.schemes & scheme) or self.paths is not None and self.paths.matches(path, scheme)


class _HostIndex:
    __slots__ = ("exact", "suffix")

    def __init__(self):
        self.exact: dict[str, _Bucket] = {}
        self.suffix: dict[str, _Bucket] = {}

    def add(self, rule: Rule):
        index = self.suffix if rule.subdomains else self.exact
        if rule.host not in index:
            index[rule.host] = _Bucket()
        index[rule.host].add(rule)

    def matches(self, host: str, path: str, scheme: int) -> bool:
        bucket = self.exact.get(host)
        if bucket is not None and bucket.matches(path, scheme):
            return True
        while True:
            bucket = self.suffix.get(host)
            if bucket is not None and bucket.matches(path, scheme):
                return True
            if not host:
                return False
            host = host.partition(".")[2]


class FilterRuleset:
    def __init__(self, texts: Iterable[str]):
        self.allow, self.block = _HostIndex(), _HostIndex()
        seen: set[Rule] = set()
        for text in texts:
            for rule in parse_rules(text):
                if rule in seen:
                    continue
                seen.add(rule)
                (self.allow if rule.allow else self.block).add(rule)
        self.rule_count = len(seen)

    def action(self, host: str, path: str, scheme: int) -> bool | None:
        if self.allow.matches(host, path, scheme):
            return False
        if self.block.matches(host, path, scheme):
            return True
        return None


class FilterSnapshot:
    def __init__(self, custom: str, subscriptions: Iterable[str]):
        self.custom = FilterRuleset([custom])
        self.subscriptions = FilterRuleset(subscriptions)

    def blocked(self, url: str) -> bool:
        target = httpx.URL(url)
        scheme = _SCHEMES.get(target.scheme, 0)
        if not scheme:
            return False
        host, path = target.raw_host.decode("ascii"), target.raw_path.decode("ascii")
        custom = self.custom.action(host, path, scheme)
        return custom if custom is not None else self.subscriptions.action(host, path, scheme) is True


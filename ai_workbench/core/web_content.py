"""Deterministic web text cleaning, lexical ranking and conservative date inference."""

from collections import Counter
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ai_workbench.core.network_policy import NetworkPolicy, NetworkPolicyError
from ai_workbench.core.web_schemas import WebDate, WebLink


TRACKING_PARAMETERS = {"spm", "fbclid", "gclid", "dclid", "msclkid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    # Scheme, www, path case/trailing slash and non-tracking query order are meaningful.
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                      urlencode(query) if len(query) != len(parse_qsl(parts.query, keep_blank_values=True)) else parts.query, ""))


def query_key(query: str, recency: str) -> str:
    return recency + ":" + " ".join(unicodedata.normalize("NFKC", query).casefold().split())


def fingerprint(content: str) -> str | None:
    prefix = []
    for char in content:
        if not char.isspace() and not unicodedata.category(char).startswith("P"):
            prefix.append(char.casefold())
            if len(prefix) == 150:
                return "".join(prefix)
    return None


class _HTMLText(HTMLParser):
    """Turn extraction HTML into text/links without executing or fetching anything."""
    BLOCKS = {"p", "div", "article", "section", "main", "li", "h1", "h2", "h3", "h4", "tr", "br"}
    SKIP = {"script", "style", "nav", "footer", "aside", "form", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = []
        self.href = None

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in self.SKIP:
                self.skip.append(tag)
            return
        if tag in self.SKIP:
            self.skip.append(tag)
        elif tag in self.BLOCKS:
            self.parts.append("\n\n")
        elif tag == "a":
            self.href = dict(attrs).get("href")
            if self.href:
                self.parts.append("[")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
        elif tag == "a" and self.href:
            self.parts.append("](" + self.href + ")")
            self.href = None
        elif tag in self.BLOCKS:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


NAV_LABELS = {"首页", "主站", "商城", "论坛", "登录", "注册", "网站导航", "友情链接", "home", "login", "sign in",
              "game info", "interactive map", "learn more", "now playing"}


def decoded_text(text: str) -> str:
    # AnySearch's IGN extraction contains this misdecoded breadcrumb separator.
    # Remove the substitution once the provider consistently returns the Unicode character.
    return unescape(unescape(text)).replace("â€º", "›")


def _closing(text: str, start: int, opening: str, closing: str) -> int | None:
    depth, escaped = 1, False
    for index in range(start + 1, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if not depth:
                return index
    return None


def _inline_links(line: str, base_url: str) -> tuple[str, list[WebLink]]:
    output, links, cursor = [], [], 0
    scan = 0
    while scan < len(line):
        start = line.find("[", scan)
        if start < 0:
            break
        middle = _closing(line, start, "[", "]")
        scan = start + 1
        if middle is None or line[middle + 1:middle + 2] != "(":
            continue
        end = _closing(line, middle + 1, "(", ")")
        if end is None:
            continue
        is_image = start > cursor and line[start - 1] == "!"
        output.append(line[cursor:start - 1 if is_image else start])
        if not is_image:
            label, _ = _inline_links(line[start + 1:middle], base_url) if "[" in line[start + 1:middle] else (line[start + 1:middle], [])
            label = re.sub(r"\\([\[\]_*])", r"\1", label)
            target = line[middle + 2:end].strip().split(' "', 1)[0].strip("<>")
            offset = sum(map(len, output))
            output.append(label)
            try:
                url = NetworkPolicy().validate_url(urljoin(base_url, unescape(target)), resolve_dns=False)
            except NetworkPolicyError:
                url = None
            if url and label.strip():
                links.append(WebLink(text=label, url=normalize_url(url), offset=offset))
        cursor = scan = end + 1
    output.append(line[cursor:])
    return "".join(output), links


def page_title(raw: str, supplied: str, url: str) -> str:
    """Prefer an article's h1 over a provider title assembled from navigation."""
    raw = decoded_text(raw)
    heading = re.search(r"(?im)^#\s+(.+?)(?:\s+#(?:\s|$)|$)", raw)
    if not heading:
        heading = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1>", raw)
    title = heading[1] if heading else decoded_text(supplied)
    title = re.sub(r"<[^>]+>", "", title)
    return _inline_links(title, url)[0].strip(" #\t")[:180]


def clean_content(raw: str, title: str, url: str) -> tuple[str, list[WebLink]]:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    # Valid JSON is evidence, not Markdown or HTML, including strings containing tags.
    if raw.startswith(("{", "[")):
        try:
            json.loads(raw)
        except (ValueError, RecursionError):
            pass
        else:
            return raw, []
    raw = decoded_text(raw)
    raw = re.sub(r"\A##\s+\d+\.\s+[^\n]*\n+\*\*URL\*\*:\s*[^\n]*\n*", "", raw)
    # AnySearch sometimes flattens repeated h1 headings onto the first body line.
    if title.strip():
        raw = re.sub(r"\A(?:\s*#\s+" + re.escape(title.strip()) + r"\s*)+", "", raw)
    code = re.compile(r"(?m)(^(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\2[^\n]*$|^(?:(?: {4}|\t)[^\n]*(?:\n|$))+)" )
    chunks, cursor = [], 0
    for match in [*code.finditer(raw), None]:
        end = match.start() if match else len(raw)
        chunk = raw[cursor:end]
        # Search providers can flatten an entire Markdown document onto one line.
        chunk = re.sub(r"(?<!\n)[ \t]+(?=#{1,6}[ \t]+)", "\n\n", chunk)
        if re.search(r"</?(?:html|body|p|div|article|script|style|h[1-6]|nav|a)(?:\s|>)", chunk, re.I):
            parser = _HTMLText()
            parser.feed(chunk)
            chunk = "".join(parser.parts)
        chunks.append(chunk)
        if match:
            chunks.append(match[0])
            cursor = match.end()
    raw = "".join(chunks)
    definitions = {key.casefold(): value for key, value in re.findall(r"(?m)^\s*\[([^\]]+)\]:\s*(\S+).*?$", raw)}
    raw = re.sub(r"(?m)^\s*\[[^\]]+\]:\s*\S+.*?$", "", raw)
    raw = re.sub(r"(!?\[[^\]\n]+\])\[([^\]\n]+)\]",
                 lambda m: f"{m[1]}({definitions[m[2].casefold()]})" if m[2].casefold() in definitions else m[0], raw)
    raw = re.sub(r"(?ims)^\s*Now playing\s*\n.*?(?=^#{1,6}\s)", "", raw)
    raw = re.split(r"(?im)^#{1,6}\s+(?:Up Next\b|Top Guide Sections\b|Related (?:articles|stories)\b|Ease in Finding Information\b)", raw)[0]
    raw = re.sub(r"(?im)(?:^\s*\d{1,3}\s*\n+\s*(?:days|hours|minutes|seconds)\s*(?:\n+\s*:\s*)?\n?){2,}", "", raw)
    lines, links, position, seen = [], [], 0, set()
    fence = None
    for original in raw.splitlines():
        line = original.strip()
        marker = re.match(r"(`{3,}|~{3,})", line)
        protected = bool(fence or marker or original.startswith(("    ", "\t")))
        if marker:
            fence = None if fence and marker[1][0] == fence else marker[1][0] if fence is None else fence
        if protected:
            lines.append(original)
            position += len(original) + 1
            continue
        text, found = _inline_links(line, url)
        leading = len(text) - len(text.lstrip())
        text = text.strip()
        visible = re.sub(r"^[#>*\-\s]+", "", text).strip()
        table = line.startswith("|")
        if line.startswith("# ") and visible == title or re.fullmatch(r"[:;]+", visible):
            continue
        if (line.startswith("# |") or line.startswith("#") and (
                re.match(r"(?i)(?:New and Upcoming Releases|TopCodes|List of Contents|Popular Guides|Characters by Elements)", visible)
                or visible.count("◆") >= 2)):
            continue
        link_chars = sum(len(item.text) for item in found)
        if not table and (visible.casefold() in NAV_LABELS or re.match(r"(?i)(?:Autoplay setting:|Add .+ on Google$)", visible)
                or (len(visible) < 200 and visible.count("›") >= 2)
                or (len(visible) < 80 and len(found) > 1 and link_chars > len(visible) * .8)):
            continue
        identity = visible.casefold()
        if not table and identity and identity in seen and not re.fullmatch(r"[\d\s:.,+%/-]+", visible):
            continue
        if identity:
            seen.add(identity)
        if not text and (not lines or not lines[-1]):
            continue
        for item in found:
            item.offset += position - leading
        links.extend(found)
        lines.append(text)
        position += len(text) + 1
    return "\n".join(lines).rstrip(), links


@dataclass(frozen=True)
class Paragraph:
    start: int
    end: int
    text: str


def paragraphs(content: str) -> list[Paragraph]:
    spans = []
    for line in re.finditer(r"[^\n]+", content):
        start, end = line.span()
        while end - start > 400:
            window = content[start:start + 400]
            stops = list(re.finditer(r"[。！？!?；;]|\.(?=\s)|\s+", window))
            cut = stops[-1].end() if stops and stops[-1].end() >= 60 else 400
            spans.append((start, start + cut))
            start += cut
        if start < end:
            spans.append((start, end))
    merged = []
    for start, end in spans:
        if (merged and merged[-1][1] - merged[-1][0] < 60 and end - merged[-1][0] <= 400
                and "\n\n" not in content[merged[-1][1]:start]):
            start = merged.pop()[0]
        merged.append((start, end))
    return [Paragraph(start, end, content[start:end]) for start, end in merged]


NUMBER = r"(?:\d{1,2}(?::\d{2}){1,2}|\d{4}(?:[-/]\d{1,2}){1,2}|v?\d+(?:\.\d+)*(?:-[a-z]+\d*)?)"
TOKEN = re.compile(NUMBER + r"|[a-z]+(?:['_-][a-z]+)*|[\u3400-\u9fff]+")
QUOTED = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|「([^」\n]+)」|『([^』\n]+)』|‘([^’\n]+)’|(?<!\w)\x27([^\x27\n]+)\x27(?!\w)')
STOP_WORDS = set("a an and are as at be by can did do does for from how in is it of on or the this to was what when where which who will with".split())
CJK_STOP = {"什么", "时候", "怎么", "如何", "多少", "哪些", "请问", "当前", "最新", "一下", "是否", "可以", "这个", "那个", "的是", "的吗", "了吗"}


def normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def terms(text: str) -> list[str]:
    tokens = []
    for part in TOKEN.findall(normalized_text(text)):
        if "\u3400" <= part[0] <= "\u9fff":
            tokens.extend(word for word in (part[i:i + 2] for i in range(len(part) - 1)) if word not in CJK_STOP)
            if len(part) == 1 and part not in "的了呢吗":
                tokens.append(part)
        elif part not in STOP_WORDS:
            if re.fullmatch(NUMBER, part):
                part = part.removeprefix("v")
                if ":" in part:
                    part = ":".join(str(int(piece)) for piece in part.split(":"))
                elif re.fullmatch(r"\d{4}(?:[-/]\d{1,2}){1,2}", part):
                    tokens.extend(str(int(piece)) for piece in re.split(r"[-/]", part))
            tokens.append(part)
    return tokens


@dataclass(frozen=True)
class QueryTerms:
    words: frozenset[str]
    required: frozenset[str]
    phrases: frozenset[str]

    @classmethod
    def parse(cls, query: str):
        phrases = frozenset(normalized_text(next(group for group in match.groups() if group))
                            for match in QUOTED.finditer(query))
        words = frozenset(terms(QUOTED.sub(" ", query)))
        return cls(words | phrases, frozenset(word for word in words if re.fullmatch(NUMBER, word)) | phrases, phrases)

    def matches(self, text: str) -> set[str]:
        normalized = normalized_text(text)
        return (self.words & set(terms(text))) | {phrase for phrase in self.phrases if phrase in normalized}


class QueryRelevance:
    """One query's page-level coverage, with missing terms included in the denominator."""
    def __init__(self, query: str, texts: list[str]):
        self.query = QueryTerms.parse(query)
        self.matches = [self.query.matches(text) for text in texts]
        self.weights = {word: math.log(1 + (len(texts) - count + .5) / (count + .5))
                        * (3 if word in self.query.required else 1)
                        for word in self.query.words
                        for count in [sum(word in matched for matched in self.matches)]}

    def coverage(self, index: int) -> float:
        matched = self.matches[index]
        if not self.query.required <= matched:
            return 0
        total = sum(self.weights.values())
        return sum(self.weights[word] for word in matched) / total if total else 0


class BM25:
    def __init__(self, texts: list[str]):
        self.documents = [Counter(terms(text)) for text in texts]
        self.lengths = [sum(item.values()) for item in self.documents]
        self.average = sum(self.lengths) / max(1, len(texts)) or 1
        counts = Counter(term for document in self.documents for term in document)
        self.idf = {term: math.log(1 + (len(texts) - count + .5) / (count + .5)) for term, count in counts.items()}

    def score(self, index: int, query_terms: set[str]) -> float:
        document = self.documents[index]
        norm = 1.5 * (.25 + .75 * self.lengths[index] / self.average)
        return sum(self.idf[term] * document[term] * 2.5 / (document[term] + norm)
                   for term in query_terms if term in document)


def excerpt(parts: list[Paragraph], scores: list[float]) -> str:
    if not parts:
        return ""
    ranked = sorted(range(len(parts)), key=lambda i: (-scores[i], i))
    chosen = {}
    for index in ranked:
        if scores[index] <= 0:
            continue
        proposed = {**chosen, index: parts[index].text}
        if len("\n\n".join(proposed[i] for i in sorted(proposed))) <= 500:
            chosen = proposed
    return "\n\n".join(chosen[i] for i in sorted(chosen))


DATE_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?:[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?|(\d{4}|\d{2}))(?!\d)")
MONTHS = {name: index for index, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
    ("nov", "november"), ("dec", "december")), 1) for name in names}
MONTH_NAME = r"(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
ENGLISH_DATE = re.compile(r"\b(" + MONTH_NAME + r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+((?:19|20)\d{2})\b", re.I)
RELATIVE_DATE = re.compile(r"\b(\d+)\s+(minute|hour|day|week)s?\s+ago\b", re.I)
DATE_LABEL = re.compile(r"(?i)(?:\b(?:date|updated|published|posted)(?:\s+(?:at|on))?\s*:?|发布时间|更新时间|发布日期|更新于)\s*")


def infer_date(url: str, content: str, today: date, acquired_at: datetime | None = None) -> WebDate:
    acquired = acquired_at.astimezone() if acquired_at is not None else datetime.combine(today, time())
    found, labeled = [], []
    head = decoded_text(content[:800])
    inputs = [("url", url, found), ("content", head, found)]
    inputs += [("content", head[match.end():match.end() + 50].split("\n", 1)[0], labeled)
               for match in DATE_LABEL.finditer(head)]
    for source, text, target in inputs:
        values = []
        for match in DATE_PATTERN.finditer(text):
            compact = match[4]
            month = int(compact[:2] if compact else match[2])
            day = int(compact[2:] if compact and len(compact) == 4 else match[3] or 1)
            precision = "day" if match[3] or compact and len(compact) == 4 else "month"
            values.append((int(match[1]), month, day, precision))
        values += [(int(m[3]), MONTHS[m[1].lower().rstrip(".")], int(m[2]), "day") for m in ENGLISH_DATE.finditer(text)]
        for year, month, day, precision in values:
            try:
                value = date(year, month, day)
            except ValueError:
                continue
            if value <= today:
                target.append((value, precision, source))
        if source == "content":
            for match in RELATIVE_DATE.finditer(text):
                seconds = int(match[1]) * {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}[match[2].lower()]
                if seconds <= (acquired.date() - date.min).days * 86400:
                    value = (acquired - timedelta(seconds=seconds)).date()
                    if value <= today:
                        target.append((value, "day", source))
    choices = labeled or found
    if not choices:
        return WebDate()
    value, precision, source = max(choices, key=lambda item: (item[0], item[1] == "day"))
    return WebDate(value=value.isoformat() if precision == "day" else value.strftime("%Y-%m"),
                   precision=precision, source=source)


def is_expired(inferred: WebDate, recency: str, today: date) -> bool:
    if recency == "any" or inferred.value is None or inferred.uncertain:
        return False
    value = date.fromisoformat(inferred.value + "-01" if inferred.precision == "month" else inferred.value)
    if inferred.precision == "month":
        value = value.replace(day=monthrange(value.year, value.month)[1])
    return value < today - timedelta(days={"week": 7, "month": 31, "year": 366}[recency])

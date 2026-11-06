"""Bounded comment Markdown, mirrored by the dependency-free browser core.

Only parser-owned nodes reach the fixed HTML vocabulary. HTML, entities, images,
headings and link titles are literal; containers require explicit indentation.
No network requests, extension hooks or HTML sanitization are involved.
"""

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit, urlunsplit

FEATURES = (
    "bold",
    "italic",
    "strike",
    "link",
    "quote",
    "unorderedList",
    "orderedList",
    "inlineCode",
    "codeBlock",
)
_ASCII = re.compile(r"^[!-/:-@\[-`{-~]$")
_QUOTE = re.compile(r"^ {0,3}>[ \t]?")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)$")
_LIST = re.compile(r"^( {0,3})([-+*]|[0-9]{1,9}[.)])(?:([ \t]+)(.*)|$)")


class MarkdownError(ValueError):
    """Reject the whole input when a resource or policy bound is exceeded."""


@dataclass(slots=True)
class Node:
    type: str
    children: list["Node"] = field(default_factory=list)
    value: str = ""
    href: str = ""
    language: str = ""
    ordered: bool = False
    start: int = 1
    tight: bool = True
    height: int = 0


@dataclass(slots=True)
class _Context:
    work: int = 0
    nodes: int = 0

    def step(self, amount: int = 1) -> None:
        self.work += amount
        if self.work > 2_000_000:
            raise MarkdownError("Markdown work limit exceeded")

    def depth(self, value: int) -> None:
        if value > 32:
            raise MarkdownError("Markdown depth limit exceeded")

    def node(self, kind: str, **fields: object) -> Node:
        self.nodes += 1
        if self.nodes > 100_000:
            raise MarkdownError("Markdown node limit exceeded")
        node = Node(kind, **fields)
        node.height = max((child.height + 1 for child in node.children), default=0)
        self.depth(node.height)
        return node


def safe_url(value: str) -> str | None:
    """Accept absolute HTTP(S)/mailto links without credentials or controls.

    URL values are escaped again at the HTML boundary. Unicode web hosts use
    IDNA and path/query characters are percent-encoded; no address is fetched.
    """
    if not value or re.search(r"[\s\x00-\x1f\x7f\\]", value):
        return None
    if not re.match(r"^(https?://|mailto:)", value, re.IGNORECASE):
        return None
    try:
        parts = urlsplit(value)
        if parts.username or parts.password:
            return None
        if parts.scheme.lower() == "mailto":
            if not parts.path or re.search(r"%0[ad]", value, re.IGNORECASE):
                return None
            return "mailto:" + value.split(":", 1)[1]
        host = parts.hostname
        if not host or any(char in host for char in "<>%\"'{}|^"):
            return None
        host = host.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = "[" + host + "]"
        port = parts.port
        if port is not None and (parts.scheme.lower(), port) not in {
            ("http", 80),
            ("https", 443),
        }:
            host += f":{port}"
        # Preserve percent escapes and syntax; HTML quoting remains independent.
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~[]")
        fragment = quote(parts.fragment, safe="/%?:@!$&'()*+,;=-._~[]#")
        return urlunsplit((parts.scheme.lower(), host, path, query, fragment))
    except (ValueError, UnicodeError):
        return None


def _punct(value: str) -> bool:
    return bool(
        value and (_ASCII.fullmatch(value) or unicodedata.category(value)[0] in "PS")
    )


def _space(value: str) -> bool:
    return not value or value.isspace() or value == "\ufeff"


@dataclass(eq=False, slots=True)
class _Token:
    node: Node
    previous: "_Token | None" = None
    next: "_Token | None" = None


@dataclass(slots=True)
class _Delimiter:
    marker: str
    count: int
    original: int
    opening: bool
    closing: bool
    token: _Token
    active: bool = True


def _inlines(source: str, ctx: _Context, depth: int) -> list[Node]:
    ctx.depth(depth)
    runs = {match.start(): len(match[0]) for match in re.finditer(r"`+", source)}
    positions: dict[int, list[int]] = {}
    for position, length in runs.items():
        positions.setdefault(length, []).append(position)

    def code_at(index: int) -> tuple[int, int | None]:
        length = runs.get(index)
        if length is None:
            end = index + 1
            while source[end : end + 1] == "`":
                end += 1
            length = end - index
        candidates = positions.get(length, [])
        ctx.step(len(candidates).bit_length() + 1)
        offset = bisect_right(candidates, index)
        return length, candidates[offset] if offset < len(candidates) else None

    brackets: dict[int, int] = {}
    stack: list[int] = []
    index = 0
    while index < len(source):
        ctx.step()
        if source[index] == "\\" and _ASCII.fullmatch(source[index + 1 : index + 2]):
            index += 2
            continue
        if source[index] == "`":
            length, close = code_at(index)
            index = (index if close is None else close) + length
            continue
        if source[index] == "[":
            stack.append(index)
        elif source[index] == "]" and stack:
            brackets[stack.pop()] = index
        index += 1

    def destination(start: int) -> tuple[str, int] | None:
        if source[start : start + 1] != "(":
            return None
        index = start + 1
        angled = source[index : index + 1] == "<"
        index += int(angled)
        value: list[str] = []
        nesting = 0
        while index < len(source):
            ctx.step()
            char = source[index]
            if char == "\\" and _ASCII.fullmatch(source[index + 1 : index + 2]):
                value.append(source[index + 1])
                index += 2
                continue
            if angled:
                if source[index : index + 2] == ">)":
                    return "".join(value), index + 2
                if _space(char) or char in "<>":
                    return None
            else:
                if char == "(":
                    nesting += 1
                    ctx.depth(nesting)
                if char == ")":
                    if not nesting:
                        return "".join(value), index + 1
                    nesting -= 1
                if _space(char):
                    return None
            value.append(char)
            index += 1
        return None

    head = _Token(Node("text"))
    tail = head
    delimiters: list[_Delimiter] = []
    text: list[str] = []

    def append(node: Node) -> _Token:
        nonlocal tail
        item = _Token(node, previous=tail)
        tail.next = item
        tail = item
        return item

    def flush() -> None:
        if text:
            append(ctx.node("text", value="".join(text)))
            text.clear()

    index = 0
    while index < len(source):
        ctx.step()
        char = source[index]
        after = source[index + 1 : index + 2]
        if char == "\\":
            if after == "\n":
                flush()
                append(ctx.node("hardBreak"))
                index += 2
                continue
            if _ASCII.fullmatch(after):
                text.append(after)
                index += 2
                continue
        if char == "\n":
            value = "".join(text)
            trailing = len(value) - len(value.rstrip(" "))
            text[:] = [value.rstrip(" ")]
            flush()
            append(ctx.node("hardBreak" if trailing >= 2 else "softBreak"))
            index += 1
            continue
        if char == "`":
            length, close = code_at(index)
            if close is not None:
                value = source[index + length : close].replace("\n", " ")
                if value.startswith(" ") and value.endswith(" ") and value.strip(" "):
                    value = value[1:-1]
                flush()
                append(ctx.node("code", value=value))
                index = close + length
                continue
            text.append("`" * length)
            index += length
            continue
        if char == "[" and index in brackets:
            close = brackets[index]
            target = destination(close + 1)
            before = index - 2
            slashes = 0
            while before >= 0 and source[before] == "\\":
                slashes += 1
                before -= 1
            if target and index > 0 and source[index - 1] == "!" and slashes % 2 == 0:
                text.append(source[index : target[1]])
                index = target[1]
                continue
            href = safe_url(target[0]) if target else None
            if href and close > index + 1:
                children = _inlines(source[index + 1 : close], ctx, depth + 1)
                if not any(node.type == "link" for node in walk(children)):
                    flush()
                    append(ctx.node("link", children=children, href=href))
                    index = target[1]
                    continue
        if char in "*_~":
            end = index + 1
            while source[end : end + 1] == char:
                end += 1
            count = end - index
            if char != "~" or count == 2:
                flush()
                before, after = source[max(0, index - 1) : index], source[end : end + 1]
                left = not _space(after) and (
                    not _punct(after) or _space(before) or _punct(before)
                )
                right = not _space(before) and (
                    not _punct(before) or _space(after) or _punct(after)
                )
                item = append(ctx.node("text", value=source[index:end]))
                delimiters.append(
                    _Delimiter(
                        char,
                        count,
                        count,
                        left and (char != "_" or not right or _punct(before)),
                        right and (char != "_" or not left or _punct(after)),
                        item,
                    )
                )
            else:
                text.append(source[index:end])
            index = end
            continue
        text.append(char)
        index += 1
    flush()

    def unlink(item: _Token) -> None:
        item.previous.next = item.next
        if item.next:
            item.next.previous = item.previous

    for closer_index, closer in enumerate(delimiters):
        while closer.active and closer.closing and closer.count:
            opener = None
            for opener_index in range(closer_index - 1, -1, -1):
                ctx.step()
                candidate = delimiters[opener_index]
                if (
                    not candidate.active
                    or not candidate.opening
                    or candidate.marker != closer.marker
                    or not candidate.count
                ):
                    continue
                ambiguous = (
                    (candidate.closing or closer.opening)
                    and (candidate.original + closer.original) % 3 == 0
                    and (candidate.original % 3 != 0 or closer.original % 3 != 0)
                )
                if candidate.marker != "~" and ambiguous:
                    continue
                opener = candidate
                break
            if opener is None:
                break
            amount = (
                2 if closer.marker == "~" or min(opener.count, closer.count) >= 2 else 1
            )
            children = []
            item = opener.token.next
            while item is not closer.token:
                ctx.step()
                children.append(item.node)
                item = item.next
            if not children:
                break
            kind = (
                "strike"
                if closer.marker == "~"
                else "strong"
                if amount == 2
                else "emphasis"
            )
            wrapped = _Token(
                ctx.node(kind, children=children), opener.token, closer.token
            )
            opener.token.next = wrapped
            closer.token.previous = wrapped
            for delimiter in delimiters[opener_index + 1 : closer_index]:
                delimiter.active = False
            opener.count -= amount
            closer.count -= amount
            opener.token.node.value = opener.marker * opener.count
            closer.token.node.value = closer.marker * closer.count
            for delimiter in (opener, closer):
                if not delimiter.count:
                    unlink(delimiter.token)
                    delimiter.active = False
    result: list[Node] = []
    item = head.next
    while item:
        node = item.node
        if node.type != "text" or node.value:
            if result and result[-1].type == node.type == "text":
                result[-1].value += node.value
            else:
                result.append(node)
        item = item.next
    return result


def _blank(line: str) -> bool:
    return not line.strip(" \t")


def _fence(line: str) -> re.Match | None:
    match = _FENCE.match(line)
    return match if match and not (match[1][0] == "`" and "`" in match[2]) else None


def _marker(line: str) -> dict | None:
    match = _LIST.match(line)
    if not match:
        return None
    ordered = match[2][0].isdigit()
    prefix = len(match[1]) + len(match[2])
    padding = 0
    for char in match[3] or " ":
        padding += 4 - (prefix + padding) % 4 if char == "\t" else 1
    width = 1 if padding > 4 else padding
    return {
        "ordered": ordered,
        "start": int(match[2][:-1]) if ordered else 1,
        "marker": match[2][-1] if ordered else match[2],
        "indent": len(match[1]),
        "width": prefix + width,
        "content": " " * (padding - width) + (match[4] or ""),
    }


def _strip_indent(line: str, width: int) -> str | None:
    column = index = 0
    while column < width and line[index : index + 1] in (" ", "\t"):
        column += 4 - column % 4 if line[index] == "\t" else 1
        index += 1
    return None if column < width else " " * (column - width) + line[index:]


def _blocks(lines: list[str], ctx: _Context, depth: int = 1) -> list[Node]:
    ctx.depth(depth)
    children = []
    index = 0
    while index < len(lines):
        ctx.step()
        line = lines[index]
        if _blank(line):
            index += 1
            continue
        opening = _fence(line)
        if opening:
            closing = re.compile(
                r"^ {0,3}" + opening[1][0] + "{" + str(len(opening[1])) + r",}[ \t]*$"
            )
            indent = len(line) - len(line.lstrip(" "))
            payload = []
            index += 1
            while index < len(lines):
                ctx.step()
                if closing.match(lines[index]):
                    index += 1
                    break
                remove = min(indent, len(lines[index]) - len(lines[index].lstrip(" ")))
                payload.append(lines[index][remove:])
                index += 1
            info = opening[2].strip()
            children.append(
                ctx.node(
                    "codeBlock",
                    value="\n".join(payload) + "\n" if payload else "",
                    language=info
                    if re.fullmatch(r"[a-zA-Z0-9_+-]{1,30}", info)
                    else "",
                )
            )
            continue
        if _QUOTE.match(line):
            nested = []
            while index < len(lines):
                ctx.step()
                prefix = _QUOTE.match(lines[index])
                if not prefix:
                    break
                nested.append(lines[index][prefix.end() :])
                index += 1
            children.append(ctx.node("quote", children=_blocks(nested, ctx, depth + 1)))
            continue
        first = _marker(line)
        if first:
            items = []
            loose = False

            def same(marker: dict | None, expected: dict = first) -> bool:
                return bool(
                    marker
                    and all(
                        marker[key] == expected[key]
                        for key in ("ordered", "marker", "indent")
                    )
                )

            while index < len(lines) and same(marker := _marker(lines[index])):
                nested = [marker["content"]]
                index += 1
                pending_blank = False
                while index < len(lines):
                    ctx.step()
                    if _blank(lines[index]):
                        pending_blank = True
                        nested.append("")
                        index += 1
                        continue
                    content = _strip_indent(lines[index], marker["width"])
                    if content is None:
                        break
                    loose |= pending_blank
                    pending_blank = False
                    nested.append(content)
                    index += 1
                if pending_blank and index < len(lines) and same(_marker(lines[index])):
                    loose = True
                while len(nested) > 1 and _blank(nested[-1]):
                    nested.pop()
                items.append(
                    ctx.node("listItem", children=_blocks(nested, ctx, depth + 1))
                )
            children.append(
                ctx.node(
                    "list",
                    ordered=first["ordered"],
                    start=first["start"],
                    tight=not loose,
                    children=items,
                )
            )
            continue
        paragraph = [re.sub(r"^ {1,3}(?! )", "", line)]
        index += 1
        while index < len(lines) and not _blank(lines[index]):
            ctx.step()
            marker = _marker(lines[index])
            if (
                _fence(lines[index])
                or _QUOTE.match(lines[index])
                or (marker and (not marker["ordered"] or marker["start"] == 1))
            ):
                break
            paragraph.append(re.sub(r"^ {1,3}(?! )", "", lines[index]))
            index += 1
        content = "\n".join(paragraph).rstrip(" \t")
        children.append(
            ctx.node("paragraph", children=_inlines(content, ctx, depth + 1))
        )
    return children


def walk(nodes: list[Node]):
    """Iterate a parser-owned tree without recursive visitor calls."""
    stack = list(reversed(nodes))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def parse(source: str) -> Node:
    """Parse a complete string or raise MarkdownError; never return partial output."""
    if not isinstance(source, str):
        raise TypeError("Expected Markdown string")
    if len(source.encode("utf-16-le", errors="surrogatepass")) // 2 > 100_000:
        raise MarkdownError("Markdown length limit exceeded")
    ctx = _Context()
    ctx.step(len(source))
    source = source.replace("\r\n", "\n").replace("\r", "\n").replace("\0", "\ufffd")
    lines = source.split("\n")
    if lines[-1] == "":
        lines.pop()
    return ctx.node("document", children=_blocks(lines, ctx))


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render(nodes: list[Node], plain: bool = False, inline: bool = False) -> str:
    output = []
    for node in nodes:
        kind = node.type
        if kind in ("text", "code"):
            value = node.value if plain else _escape(node.value)
            output.append(
                f"<code>{value}</code>" if kind == "code" and not plain else value
            )
        elif kind in ("softBreak", "hardBreak"):
            output.append("<br>\n" if kind == "hardBreak" and not plain else "\n")
        elif kind == "codeBlock":
            language = f' class="language-{node.language}"' if node.language else ""
            output.append(
                node.value.removesuffix("\n")
                if plain
                else f"<pre><code{language}>{_escape(node.value)}</code></pre>"
            )
        elif kind == "list":
            items = []
            for index, item in enumerate(node.children):
                if plain:
                    marker = f"{node.start + index}. " if node.ordered else "- "
                    items.append(
                        marker + _render(item.children, True).replace("\n", "\n  ")
                    )
                elif node.tight:
                    value = "\n".join(
                        _render(child.children, inline=True)
                        if child.type == "paragraph"
                        else _render([child])
                        for child in item.children
                    )
                    items.append(f"<li>{value}</li>")
                else:
                    items.append("<li>\n" + _render(item.children) + "\n</li>")
            value = "\n".join(items)
            tag = "ol" if node.ordered else "ul"
            start = f' start="{node.start}"' if node.ordered and node.start != 1 else ""
            output.append(value if plain else f"<{tag}{start}>\n{value}\n</{tag}>")
        else:
            value = _render(
                node.children, plain, kind not in ("quote", "document", "listItem")
            )
            if plain:
                output.append(value)
            elif kind == "link":
                output.append(
                    f'<a href="{_escape(node.href)}" rel="nofollow ugc noopener noreferrer">{value}</a>'
                )
            elif kind == "quote":
                output.append(f"<blockquote>\n{value}\n</blockquote>")
            else:
                tag = {
                    "paragraph": "p",
                    "strong": "strong",
                    "emphasis": "em",
                    "strike": "del",
                }[kind]
                output.append(f"<{tag}>{value}</{tag}>")
    return ("" if inline else "\n\n" if plain else "\n").join(output)


def render(source: str) -> str:
    """Render escaped HTML from validated, bounded Markdown."""
    return _render(parse(source).children)


def render_plain(source: str) -> str:
    """Visible plain text for email and structured data, without Markdown markers."""
    return _render(parse(source).children, plain=True)

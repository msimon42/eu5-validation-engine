"""Byte-preserving, bounded structural front end; parsing is not game validation."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

PARSER_VERSION = "lossless-1"
OPERATORS = (b"!=", b"?=", b"==", b"<=", b">=", b"=", b"<", b">")
DECLARATIONS = {"type", "template", "scripted_effect", "scripted_trigger", "scripted_value"}


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    text: str

    @property
    def span(self):
        return (self.start, self.end)


@dataclass(frozen=True)
class Node:
    kind: str
    start: int
    end: int
    key: str | None = None
    operator: str | None = None
    value: str | None = None
    children: tuple["Node", ...] = ()
    ordinal: int = 0
    head: tuple[str, ...] = ()
    value_start: int | None = None
    value_end: int | None = None
    tag: str | None = None
    recovered: bool = False

    @property
    def span(self):
        return (self.start, self.end)

    @property
    def is_block(self):
        return self.value_start is not None and self.value is None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def as_dict(self):
        return {"kind": self.kind, "span": [self.start, self.end], "key": self.key,
                "operator": self.operator, "value": self.value, "ordinal": self.ordinal,
                "head": list(self.head), "tag": self.tag, "recovered": self.recovered,
                "value_span": [self.value_start, self.value_end],
                "children": [c.as_dict() for c in self.children]}


@dataclass(frozen=True)
class Document:
    raw: bytes
    tokens: tuple[Token, ...]
    children: tuple[Node, ...]
    diagnostics: tuple[dict, ...]
    encoding: str
    bom: bytes
    newline: str
    sha256: str
    version: str = PARSER_VERSION

    @property
    def eligible(self):
        return self.encoding == "utf-8" and not self.diagnostics

    @property
    def root(self):
        return Node("document", 0, len(self.raw), children=self.children)

    def serialize(self) -> bytes:
        return self.raw

    def position(self, byte_offset: int) -> dict:
        """Byte offsets include BOM; decoded characters exclude BOM; lines are 1-based."""
        if self.encoding != "utf-8":
            raise ValueError("position map unavailable for unsupported encoding")
        if not 0 <= byte_offset <= len(self.raw):
            raise ValueError("byte offset out of range")
        if 0 < byte_offset < len(self.bom):
            raise ValueError("byte offset inside BOM")
        prefix = self.raw[len(self.bom):max(len(self.bom), byte_offset)].decode("utf-8", "strict")
        # CRLF is one line boundary; lone CR is also a line boundary.
        normalized = prefix.replace("\r\n", "\n").replace("\r", "\n")
        line_prefix = normalized.rsplit("\n", 1)[-1]
        return {"byte": byte_offset, "character": len(prefix),
                "line": normalized.count("\n") + 1, "column": len(line_prefix) + 1,
                "utf16_line": normalized.count("\n"),
                "utf16_column": len(line_prefix.encode("utf-16-le")) // 2}

    def byte_from_utf16(self, line: int, column: int) -> int:
        if self.encoding != "utf-8" or type(line) is not int or type(column) is not int or min(line, column) < 0:
            raise ValueError("invalid UTF-16 editor position")
        text = self.raw[len(self.bom):].decode("utf-8", "strict")
        lines = text.splitlines(keepends=True)
        if not lines or text.endswith(("\n", "\r")):
            lines.append("")
        if line >= len(lines):
            raise ValueError("editor line out of range")
        content = lines[line].rstrip("\r\n")
        units = 0
        for index, character in enumerate(content):
            if units == column:
                return len(self.bom) + len(("".join(lines[:line]) + content[:index]).encode())
            units += len(character.encode("utf-16-le")) // 2
            if units > column:
                raise ValueError("editor column splits a surrogate pair")
        if units != column:
            raise ValueError("editor column out of range")
        return len(self.bom) + len(("".join(lines[:line]) + content).encode())

    def byte_offset(self, character_offset: int) -> int:
        text = self.raw[len(self.bom):].decode("utf-8", "strict")
        if not 0 <= character_offset <= len(text):
            raise ValueError("character offset out of range")
        return len(self.bom) + len(text[:character_offset].encode("utf-8"))


def _newline(raw: bytes) -> str:
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    cr = raw.count(b"\r") - crlf
    present = [name for name, count in (("CRLF", crlf), ("LF", lf), ("CR", cr)) if count]
    return present[0] if len(present) == 1 else "mixed" if present else "none"


def parse(raw: bytes, *, max_bytes: int = 8_000_000, max_tokens: int = 250_000,
          max_depth: int = 128, dialect: str = "script") -> Document:
    if not isinstance(raw, bytes):
        raise TypeError("parse requires immutable bytes")
    diagnostics: list[dict] = []
    tokens: list[Token] = []
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    encoding = "utf-8"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")):
        encoding = "unsupported"
        diagnostics.append({"code": "unsupported_encoding", "span": [0, min(4, len(raw))]})
    else:
        try:
            raw[len(bom):].decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            encoding = "invalid"
            diagnostics.append({"code": "invalid_utf8", "span": [exc.start + len(bom), exc.end + len(bom)]})
    if len(raw) > max_bytes:
        diagnostics.append({"code": "byte_limit", "span": [0, len(raw)]})
    if encoding != "utf-8" or len(raw) > max_bytes:
        token = Token("opaque", 0, len(raw), "")
        return Document(raw, (token,), (Node("opaque", 0, len(raw), recovered=True),),
                        tuple(diagnostics), encoding, bom, _newline(raw), digest(raw))

    def emit(kind, start, end):
        tokens.append(Token(kind, start, end, raw[start:end].decode("utf-8")))

    i, size = 0, len(raw)
    if bom:
        emit("bom", 0, 3)
        i = 3
    while i < size:
        if len(tokens) >= max_tokens:
            diagnostics.append({"code": "token_limit", "span": [i, size]})
            emit("opaque", i, size)
            break
        start = i
        c = raw[i]
        if c in b" \t\r\n":
            i += 1
            while i < size and raw[i] in b" \t\r\n":
                i += 1
            emit("trivia", start, i)
        elif c == 35:
            while i < size and raw[i] not in b"\r\n":
                i += 1
            emit("comment", start, i)
        elif c == 34:
            i += 1
            closed = False
            while i < size:
                if raw[i] == 92:
                    i = min(size, i + 2)
                elif raw[i] == 34:
                    i += 1
                    closed = True
                    break
                else:
                    i += 1
            emit("string", start, i)
            if not closed:
                diagnostics.append({"code": "unterminated_string", "span": [start, i]})
        elif raw.startswith(b"[[", i):
            end = raw.find(b"]]", i + 2)
            i = size if end < 0 else end + 2
            emit("template", start, i)
            if end < 0:
                diagnostics.append({"code": "unterminated_template", "span": [start, i]})
        elif raw.startswith(b"@[", i):
            depth = 1
            i += 2
            while i < size and depth:
                if raw[i] == 91:
                    depth += 1
                elif raw[i] == 93:
                    depth -= 1
                i += 1
            emit("expression", start, i)
            if depth:
                diagnostics.append({"code": "unterminated_expression", "span": [start, i]})
        elif c in (123, 125):
            i += 1
            emit("open" if c == 123 else "close", start, i)
        else:
            op = next((op for op in OPERATORS if raw.startswith(op, i)), None)
            if op:
                i += len(op)
                emit("operator", start, i)
            else:
                i += 1
                while i < size and raw[i] not in b" \t\r\n{}\"#=<>!?":
                    i += 1
                emit("atom", start, i)
                if c in (33, 63):
                    diagnostics.append({"code": "partial_operator", "span": [start, i]})

    significant = [token for token in tokens if token.kind not in {"trivia", "comment", "bom"}]
    cursor = 0

    def items(depth: int, opener: Token | None = None):
        nonlocal cursor
        result: list[Node] = []
        counts: dict[str, int] = {}
        if depth > max_depth:
            start = significant[cursor].start if cursor < len(significant) else size
            diagnostics.append({"code": "depth_limit", "span": [start, size]})
            cursor = len(significant)
            return (Node("opaque", start, size, recovered=True),), size, True
        while cursor < len(significant):
            token = significant[cursor]
            if token.kind == "close":
                cursor += 1
                if opener:
                    return tuple(result), token.end, False
                diagnostics.append({"code": "unexpected_close", "span": [token.start, token.end]})
                result.append(Node("error", token.start, token.end, recovered=True))
                continue
            if token.kind == "open":
                cursor += 1
                children, end, recovered = items(depth + 1, token)
                result.append(Node("block", token.start, end, children=children,
                                   value_start=token.start, value_end=end, recovered=recovered))
                continue
            if token.kind in {"operator", "opaque"}:
                cursor += 1
                result.append(Node("error" if token.kind == "operator" else "opaque", token.start,
                                   token.end, value=token.text, recovered=True))
                if token.kind == "operator":
                    diagnostics.append({"code": "unexpected_operator", "span": [token.start, token.end]})
                continue
            cursor += 1
            head = [token.text]
            if token.text in DECLARATIONS:
                while cursor < len(significant) and significant[cursor].kind in {"atom", "string"}:
                    head.append(significant[cursor].text)
                    cursor += 1
            key = head[1] if len(head) > 1 else head[0]
            ordinal = counts.get(key, 0)
            counts[key] = ordinal + 1
            operator = None
            if cursor < len(significant) and significant[cursor].kind == "operator":
                operator = significant[cursor].text
                cursor += 1
            if cursor < len(significant) and significant[cursor].kind == "open":
                opening = significant[cursor]
                cursor += 1
                children, end, recovered = items(depth + 1, opening)
                result.append(Node("declaration" if len(head) > 1 else "property" if operator else "tagged_block",
                                   token.start, end, key=key, operator=operator, children=children,
                                   ordinal=ordinal, head=tuple(head), value_start=opening.start,
                                   value_end=end, tag=token.text if not operator else None, recovered=recovered))
            elif operator and cursor < len(significant) and significant[cursor].kind not in {"close", "operator"}:
                val = significant[cursor]
                cursor += 1
                if cursor < len(significant) and significant[cursor].kind == "open":
                    opening = significant[cursor]
                    cursor += 1
                    children, end, recovered = items(depth + 1, opening)
                    result.append(Node("gui_head" if len(head) > 1 else "property", token.start, end,
                                       key=key, operator=operator, children=children, ordinal=ordinal,
                                       head=tuple(head), value_start=opening.start, value_end=end,
                                       tag=val.text, recovered=recovered))
                else:
                    result.append(Node("property", token.start, val.end, key=key, operator=operator,
                                       value=val.text, ordinal=ordinal, head=tuple(head),
                                       value_start=val.start, value_end=val.end))
            elif operator:
                diagnostics.append({"code": "missing_value", "span": [token.start, token.end]})
                result.append(Node("error", token.start, token.end, key=key, operator=operator, recovered=True))
            else:
                result.append(Node("constant_expression" if token.kind == "expression" else
                                   "template" if token.kind == "template" else "bare", token.start,
                                   token.end, value=token.text, ordinal=ordinal, head=tuple(head)))
        if opener:
            diagnostics.append({"code": "missing_close", "span": [size, size],
                                "related_span": [opener.start, opener.end]})
        return tuple(result), size, bool(opener)

    children, _, _ = items(0)
    return Document(raw, tuple(tokens), children, tuple(diagnostics), encoding, bom,
                    _newline(raw), digest(raw))


def serialize_original(document: Document) -> bytes:
    return document.raw


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    replacement: bytes
    expected_old_sha256: str
    occurrence: int | None = None


def apply_edits(document: Document, edits: Iterable[Edit | dict], expected_hash: str,
                *, allow_syntax_repair: bool = False) -> bytes:
    """Only declared original-byte intervals change; stale/ambiguous edits fail closed."""
    if expected_hash != document.sha256:
        raise ValueError("stale document hash")
    if not document.eligible and not allow_syntax_repair:
        raise ValueError("document has unsupported or recovered regions")
    normalized: list[Edit] = []
    for edit in edits:
        if isinstance(edit, dict):
            allowed = {"start", "end", "replacement", "expected_old_sha256", "occurrence"}
            if set(edit) - allowed or not {"start", "end", "replacement", "expected_old_sha256"} <= set(edit):
                raise ValueError("invalid structural edit fields")
            edit = Edit(edit["start"], edit["end"], edit["replacement"],
                        edit["expected_old_sha256"], edit.get("occurrence"))
        if not isinstance(edit, Edit) or type(edit.start) is not int or type(edit.end) is not int:
            raise ValueError("edit coordinates must be integers")
        if edit.occurrence is not None and (type(edit.occurrence) is not int or edit.occurrence < 0):
            raise ValueError("invalid occurrence ordinal")
        if not isinstance(edit.replacement, bytes):
            raise ValueError("replacement must be bytes")
        if not 0 <= edit.start <= edit.end <= len(document.raw):
            raise ValueError("edit outside document")
        if digest(document.raw[edit.start:edit.end]) != edit.expected_old_sha256:
            raise ValueError("stale old-byte hash")
        if edit.occurrence is not None and not any(n.ordinal == edit.occurrence and
                (n.start == edit.start and n.end == edit.end or
                 n.value_start == edit.start and n.value_end == edit.end) for n in document.root.walk()):
            raise ValueError("occurrence precondition failed")
        normalized.append(edit)
    normalized.sort(key=lambda edit: (edit.start, edit.end))
    for left, right in zip(normalized, normalized[1:]):
        if left.end > right.start or left.start == right.start:
            raise ValueError("overlapping or ambiguous insertion edits")
    pieces, cursor = [], 0
    for edit in normalized:
        pieces.extend((document.raw[cursor:edit.start], edit.replacement))
        cursor = edit.end
    pieces.append(document.raw[cursor:])
    result = b"".join(pieces)
    reparsed = parse(result)
    if not reparsed.eligible:
        raise ValueError("edited output does not strict-reparse")
    return result

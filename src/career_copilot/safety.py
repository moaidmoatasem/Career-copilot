"""Treat every email, job post, message and feed item as untrusted input.

Nothing here blocks content. It cleans it (invisible characters, hidden HTML) and attaches
flags so the model and the human can see when external text tries to steer the agent,
asks for credentials, or looks like a recruitment scam.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

_INVISIBLE = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")

_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "instruction_override",
        "warning",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|any|your|the)\b"
            r"[^.\n]{0,25}\b(?:instructions?|prompts?|rules|guidelines|directions)\b",
            re.I,
        ),
    ),
    (
        "role_hijack",
        "warning",
        re.compile(r"\b(?:you are now|act as (?:an?|the) |pretend (?:to be|you are)|from now on,? you)", re.I),
    ),
    (
        "prompt_reference",
        "warning",
        re.compile(r"\b(?:system prompt|developer message|hidden instructions?|jailbreak|prompt injection)\b", re.I),
    ),
    (
        "markup_injection",
        "warning",
        re.compile(
            r"</?\s*(?:system|assistant|instructions?|tool_call|function_call)\s*>|\[/?INST\]|<\|im_(?:start|end)\|>",
            re.I,
        ),
    ),
    (
        "agent_action_request",
        "warning",
        re.compile(
            r"\b(?:call|invoke|run|execute)\s+(?:the\s+)?(?:tool|function)s?\b|\bmark_executed\b"
            r"|\bdraft_(?:message_reply|post|comment|application|outreach)\b|\bpropose_profile_edit\b",
            re.I,
        ),
    ),
    (
        "credential_request",
        "warning",
        re.compile(
            r"\b(?:password|passcode|one[- ]time (?:code|password)|otp|2fa code|verification code|session cookie"
            r"|li_at|api key|access token)\b",
            re.I,
        ),
    ),
    (
        # Payment channels scammers use. Fees are judged separately, by who is asked to pay (_fee_request).
        "scam_signal",
        "warning",
        re.compile(r"\b(?:western union|moneygram|gift cards?|crypto(?:currency)? payment)\b", re.I),
    ),
    (
        "sensitive_document_request",
        "info",
        re.compile(r"\b(?:passport (?:copy|number|details)|national id|id card copy|bank statement|iban)\b", re.I),
    ),
]

_BLOCK_TAGS = {
    "p", "div", "br", "tr", "li", "ul", "ol", "table", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote", "hr",
}
_SKIP_TAGS = {"script", "style", "head", "title", "noscript", "template"}
_VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "col", "area", "base", "embed"}
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem|%)?\s*(?:;|$)"
    r"|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)|max-height\s*:\s*0(?:px)?\s*(?:;|$)",
    re.I,
)
_HTML_HINT = re.compile(r"<\s*(?:html|body|div|table|p|a|span|br|td)\b", re.I)


class _HTMLToText(HTMLParser):
    """HTML → text that keeps link targets next to their text and separates hidden text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_parts: list[str] = []
        self._stack: list[tuple[str, bool, bool]] = []  # (tag, hidden, skipped)
        self._href: str | None = None
        self._link_text: list[str] = []

    def _hidden(self) -> bool:
        return any(hidden for _, hidden, _ in self._stack)

    def _skipped(self) -> bool:
        return any(skipped for _, _, skipped in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag in _BLOCK_TAGS:
            self._break()
        if tag in _VOID_TAGS:
            return
        hidden = bool(_HIDDEN_STYLE.search(attr.get("style", ""))) or "hidden" in attr
        self._stack.append((tag, hidden, tag in _SKIP_TAGS))
        if tag == "a" and not self._hidden() and not self._skipped():
            self._flush_link()
            self._href = attr.get("href", "").strip() or None
            self._link_text = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if tag == "a":
            self._flush_link()
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_data(self, data: str) -> None:
        if self._skipped():
            return
        if self._hidden():
            self.hidden_parts.append(data)
        elif self._href is not None:
            self._link_text.append(data)
        else:
            self.parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush_link()

    def _break(self) -> None:
        if self._href is not None:
            self._link_text.append(" | ")
        else:
            self.parts.append("\n")

    def _flush_link(self) -> None:
        if self._href is None:
            return
        text = " ".join("".join(self._link_text).split())
        text = re.sub(r"(?:\s*\|\s*)+", " | ", text).strip(" |")
        self.parts.append(f"{text} <{self._href}>" if text else f"<{self._href}>")
        self.parts.append("\n")
        self._href = None
        self._link_text = []


def looks_like_html(text: str) -> bool:
    return bool(_HTML_HINT.search(text))


def html_to_text(html: str) -> tuple[str, str]:
    """Return (visible_text, hidden_text)."""
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts), " ".join(parser.hidden_parts)


def clean_text(text: str, max_len: int | None = None) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


# A fee is a scam signal only when you are the one asked to pay it. Genuine Gulf offers often say
# the employer covers visa and medical fees, which is the opposite of a scam.
_FEE = re.compile(
    r"\b(?:(?:visa|processing|registration|training|medical|placement|application|recruitment|agency"
    r"|admin(?:istration)?|joining|documentation)\s+)*fees?\b|\bsecurity deposit\b",
    re.I,
)
_PAYMENT_ASK = re.compile(
    r"\b(?:pay(?:ing|ment|able)?|transfer(?:ring)?|send(?:ing)?|deposit(?:ing)?|wire|remit|must|required"
    r"|needs? to)\b",
    re.I,
)
_NOT_YOU = r"(?!\s+(?:you|yourself|the candidate|candidates?|the applicant|applicants?)\b)"
_EMPLOYER_PAYS = re.compile(
    r"\b(?:covered|reimbursed|waived|sponsored)\b"
    rf"|\b(?:paid|borne|handled|settled)\s+(?:for\s+)?by\b{_NOT_YOU}"
    r"|\b(?:we|company|employer|client|organi[sz]ation)\s+(?:will\s+|shall\s+)?(?:fully\s+)?"
    r"(?:pays?|covers?|handles?|bears?|sponsors?|takes? care of)\b"
    r"|\b(?:free of charge|at no (?:extra |additional )?cost|no (?:\w+\s+){0,2}fees?"
    r"|without (?:any )?(?:fees?|cost|charge))\b"
    r"|\bnever\s+(?:\w+\s+){0,4}(?:pay|ask|charge|request|require)\w*"
    r"|\b(?:do|does|will|shall)\s*(?:not|n't)\s+(?:ask|charge|request|require)\w*",
    re.I,
)
_NEGATED = re.compile(r"(?:\bnot|n't)\s+(?:\w+\s+)?$", re.I)  # "not covered", "isn't fully covered"
_SENTENCE = re.compile(r"[^.!?;\n]+")


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, b[0] - a[1], a[0] - b[1])


def _fee_request(text: str) -> tuple[int, int] | None:
    """Span of a fee you are asked to pay: a request to pay sits nearer the fee than any sign the employer pays."""
    for sentence in _SENTENCE.finditer(text):
        part, offset = sentence.group(), sentence.start()
        fees = [m.span() for m in _FEE.finditer(part)]
        if not fees:
            continue
        benign, asks = [], []
        for m in _EMPLOYER_PAYS.finditer(part):
            # "not covered" means you pay.
            (asks if _NEGATED.search(part[: m.start()]) else benign).append(m.span())
        asks += [m.span() for m in _PAYMENT_ASK.finditer(part)
                 if not any(_gap(m.span(), other) == 0 for other in benign + fees)]
        for fee in fees:
            ask = min((_gap(fee, a) for a in asks), default=None)
            calm = min((_gap(fee, b) for b in benign), default=None)
            if ask is not None and (calm is None or ask <= calm):
                return offset + fee[0], offset + fee[1]
    return None


def detect_flags(text: str) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    for flag_type, severity, pattern in _PATTERNS:
        match = pattern.search(text)
        span = match.span() if match else _fee_request(text) if flag_type == "scam_signal" else None
        if span:
            start, end = max(0, span[0] - 30), min(len(text), span[1] + 30)
            excerpt = " ".join(text[start:end].split())
            flags.append({"type": flag_type, "severity": severity, "excerpt": excerpt[:120]})
    return flags


def prepare_untrusted(raw: str, max_len: int = 20_000) -> tuple[str, list[dict[str, str]]]:
    """Clean external content and return it with safety flags."""
    flags: list[dict[str, str]] = []
    invisible = len(_INVISIBLE.findall(raw))
    if looks_like_html(raw):
        visible, hidden = html_to_text(raw)
        hidden = clean_text(hidden)
        if hidden:
            flags.append(
                {"type": "hidden_html_text", "severity": "info", "excerpt": f"{len(hidden)} characters of hidden text removed"}
            )
            for flag in detect_flags(hidden):
                flags.append({**flag, "type": f"hidden_{flag['type']}", "severity": "warning"})
    else:
        visible = raw
    if invisible > 5:
        flags.append(
            {"type": "invisible_characters", "severity": "info", "excerpt": f"{invisible} invisible characters removed"}
        )
    text = clean_text(visible, max_len)
    flags.extend(detect_flags(text))
    return text, flags


def has_warning(flags: list[dict[str, str]], types: set[str] | None = None) -> bool:
    return any(f["severity"] == "warning" and (types is None or f["type"] in types) for f in flags)

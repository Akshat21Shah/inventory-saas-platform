"""How many SMS parts a text takes (ADR-060): plain GSM-7 text fits 160 characters in one part
(153 a part when longer); any other character (Devanagari, ₹, curly quotes) makes the whole
message Unicode, 70 characters in one part (67 a part when longer). Each part is charged."""

import math

GSM_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "ÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM_EXTENDED = "^{}\\[~]|€\f"  # each takes two characters


def is_unicode(text: str) -> bool:
    return any(c not in GSM_BASIC and c not in GSM_EXTENDED for c in text)


def length(text: str) -> int:
    """Characters as the network counts them (UTF-16 code units for Unicode)."""
    if is_unicode(text):
        return len(text.encode("utf-16-le")) // 2
    return sum(2 if c in GSM_EXTENDED else 1 for c in text)


def parts(text: str) -> int:
    if not text:
        return 0
    size = length(text)
    single, each = (70, 67) if is_unicode(text) else (160, 153)
    return 1 if size <= single else math.ceil(size / each)

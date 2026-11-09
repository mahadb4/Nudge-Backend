"""Text normalisation shared by every validator (port of the frontend's clean() and cleanMulti()).

Framework-free. Control characters are detected here and rejected by validators (validation spec);
tab, newline and carriage return count as whitespace, not as control characters.
"""

import re
import unicodedata

# C0 controls except tab, newline and carriage return; DEL; C1 controls.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Soft hyphen, zero-width characters, bidi marks, overrides and isolates, word joiners, BOM.
_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_WHITESPACE = re.compile(r"\s+")


def has_control_chars(value: str) -> bool:
    return bool(_CONTROL.search(value))


def strip_control_chars(value: str) -> str:
    """Control characters become spaces, so words around them do not run together."""
    return _CONTROL.sub(" ", value)


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def strip_invisible(value: str) -> str:
    return _INVISIBLE.sub("", value)


def clean(value: str) -> str:
    """Single-line text: NFC, invisible characters removed, whitespace collapsed to one space,
    trimmed."""
    return _WHITESPACE.sub(" ", strip_invisible(unicodedata.normalize("NFC", value))).strip()


def clean_multi(value: str) -> str:
    """Multi-line text: like clean() but line breaks are kept (CRLF and CR become LF)."""
    return strip_invisible(unicodedata.normalize("NFC", normalize_newlines(value))).strip()


def contains_markup(value: str) -> bool:
    return "<" in value or ">" in value


def has_letter(value: str) -> bool:
    return any(character.isalpha() for character in value)

"""Ported from the frontend's tests/unit/validate.test.ts where the rule is the same."""

from common.text import (
    clean,
    clean_multi,
    contains_markup,
    has_control_chars,
    has_letter,
    normalize_newlines,
    strip_invisible,
)


def test_clean_trims_and_collapses_whitespace():
    assert clean("  Ali   Raza  ") == "Ali Raza"


def test_newlines_in_a_single_line_field_collapse_to_one_space():
    assert clean("Ali\n\r\nRaza") == "Ali Raza"


def test_invisible_characters_are_removed():
    assert clean("A​l‮i") == "Ali"
    assert strip_invisible("﻿x­") == "x"


def test_nfc_normalisation():
    assert clean("José") == "José"


def test_control_characters_are_detected_not_stripped():
    assert has_control_chars("Al\x00i")
    assert has_control_chars("Al\x07i")
    assert has_control_chars("x\x7f")
    assert has_control_chars("x\x85")
    assert clean("Al\x00i") == "Al\x00i"  # clean() never hides them; validators reject them


def test_tab_newline_and_carriage_return_are_whitespace_not_control():
    assert not has_control_chars("a\tb\nc\rd")


def test_clean_multi_keeps_line_breaks_and_normalises_them():
    assert clean_multi("  Hi\r\n\r\nthere\r") == "Hi\n\nthere"
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"


def test_markup_and_letters():
    assert contains_markup("<b>") and contains_markup("a>b")
    assert not contains_markup("O'Brien")
    for name in ["O'Brien", "José", "Anne-Marie", "李雷", "محمد"]:
        assert has_letter(name)
    for not_name in ["12345", "٣٤٥٦", "---", "..."]:
        assert not has_letter(not_name)

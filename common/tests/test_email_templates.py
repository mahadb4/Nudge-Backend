"""The designed (HTML) emails: both parts exist, the text part holds the code and link, every
inserted value is escaped, nothing is logged, and preview_email is dev-only. In-memory mail backend
only; no real mail."""

import logging
import re

import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from common.constants import EmailKind
from common.email_templates.renderer import EmailRenderer
from common.interfaces import EmailMessage
from common.messages import Messages
from config import container

EVIL_NAME = '<script>alert("x")</script> O\'Brien & "Sons"'
CODE = "482915"
RESET_LINK = "http://localhost:5173/new-password?token=abc-123&x=1"
SIGN_IN = "http://localhost:5173/sign-in"


def message(kind: EmailKind, **extra: str) -> EmailMessage:
    return EmailMessage(to="a@example.com", subject="s", text_body="t", kind=kind, **extra)


def html_for(kind: EmailKind, **extra: str) -> str:
    html = EmailRenderer().render_html(message(kind, **extra))
    assert html
    return html


def send(**fields: object) -> mail.EmailMessage:
    container.email_sender().send(EmailMessage(to="a@example.com", **fields))
    return mail.outbox[-1]


def html_part(sent: mail.EmailMessage) -> str:
    (alternative,) = sent.alternatives
    assert alternative[1] == "text/html"
    return alternative[0]


# ---- both parts exist


def test_a_designed_email_is_multipart_with_a_text_and_an_html_part():
    sent = send(
        subject="s",
        text_body=Messages.EMAIL_VERIFY_CODE_BODY.render(CODE),
        kind=EmailKind.VERIFY_CODE,
        recipient_name="Ali",
        code=CODE,
    )
    assert sent.body == Messages.EMAIL_VERIFY_CODE_BODY.render(CODE)
    assert CODE in html_part(sent) and "<table" in html_part(sent)
    assert sent.message().get_content_type() == "multipart/alternative"


def test_a_message_without_a_kind_stays_plain_text_only():
    sent = send(subject="s", text_body="plain")
    assert sent.alternatives == [] and sent.body == "plain"


# ---- content of each kind


def test_the_code_email_shows_the_code_in_a_large_monospace_block_with_validity():
    html = html_for(EmailKind.VERIFY_CODE, code=CODE, recipient_name="Ali")
    assert re.search(r"font-size:40px[^>]*>" + CODE + "<", html)
    assert "monospace" in html
    assert Messages.EMAIL_VERIFY_VALID.value in html
    assert Messages.EMAIL_VERIFY_NOT_YOU.value in html
    assert Messages.EMAIL_GREETING.render("Ali") in html


def test_the_reset_email_has_a_button_and_the_plain_link_below_it():
    html = html_for(EmailKind.RESET_LINK, link=RESET_LINK, recipient_name="Ali")
    assert Messages.EMAIL_RESET_BUTTON.value in html
    assert html.count("token=abc-123&amp;x=1") == 3  # button href, link href, link text
    assert html.index(Messages.EMAIL_RESET_BUTTON.value) < html.index(
        Messages.EMAIL_RESET_LINK_LABEL.value
    )
    assert Messages.EMAIL_RESET_VALID.value in html


def test_no_greeting_without_a_name():
    assert "Hi" not in html_for(EmailKind.VERIFY_CODE, code=CODE)


# ---- design rules


@pytest.mark.parametrize("kind", list(EmailKind))
def test_the_layout_is_safe_table_based_and_self_contained(kind):
    html = html_for(kind, code=CODE, link=SIGN_IN, recipient_name="Ali")
    lowered = html.lower()
    assert "max-width:600px" in lowered
    assert "<script" not in lowered and "<img" not in lowered and "<link" not in lowered
    assert "http://" not in re.sub(r'href="[^"]*"', "", html).replace(SIGN_IN, "")
    assert "src=" not in lowered and "url(" not in lowered
    assert "prefers-color-scheme: dark" in lowered and 'name="color-scheme"' in lowered
    assert "<table" in lowered and 'role="presentation"' in lowered
    assert Messages.EMAIL_BRAND_NAME.value in html
    assert Messages.EMAIL_FOOTER_AUTOMATED.value in html


# ---- escaping


@pytest.mark.parametrize("kind", list(EmailKind))
def test_every_inserted_value_is_escaped(kind):
    html = html_for(
        kind,
        recipient_name=EVIL_NAME,
        code='<b onmouseover="x">1</b>',
        link='http://x/?a="><script>1</script>&b=1',
    )
    assert "<script" not in html.lower()
    assert "<b onmouseover" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "O&#x27;Brien &amp; &quot;Sons&quot;" in html


def test_a_hostile_name_in_a_real_send_cannot_open_a_tag():
    sent = send(
        subject="s",
        text_body="t",
        kind=EmailKind.VERIFY_CODE,
        recipient_name=EVIL_NAME,
        code=CODE,
    )
    assert "<script" not in html_part(sent).lower()


# ---- never logged


def test_the_code_and_the_link_are_never_written_to_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        html_for(EmailKind.VERIFY_CODE, code=CODE, recipient_name="Ali")
        html_for(EmailKind.RESET_LINK, link=RESET_LINK, recipient_name="Ali")
        send(subject="s", text_body="t", kind=EmailKind.VERIFY_CODE, code=CODE)
    assert CODE not in caplog.text and "abc-123" not in caplog.text


# ---- preview_email


def test_preview_email_refuses_under_the_test_settings_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    with pytest.raises(CommandError) as info:
        call_command("preview_email", "verify_code")
    assert "preview_email" in str(info.value) and "config.settings.dev" in str(info.value)
    assert list(tmp_path.iterdir()) == []


def test_preview_email_knows_every_kind_and_rejects_others():
    with pytest.raises(CommandError):
        call_command("preview_email", "nonsense")


# ---- the look matches the app (colours from Nudge-frontend/src/styles/tokens.css)


def dark_block(html: str) -> str:
    return html[html.index("prefers-color-scheme: dark") : html.index("</style>")]


def test_the_logo_is_the_app_mark_drawn_without_images():
    html = html_for(EmailKind.VERIFY_CODE, code=CODE)
    assert 'bgcolor="#171717"' in html and "width:40px;height:40px" in html
    assert "border-radius:12px;font-family:Arial" in html
    assert "color:#3ecf8e" in html and "&rsaquo;" in html and "color:#ffffff" in html
    assert html.index("&rsaquo;") < html.index(Messages.EMAIL_BRAND_NAME.value)


def test_light_is_the_default_white_page_and_card_with_gray_borders():
    html = html_for(EmailKind.VERIFY_CODE, code=CODE)
    assert 'class="bg" style="margin:0;padding:0;background-color:#ffffff;"' in html
    assert "background-color:#ffffff;border:1px solid #d9d9d9;border-radius:12px" in html
    assert "color:#171717" in html


def test_the_code_sits_in_a_light_gray_box_not_a_dark_one():
    html = html_for(EmailKind.VERIFY_CODE, code=CODE)
    box = re.search(r'class="code" style="([^"]*)"', html).group(1)
    assert "background-color:#f2f2f2" in box and "border:1px solid #d9d9d9" in box
    assert "color:#171717" in box and "monospace" in box and "font-size:40px" in box


@pytest.mark.parametrize("kind", [EmailKind.REGISTER_EXISTING, EmailKind.RESET_LINK])
def test_the_button_is_black_with_white_text_and_the_app_radius(kind):
    html = html_for(kind, link=SIGN_IN)
    cell = re.search(r'<td class="btn"[^>]*style="([^"]*)"', html).group(1)
    assert "background-color:#171717" in cell and "border-radius:8px" in cell
    assert re.search(r'class="btn-text"[^>]*style="[^"]*color:#ffffff', html)


@pytest.mark.parametrize("kind", list(EmailKind))
def test_green_is_only_the_top_line_and_the_logo_chevron(kind):
    html = html_for(kind, code=CODE, link=SIGN_IN)
    line = re.search(r'<td bgcolor="#3ecf8e" height="3" style="([^"]*)"', html).group(1)
    assert "height:3px" in line and "background-color:#3ecf8e" in line
    assert html.index("#3ecf8e") < html.index(Messages.EMAIL_BRAND_NAME.value)  # the line is on top
    rest = html.replace('bgcolor="#3ecf8e"', "").replace("background-color:#3ecf8e", "")
    assert rest.lower().count("#3ecf8e") == 1  # the chevron


@pytest.mark.parametrize("kind", list(EmailKind))
def test_dark_mode_is_plain_black_and_white_with_no_blue_or_navy(kind):
    dark = dark_block(html_for(kind, code=CODE, link=SIGN_IN))
    assert "background-color: #000000" in dark and "#ededed" in dark
    colours = set(re.findall(r"#[0-9a-fA-F]{6}", dark))
    for colour in colours:
        red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
        assert max(red, green, blue) - min(red, green, blue) == 0, colour  # pure grey


# ---- premium polish: spacing, mobile, footer, readability


def contrast(foreground: str, background: str) -> float:
    def luminance(colour: str) -> float:
        parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def style_of(html: str, text: str) -> str:
    return re.search(r'style="([^"]*)"[^>]*>' + re.escape(text) + r"<", html).group(1)


def mobile_block(html: str) -> str:
    return html[html.index("max-width: 600px") : html.index("prefers-color-scheme")]


def test_spacing_is_40px_on_desktop_and_24px_on_phones_in_one_column():
    html = html_for(EmailKind.VERIFY_CODE, code=CODE)
    assert 'class="pad" style="padding:40px;"' in html
    assert ".pad { padding: 24px !important; }" in mobile_block(html)
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html
    assert "float" not in html and "display:flex" not in html.replace(" ", "")


def test_the_heading_is_larger_and_bolder_and_body_lines_are_1_6():
    html = html_for(EmailKind.RESET_LINK, link=SIGN_IN, recipient_name="Ali")
    heading = style_of(html, Messages.EMAIL_RESET_HEADING.value)
    assert "font-size:28px" in heading and "font-weight:700" in heading
    intro = style_of(html, Messages.EMAIL_RESET_INTRO.value)
    assert "line-height:1.6" in intro and "font-size:16px" in intro


def test_the_code_is_40px_with_wide_spacing_and_its_validity_line_follows_it():
    html = html_for(EmailKind.VERIFY_CODE, code=CODE)
    box = re.search(r'class="code" style="([^"]*)"', html).group(1)
    assert "font-size:40px" in box and "letter-spacing:10px" in box and "padding:24px 12px" in box
    assert html.index(CODE) < html.index(Messages.EMAIL_VERIFY_VALID.value)
    assert html.index(Messages.EMAIL_VERIFY_VALID.value) < html.index(
        Messages.EMAIL_VERIFY_NOT_YOU.value
    )


@pytest.mark.parametrize("kind", [EmailKind.REGISTER_EXISTING, EmailKind.RESET_LINK])
def test_the_button_has_14px_padding_and_fills_the_width_on_phones(kind):
    html = html_for(kind, link=SIGN_IN)
    anchor = re.search(r'class="btn-text" href="[^"]*" style="([^"]*)"', html).group(1)
    assert "padding:14px 28px" in anchor and "color:#ffffff" in anchor
    assert ".btn-table { width: 100% !important; }" in mobile_block(html)
    assert ".btn-text { display: block !important;" in mobile_block(html)
    assert html.count(f'href="{SIGN_IN}"') == 2  # the plain link stays below the button


def test_the_footer_has_a_divider_the_automatic_line_and_the_brand_with_the_year():
    from datetime import UTC, datetime

    from common.infra.clock import FrozenClock

    renderer = EmailRenderer(FrozenClock(datetime(2031, 3, 4, tzinfo=UTC)))
    html = renderer.render_html(message(EmailKind.VERIFY_CODE, code=CODE))
    footer = html[html.index('class="divider"') :]
    assert "border-top:1px solid #ececec" in footer
    assert Messages.EMAIL_FOOTER_AUTOMATED.value in footer
    assert Messages.EMAIL_FOOTER_BRAND.render("Nudge", 2031) in footer
    assert "replies" in Messages.EMAIL_FOOTER_AUTOMATED.value.lower()


@pytest.mark.parametrize("kind", list(EmailKind))
def test_readability_body_text_is_at_least_15px_and_muted_text_has_4_5_contrast(kind):
    html = html_for(kind, code=CODE, link=SIGN_IN, recipient_name="Ali")
    intro, not_you = {
        EmailKind.VERIFY_CODE: (Messages.EMAIL_VERIFY_INTRO, Messages.EMAIL_VERIFY_NOT_YOU),
        EmailKind.REGISTER_EXISTING: (
            Messages.EMAIL_EXISTING_INTRO,
            Messages.EMAIL_EXISTING_NOT_YOU,
        ),
        EmailKind.RESET_LINK: (Messages.EMAIL_RESET_INTRO, Messages.EMAIL_RESET_NOT_YOU),
    }[kind]
    for sentence in (intro.value, not_you.value, Messages.EMAIL_GREETING.render("Ali")):
        size = int(re.search(r"font-size:(\d+)px", style_of(html, sentence)).group(1))
        assert size >= 15, sentence
    for style in re.findall(r'class="muted" style="([^"]*)"', html):
        colour = re.search(r"(?<![-\w])color:(#[0-9a-f]{6})", style).group(1)
        assert contrast(colour, "#ffffff") >= 4.5, style
    muted_dark = re.search(r"\.muted \{ color: (#[0-9a-f]{6})", dark_block(html)).group(1)
    assert contrast(muted_dark, "#000000") >= 4.5
    assert contrast("#171717", "#f2f2f2") >= 4.5 and contrast("#ededed", "#000000") >= 4.5


# ---- send_test_email --kind and the shared samples


@pytest.mark.parametrize("kind", list(EmailKind))
def test_sample_messages_look_like_the_real_ones_and_hold_no_real_data(kind):
    from common.management.email_samples import SAMPLE_NAME, sample_message

    sample = sample_message(kind, "me@example.com")
    assert sample.kind is kind and sample.to == "me@example.com"
    assert sample.recipient_name == SAMPLE_NAME and sample.text_body and sample.subject
    assert (sample.code or "") in sample.text_body and (sample.link or "") in sample.text_body
    assert sample.code or sample.link


@pytest.fixture
def dev_mode(monkeypatch, settings, db):
    """Make the command's guard see the dev settings (only the three values it reads). The real
    mail backend stays the in-memory one, which is asserted, so nothing can leave the machine."""
    from types import SimpleNamespace

    from django.db import connection

    from common.management.commands import send_test_email

    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    seen = SimpleNamespace(
        SETTINGS_MODULE="config.settings.dev",
        DEBUG=True,
        DEV_DATABASE_NAME=connection.settings_dict["NAME"],
        EMAIL_BACKEND=settings.EMAIL_BACKEND,
    )
    monkeypatch.setattr(send_test_email, "settings", seen)


@pytest.mark.parametrize("kind", list(EmailKind))
def test_send_test_email_kind_sends_the_designed_email_with_sample_data(dev_mode, kind):
    mail.outbox.clear()
    call_command("send_test_email", "me@example.com", "--kind", kind.value)
    (sent,) = mail.outbox
    assert sent.to == ["me@example.com"]
    assert sent.message().get_content_type() == "multipart/alternative"
    assert html_part(sent) and sent.body


def test_send_test_email_without_kind_stays_the_plain_test_message(dev_mode):
    mail.outbox.clear()
    call_command("send_test_email", "me@example.com")
    (sent,) = mail.outbox
    assert sent.subject == Messages.CLI_TEST_EMAIL_SUBJECT.value and sent.alternatives == []


def test_send_test_email_kind_is_still_dev_only_and_rejects_unknown_kinds():
    with pytest.raises(CommandError) as info:
        call_command("send_test_email", "me@example.com", "--kind", "verify_code")
    assert "config.settings.dev" in str(info.value) and mail.outbox == []
    with pytest.raises(CommandError):
        call_command("send_test_email", "me@example.com", "--kind", "nonsense")

"""The real flows (services, repositories, nudge_test) now send multipart/alternative mail. The text
part is exactly what it was before; the HTML part carries the same code or link. In-memory mail
backend only."""

import re

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.tests.fakes import VALID_REGISTRATION
from common.messages import Messages

pytestmark = pytest.mark.django_db

API = "/api/v1/auth/"
REGISTER, VERIFY, RESEND, RESET = (
    f"{API}{name}/" for name in ("register", "verify", "resend", "reset")
)
EMAIL = VALID_REGISTRATION["email"]
SIGN_UP = {**VALID_REGISTRATION, "type": VALID_REGISTRATION["account_type"]}
del SIGN_UP["account_type"]


def post(client: APIClient, url: str, data: object):
    return client.post(url, data, format="json")


def html_of(sent: mail.EmailMessage) -> str:
    (alternative,) = sent.alternatives
    assert alternative[1] == "text/html"
    return alternative[0]


def test_sign_up_sends_the_code_in_both_parts(client):
    assert post(client, REGISTER, SIGN_UP).status_code == 202
    sent = mail.outbox[-1]
    code = re.search(r"Your code is (\d{6})\.", sent.body).group(1)
    assert sent.body == Messages.EMAIL_VERIFY_CODE_BODY.render(code)
    assert sent.subject == Messages.EMAIL_VERIFY_CODE_SUBJECT.value
    html = html_of(sent)
    assert f">{code}<" in html
    assert Messages.EMAIL_GREETING.render(VALID_REGISTRATION["name"]) in html


def test_resend_sends_the_new_code_in_both_parts(client, clock):
    post(client, REGISTER, SIGN_UP)
    clock.advance(31)
    mail.outbox.clear()
    assert post(client, RESEND, {"email": EMAIL}).status_code == 202
    sent = mail.outbox[-1]
    code = re.search(r"Your code is (\d{6})\.", sent.body).group(1)
    assert f">{code}<" in html_of(sent)


def test_the_registration_notice_has_both_parts_and_the_sign_in_link(client, clock):
    post(client, REGISTER, SIGN_UP)
    code = re.search(r"Your code is (\d{6})\.", mail.outbox[-1].body).group(1)
    assert post(client, VERIFY, {"email": EMAIL, "code": code}).status_code == 200
    clock.advance(31)
    mail.outbox.clear()
    assert post(APIClient(), REGISTER, SIGN_UP).status_code == 202
    sent = mail.outbox[-1]
    link = re.search(r"at (\S+?)\. If it was not", sent.body).group(1)
    assert sent.subject == Messages.EMAIL_REGISTER_EXISTING_SUBJECT.value
    assert f'href="{link}"' in html_of(sent)


def test_the_reset_email_has_the_same_link_in_the_text_the_button_and_the_plain_line(client, clock):
    post(client, REGISTER, SIGN_UP)
    code = re.search(r"Your code is (\d{6})\.", mail.outbox[-1].body).group(1)
    post(client, VERIFY, {"email": EMAIL, "code": code})
    clock.advance(31)
    mail.outbox.clear()
    assert post(APIClient(), RESET, {"email": EMAIL}).status_code == 202
    sent = mail.outbox[-1]
    link = re.search(r"/new-password\?token=[\w-]+", sent.body).group(0)
    assert sent.body.count(link) == 1
    assert html_of(sent).count(link) == 3  # button href, plain-link href, plain-link text

"""ResetTokenService: signed, one hour, single use. No database."""

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.accounts.services.reset_token_service import ResetTokenService
from apps.accounts.tests.fakes import AccountsWorld
from common.constants import Ttl
from common.validators import is_reset_token_format

EMAIL = "ali@example.com"


@pytest.fixture
def world() -> AccountsWorld:
    w = AccountsWorld()
    w.verified_user()
    return w


@pytest.fixture
def tokens(world) -> ResetTokenService:
    return ResetTokenService(world.digests, world.clock)


def user(world, email: str = EMAIL):
    return world.users.get_by_email(email)


def test_a_token_matches_the_pattern_the_frontend_accepts(world, tokens):
    token = tokens.issue(user(world))
    assert is_reset_token_format(token) and 4 <= len(token) <= 200


def test_a_fresh_token_is_valid_for_its_user_and_names_them(world, tokens):
    token = tokens.issue(user(world))
    assert tokens.user_id_in(token) == user(world).id
    assert tokens.is_valid(token, user(world)) is True


def test_the_token_carries_no_email_and_no_password_hash(world, tokens):
    token = tokens.issue(user(world))
    assert EMAIL not in token and user(world).password_hash not in token


def test_it_works_for_one_hour_only(world, tokens):
    token = tokens.issue(user(world))
    world.clock.advance(Ttl.RESET_LINK - 1)
    assert tokens.is_valid(token, user(world)) is True
    world.clock.advance(1)
    assert tokens.is_valid(token, user(world)) is False


def test_a_new_password_kills_it(world, tokens):
    token = tokens.issue(user(world))
    world.users.set_password(user(world).id, "fake$another")
    assert tokens.is_valid(token, user(world)) is False


def test_a_sign_in_kills_it(world, tokens):
    token = tokens.issue(user(world))
    world.users.touch_last_login(user(world).id, world.clock.now() + timedelta(seconds=5))
    assert tokens.is_valid(token, user(world)) is False


def test_it_is_not_valid_for_another_user(world, tokens):
    world.verified_user(email="other@example.com", name="Sana Malik")
    token = tokens.issue(user(world))
    assert tokens.is_valid(token, user(world, "other@example.com")) is False


def test_a_changed_signature_expiry_or_user_is_refused(world, tokens):
    token = tokens.issue(user(world))
    user_part, expiry, mac = token.split("-")
    flipped = mac[:-1] + ("0" if mac[-1] != "0" else "1")
    longer = str(int(expiry) + 3600)
    other_user = "0" * 32
    for forged in (
        f"{user_part}-{expiry}-{flipped}",
        f"{user_part}-{longer}-{mac}",
        f"{other_user}-{expiry}-{mac}",
    ):
        assert tokens.is_valid(forged, user(world)) is False


@pytest.mark.parametrize(
    "garbage",
    ["", "x", "a-b-c", "-" * 10, "z" * 200, "é" * 20, "a b c d"],
)
def test_garbage_is_not_a_token(world, tokens, garbage):
    assert tokens.user_id_in(garbage) is None
    assert tokens.is_valid(garbage, user(world)) is False


def test_two_tokens_for_the_same_user_differ_only_when_time_differs(world, tokens):
    first = tokens.issue(user(world))
    assert tokens.issue(user(world)) == first
    world.clock.advance(1)
    assert tokens.issue(user(world)) != first


def test_a_token_stays_valid_after_a_rehash_free_profile_change(world, tokens):
    token = tokens.issue(user(world))
    world.users.rows[user(world).id] = replace(user(world), full_name="Renamed Person")
    assert tokens.is_valid(token, user(world)) is True

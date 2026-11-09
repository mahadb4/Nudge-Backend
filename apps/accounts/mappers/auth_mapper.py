"""Entities -> response DTOs. Pure functions. Never returns a password hash or an internal field."""

from apps.accounts.domain.entities import Me, MembershipWithOrganization, SignInResult
from apps.accounts.dtos.auth_dtos import (
    MeOrganization,
    MeOrganizationRef,
    MeResponse,
    SignInResponse,
)
from common.constants import ACCOUNT_TYPE_WIRE, ROLE_WIRE


def to_me_response(me: Me) -> MeResponse:
    organization = me.current.organization
    return MeResponse(
        id=str(me.user.id),
        name=me.user.full_name,
        email=me.user.email,
        type=ACCOUNT_TYPE_WIRE[organization.account_type],
        verified=me.user.email_verified_at is not None,
        phone=me.user.phone,
        timezone=me.user.timezone,
        organization=MeOrganization(
            id=str(organization.id),
            name=organization.name,
            type=ACCOUNT_TYPE_WIRE[organization.account_type],
            timezone=organization.timezone,
        ),
        role=ROLE_WIRE[me.current.membership.role],
        organizations=[_to_reference(item) for item in me.organizations],
    )


def _to_reference(item: MembershipWithOrganization) -> MeOrganizationRef:
    return MeOrganizationRef(
        id=str(item.organization.id),
        name=item.organization.name,
        role=ROLE_WIRE[item.membership.role],
    )


def to_sign_in_response(result: SignInResult) -> SignInResponse:
    return SignInResponse(access=result.tokens.access_token, user=to_me_response(result.me))

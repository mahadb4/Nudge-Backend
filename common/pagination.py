"""Offset lists (small, per-organization lists): page and page_size, q, one ordering from an
allowlist and a few typed filters. Anything else in the query string is a 400 that names the
parameter. The page size is capped (CODING_STYLE 7)."""

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Generic, TypeVar
from urllib.parse import urlencode

from common.constants import Limits
from common.errors import FieldIssue, InvalidValue, ValidationFailed
from common.messages import Messages
from common.text import clean, has_control_chars

T = TypeVar("T")

PARAM_PAGE = "page"
PARAM_PAGE_SIZE = "page_size"
PARAM_Q = "q"
PARAM_ORDERING = "ordering"
MAX_DIGITS = 9


@dataclass(frozen=True, slots=True)
class ListQuery:
    page: int
    page_size: int
    q: str | None
    ordering: str
    filters: Mapping[str, object] = field(default_factory=dict)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    results: list[T]
    count: int
    query: ListQuery

    @property
    def has_next(self) -> bool:
        return self.query.offset + len(self.results) < self.count

    @property
    def has_previous(self) -> bool:
        return self.query.page > 1


def _whole_number(raw: str, low: int, high: int | None, message: Messages, *values: object) -> int:
    if not (raw.isascii() and raw.isdigit() and len(raw) <= MAX_DIGITS):
        raise InvalidValue(message, *values)
    number = int(raw)
    if number < low or (high is not None and number > high):
        raise InvalidValue(message, *values)
    return number


def parse_list_query(
    params: Mapping[str, str],
    *,
    orderings: Collection[str],
    default_ordering: str,
    filters: Mapping[str, Callable[[object], object]] | None = None,
) -> ListQuery:
    """Read ?page, ?page_size, ?q, ?ordering and the declared filters.

    orderings is the allowlist of public names (for example "-created_at"). Every problem is
    reported together, by parameter name.
    """
    filters = filters or {}
    allowed = {PARAM_PAGE, PARAM_PAGE_SIZE, PARAM_Q, PARAM_ORDERING, *filters}
    issues: dict[str, list[FieldIssue]] = {}

    def fail(name: str, error: InvalidValue) -> None:
        issues.setdefault(name, []).append(error.issue)

    for name in params:
        if name not in allowed:
            # Only plain identifiers are echoed back, like unknown body fields.
            key = name if name.isidentifier() and len(name) <= 40 else "query"
            issues.setdefault(key, []).append(FieldIssue(Messages.VALIDATION_UNKNOWN_FIELD))

    page, page_size, q, ordering = 1, Limits.PAGE_SIZE_DEFAULT, None, default_ordering
    if PARAM_PAGE in params:
        try:
            page = _whole_number(params[PARAM_PAGE], 1, None, Messages.VALIDATION_PAGE_INVALID)
        except InvalidValue as error:
            fail(PARAM_PAGE, error)
    if PARAM_PAGE_SIZE in params:
        try:
            page_size = _whole_number(
                params[PARAM_PAGE_SIZE],
                1,
                Limits.PAGE_SIZE_MAX,
                Messages.VALIDATION_PAGE_SIZE_INVALID,
                Limits.PAGE_SIZE_MAX,
            )
        except InvalidValue as error:
            fail(PARAM_PAGE_SIZE, error)
    if params.get(PARAM_Q):
        try:
            q = _clean_query(params[PARAM_Q])
        except InvalidValue as error:
            fail(PARAM_Q, error)
    if PARAM_ORDERING in params:
        if params[PARAM_ORDERING] in orderings:
            ordering = params[PARAM_ORDERING]
        else:
            fail(PARAM_ORDERING, InvalidValue(Messages.VALIDATION_CHOICE_INVALID))
    parsed: dict[str, object] = {}
    for name, validate in filters.items():
        if name in params:
            try:
                parsed[name] = validate(params[name])
            except InvalidValue as error:
                fail(name, error)
    if issues:
        raise ValidationFailed.from_issues(issues)
    return ListQuery(page, page_size, q, ordering, parsed)


def _clean_query(raw: str) -> str | None:
    if has_control_chars(raw):
        raise InvalidValue(Messages.VALIDATION_CONTROL_CHARS)
    value = clean(raw)
    if not value:
        return None
    if len(value) < Limits.QUERY_MIN:
        raise InvalidValue(Messages.VALIDATION_TOO_SHORT, Limits.QUERY_MIN)
    if len(value) > Limits.QUERY_MAX:
        raise InvalidValue(Messages.VALIDATION_TOO_LONG, Limits.QUERY_MAX)
    return value


def page_link(base_url: str, params: Mapping[str, str], page: int) -> str:
    """The same query string with another page number."""
    return f"{base_url}?{urlencode({**params, PARAM_PAGE: page})}"

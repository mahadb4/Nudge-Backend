"""The seven stages every new organization starts with. Same rows as nudge_create_default_stages()
in the seed SQL."""

from apps.crm.domain.enums import StageOutcome

# (name, outcome); the position is the index. Won and Lost are fixed at the end (Q-5).
DEFAULT_STAGES: tuple[tuple[str, StageOutcome], ...] = (
    ("New", StageOutcome.OPEN),
    ("Contacted", StageOutcome.OPEN),
    ("Meeting scheduled", StageOutcome.OPEN),
    ("Proposal", StageOutcome.OPEN),
    ("Negotiation", StageOutcome.OPEN),
    ("Won", StageOutcome.WON),
    ("Lost", StageOutcome.LOST),
)

"""Base for response DTOs: small frozen dataclasses with a to_dict() helper (CODING_STYLE 4)."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ResponseDto:
    def to_dict(self) -> dict[str, object]:
        return asdict(self)

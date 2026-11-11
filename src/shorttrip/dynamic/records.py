"""Data contracts for the dynamic-update pipeline."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


REQUIRED_FIELDS = {
    "attraction": ("name", "city", "type", "lat", "lon", "opentime", "endtime", "price"),
    "restaurant": ("name", "city", "cuisine", "lat", "lon", "opentime", "endtime", "price"),
    "accommodation": ("name", "city", "lat", "lon", "price", "numbed"),
}


@dataclass
class DataRequest:
    """What the planner is missing, and why it believes a fetch would help."""

    city: str
    kind: str
    name: str
    fields: tuple[str, ...]
    reason: str
    trigger: str = "missing_key_data"
    source_query: str | None = None
    required_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "kind": self.kind,
            "name": self.name,
            "fields": list(self.fields),
            "reason": self.reason,
            "trigger": self.trigger,
            "source_query": self.source_query,
            "required_by": self.required_by,
        }


@dataclass
class Evidence:
    """One fetched page/API response, kept verbatim for audit."""

    source: str
    url: str
    retrieved_at: str
    title: str
    text: str
    structured: dict = field(default_factory=dict)
    authority: float = 0.5
    ok: bool = True
    error: str | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8", "replace")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
            "title": self.title,
            "digest": self.digest,
            "chars": len(self.text),
            "structured": self.structured,
            "authority": self.authority,
            "ok": self.ok,
            "error": self.error,
        }


@dataclass
class FieldValue:
    value: object
    quote: str = ""
    source: str = ""
    # quote_ok is filled by the gate: does the quote really occur in the evidence?
    quote_ok: bool | None = None


@dataclass
class CandidateRecord:
    request: DataRequest
    fields: dict[str, FieldValue]
    extractor: str
    evidence: list[Evidence] = field(default_factory=list)

    def plain(self) -> dict:
        return {key: value.value for key, value in self.fields.items()}


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    hard: bool = True

    def to_dict(self) -> dict:
        return {"gate": self.name, "passed": self.passed, "hard": self.hard, "detail": self.detail}


@dataclass
class QualityReport:
    decision: str  # accept | quarantine | reject
    gates: list[GateResult]
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    needs_user_confirm: bool = False

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 3),
            "needs_user_confirm": self.needs_user_confirm,
            "reasons": self.reasons,
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass
class UpdateResult:
    request: DataRequest
    candidate: CandidateRecord | None
    quality: QualityReport | None
    version: str | None
    patched_instances: int = 0
    conflicts: list = field(default_factory=list)
    route: dict | None = None

    @property
    def accepted(self) -> bool:
        return self.quality is not None and self.quality.decision == "accept"

    def to_dict(self) -> dict:
        return {
            "request": self.request.to_dict(),
            "decision": self.quality.decision if self.quality else "no_candidate",
            "confidence": round(self.quality.confidence, 3) if self.quality else 0.0,
            "version": self.version,
            "patched_instances": self.patched_instances,
            "conflicts": self.conflicts,
            "route": self.route,
            "record": self.candidate.plain() if self.candidate else None,
            "quotes": {
                key: value.quote for key, value in (self.candidate.fields.items() if self.candidate else [])
            },
            "quality": self.quality.to_dict() if self.quality else None,
            "evidence": [item.to_dict() for item in (self.candidate.evidence if self.candidate else [])],
        }

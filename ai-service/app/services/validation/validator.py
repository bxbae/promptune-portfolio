from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.services.validation.rule_validator import validate_rules
from app.services.validation.semantic_validator import validate_semantic


DEFAULT_SEMANTIC_THRESHOLD = 0.65

ENABLE_SEMANTIC_VALIDATION_TELEMETRY = (
    os.getenv(
        "ENABLE_SEMANTIC_VALIDATION_TELEMETRY",
        "false",
    ).strip().lower()
    == "true"
)


@dataclass
class FinalValidationResult:
    passed: bool
    rule_ok: bool
    semantic_ok: bool
    semantic_score: float
    facts_preserved: bool
    issues: list[str] = field(default_factory=list)


def validate_response(
    original: str,
    generated: str,
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
) -> FinalValidationResult:
    rule_result = validate_rules(
        original=original,
        generated=generated,
    )

    semantic_ok = True
    semantic_score = -1.0
    semantic_issues: list[str] = []

    if ENABLE_SEMANTIC_VALIDATION_TELEMETRY:
        semantic_result = validate_semantic(
            original=original,
            generated=generated,
            threshold=semantic_threshold,
        )

        semantic_ok = semantic_result.semantic_ok
        semantic_score = semantic_result.score
        semantic_issues = semantic_result.issues

    issues = [
        *rule_result.issues,
        *semantic_issues,
    ]

    return FinalValidationResult(
        passed=rule_result.passed,
        rule_ok=rule_result.passed,
        semantic_ok=semantic_ok,
        semantic_score=semantic_score,
        facts_preserved=rule_result.facts_preserved,
        issues=issues,
    )

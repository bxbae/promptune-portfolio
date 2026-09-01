from __future__ import annotations

import re
import unicodedata


_IDENTITY_CLAIM_RE = re.compile(
    r"(?:본명|실명)"
    r"\s*(?:은|는|:)?\s*"
    r"([가-힣]{2,4}?)"
    r"(?=이며|이고|이다|[)）\\s,.;]|$)"
)


def _normalize(value: str) -> str:
    return "".join(
        unicodedata.normalize(
            "NFC",
            str(value or ""),
        ).lower().split()
    )


def _build_evidence_text(
    documents: list[dict] | None,
    web_results: list[dict] | None,
) -> str:
    parts: list[str] = []

    for item in documents or []:
        parts.extend([
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            str(item.get("content") or ""),
        ])

    for item in web_results or []:
        parts.extend([
            str(item.get("title") or ""),
            str(item.get("content") or ""),
        ])

    return "\n".join(parts)


def validate_evidence_identity(
    generated: str,
    *,
    documents: list[dict] | None = None,
    web_results: list[dict] | None = None,
) -> list[str]:
    """
    생성 답변이 '본명/실명'을 단정했을 때 해당 값이 실제 retrieval
    evidence에 존재하는지 확인한다.

    evidence가 없는 일반 CHAT에는 적용하지 않는다.
    """
    evidence = _build_evidence_text(
        documents,
        web_results,
    )

    if not evidence.strip():
        return []

    normalized_evidence = _normalize(evidence)
    issues: list[str] = []

    for claim in _IDENTITY_CLAIM_RE.findall(
        str(generated or "")
    ):
        normalized_claim = _normalize(claim)

        if (
            normalized_claim
            and normalized_claim
            not in normalized_evidence
        ):
            issues.append(
                "근거 불일치: 답변이 본명/실명을 "
                f"'{claim}'(으)로 단정했지만 "
                "제공된 검색/문서 근거에서 확인되지 않습니다."
            )

    return issues

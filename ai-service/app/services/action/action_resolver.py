from __future__ import annotations

import re

from app.services.action.action_classifier import classify_action
from app.services.action.action_types import ActionPlan, ActionType


_ROUTE_BY_ACTION = {
    ActionType.CHAT: "no_retrieval",
    ActionType.MEMORY_WRITE: "no_retrieval",
    ActionType.MEMORY_READ: "no_retrieval",
    ActionType.USER_CONTEXT: "user_context",
    ActionType.TEXT_TRANSFORM: "no_retrieval",
    ActionType.INTERNAL_DOC: "internal_rag",
    ActionType.WEB_FACT: "external_or_realtime",
    ActionType.MIXED_RESEARCH: "external_or_realtime",
}

_SOURCES_BY_ACTION = {
    ActionType.CHAT: (),
    ActionType.MEMORY_WRITE: (),
    ActionType.MEMORY_READ: ("MEMORY",),
    ActionType.USER_CONTEXT: ("USER_CONTEXT",),
    ActionType.TEXT_TRANSFORM: (),
    ActionType.INTERNAL_DOC: ("INTERNAL",),
    ActionType.WEB_FACT: ("WEB",),
    ActionType.MIXED_RESEARCH: ("INTERNAL", "WEB"),
}

_RETRIEVAL_ACTIONS = {
    ActionType.USER_CONTEXT,
    ActionType.INTERNAL_DOC,
    ActionType.WEB_FACT,
    ActionType.MIXED_RESEARCH,
}

_MIN_ACTION_CONFIDENCE = 0.25


def _self_aliases(user_context: dict[str, str] | None) -> list[str]:
    if not user_context:
        return []

    aliases: list[str] = []

    for key in (
        "name",
        "displayName",
        "email",
        "microsoftEmail",
    ):
        value = str(user_context.get(key, "") or "").strip()

        if not value:
            continue

        # 한 글자 이름이나 지나치게 짧은 값은 일반 문장 오치환 위험이 있다.
        if len(value) < 2:
            continue

        if value not in aliases:
            aliases.append(value)

    return sorted(aliases, key=len, reverse=True)


def normalize_action_query(
    query: str,
    user_context: dict[str, str] | None = None,
) -> str:
    """
    Action classification에서만 현재 사용자 실명/메일을 1인칭 표현으로 정규화한다.

    예:
      현재 사용자 name=차승연
      "차승연 이력서 알려줘" -> "내 이력서 알려줘"
      "차승연의 경력 알려줘" -> "내 경력 알려줘"

    원래 query 자체는 변경하지 않는다.
    """
    text = str(query or "").strip()

    for alias in _self_aliases(user_context):
        escaped = re.escape(alias)

        # "차승연의 이력서" -> "내 이력서"
        text = re.sub(
            rf"{escaped}\s*의(?=\s|$)",
            "내",
            text,
            flags=re.IGNORECASE,
        )

        # "차승연 이력서" -> "내 이력서"
        text = re.sub(
            escaped,
            "내",
            text,
            flags=re.IGNORECASE,
        )

    return re.sub(r"\s+", " ", text).strip()


def resolve_action(
    query: str,
    user_context: dict[str, str] | None = None,
) -> ActionPlan:
    routing_query = normalize_action_query(
        query,
        user_context,
    )

    predicted, confidence = classify_action(routing_query)

    try:
        action = ActionType(predicted)
    except ValueError:
        return ActionPlan(
            action=ActionType.CHAT,
            confidence=0.0,
            retrieval_required=False,
            sources=(),
            retrieval_route="no_retrieval",
            reason="unknown_action_safe_fallback",
            routing_query=routing_query,
        )

    if confidence >= _MIN_ACTION_CONFIDENCE:
        return ActionPlan(
            action=action,
            confidence=confidence,
            retrieval_required=action in _RETRIEVAL_ACTIONS,
            sources=_SOURCES_BY_ACTION[action],
            retrieval_route=_ROUTE_BY_ACTION[action],
            reason=(
                "action_classifier:self_reference_normalized"
                if routing_query != str(query or "").strip()
                else "action_classifier"
            ),
            routing_query=routing_query,
        )

    return ActionPlan(
        action=action,
        confidence=confidence,
        retrieval_required=False,
        sources=(),
        retrieval_route="",
        reason="low_confidence_needs_strong_signal",
        routing_query=routing_query,
    )

from __future__ import annotations

from app.schemas.models import ConversationMessage


MAX_HISTORY_TOTAL_CHARS = 3000
MAX_HISTORY_MESSAGE_CHARS = 1200
MAX_RECALL_EVIDENCE_CHARS = 2400


def truncate_context_text(
    text: str,
    limit: int,
) -> str:
    value = str(text or "").strip()

    if limit <= 0:
        return ""

    if len(value) <= limit:
        return value

    if limit < 20:
        return value[:limit]

    marker = "\n...[중간 생략]...\n"
    available = limit - len(marker)

    head_length = int(
        available * 0.6
    )
    tail_length = (
        available - head_length
    )

    return (
        value[:head_length].rstrip()
        + marker
        + value[-tail_length:].lstrip()
    )


def budget_history(
    history: list[ConversationMessage],
    *,
    max_total_chars: int = MAX_HISTORY_TOTAL_CHARS,
    max_message_chars: int = MAX_HISTORY_MESSAGE_CHARS,
) -> list[ConversationMessage]:
    if (
        not history
        or max_total_chars <= 0
        or max_message_chars <= 0
    ):
        return []

    selected_reversed = []
    remaining = max_total_chars

    for message in reversed(history):
        content = str(
            message.content or ""
        ).strip()

        if not content:
            continue

        if remaining <= 0:
            break

        per_message_limit = min(
            max_message_chars,
            remaining,
        )

        content = truncate_context_text(
            content,
            per_message_limit,
        )

        if not content:
            continue

        selected_reversed.append(
            ConversationMessage(
                role=message.role,
                content=content,
            )
        )

        remaining -= len(content)

    return list(
        reversed(selected_reversed)
    )

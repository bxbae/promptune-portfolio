from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    CHAT = "CHAT"
    MEMORY_WRITE = "MEMORY_WRITE"
    MEMORY_READ = "MEMORY_READ"
    USER_CONTEXT = "USER_CONTEXT"
    TEXT_TRANSFORM = "TEXT_TRANSFORM"
    INTERNAL_DOC = "INTERNAL_DOC"
    WEB_FACT = "WEB_FACT"
    MIXED_RESEARCH = "MIXED_RESEARCH"


@dataclass(frozen=True)
class ActionPlan:
    action: ActionType
    confidence: float
    retrieval_required: bool
    sources: tuple[str, ...]
    retrieval_route: str
    reason: str
    routing_query: str

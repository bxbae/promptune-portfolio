"""추천문구에 원문에 없던 숫자가 추가되는지 검사하는 Rule 기반 안전검사."""

import re

from app.schemas.models import SafetyRequest, SafetyResponse


_NUM_RE = re.compile(r"\d+")


def safety_check(req: SafetyRequest) -> SafetyResponse:
    """추천문구가 원문에 없는 숫자를 새로 만들어내는지 검사한다."""
    orig_nums = set(_NUM_RE.findall(req.original))
    sugg_nums = set(_NUM_RE.findall(req.suggestion))

    invented = sugg_nums - orig_nums

    if invented:
        return SafetyResponse(
            safe=False,
            reason=f"원문에 없는 숫자 생성: {invented}",
        )

    return SafetyResponse(
        safe=True,
        reason="",
    )
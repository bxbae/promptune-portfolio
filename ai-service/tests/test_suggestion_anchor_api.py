from unittest.mock import patch

from app.schemas.models import SuggestRequest
from app.services.anchor_selector import AnchorSelection
from app.services import suggest_hcx


def test_suggest_response_contains_anchor():
    req = SuggestRequest(
        text="팀장님께 메일 써줘.",
        target_elements=["AUDIENCE"],
    )

    with (
        patch.object(
            suggest_hcx,
            "predict_missing_with_rules",
            return_value={"AUDIENCE": 1},
        ),
        patch.object(
            suggest_hcx,
            "_generate_candidates",
            return_value=[
                "수신자를 프로젝트 담당자로 설정해줘."
            ],
        ),
        patch.object(
            suggest_hcx,
            "_validate_generated_candidates",
            return_value=[
                "수신자를 프로젝트 담당자로 설정해줘."
            ],
        ),
        patch.object(
            suggest_hcx,
            "select_anchor",
            return_value=AnchorSelection(
                sentence_index=0,
                char_offset=len("팀장님께 메일 써줘."),
            ),
        ),
    ):
        response = suggest_hcx.suggest(req)

    assert len(response.suggestions) == 1

    suggestion = response.suggestions[0]

    assert suggestion.element == "AUDIENCE"
    assert suggestion.anchor.sentence_index == 0
    assert suggestion.anchor.char_offset == len(
        "팀장님께 메일 써줘."
    )


def test_suggest_schema_uses_snake_case_anchor_fields():
    req = SuggestRequest(
        text="팀장님께 메일 써줘.",
        target_elements=["AUDIENCE"],
    )

    with (
        patch.object(
            suggest_hcx,
            "predict_missing_with_rules",
            return_value={"AUDIENCE": 1},
        ),
        patch.object(
            suggest_hcx,
            "_generate_candidates",
            return_value=["수신자를 담당자로 설정해줘."],
        ),
        patch.object(
            suggest_hcx,
            "_validate_generated_candidates",
            return_value=["수신자를 담당자로 설정해줘."],
        ),
        patch.object(
            suggest_hcx,
            "select_anchor",
            return_value=AnchorSelection(
                sentence_index=0,
                char_offset=12,
            ),
        ),
    ):
        payload = suggest_hcx.suggest(req).model_dump()

    anchor = payload["suggestions"][0]["anchor"]

    assert anchor == {
        "sentence_index": 0,
        "char_offset": 12,
    }
from unittest.mock import patch

from app.services.anchor_selector import select_anchor


def test_single_sentence_anchor_is_end_of_sentence():
    text = "프로젝트 일정에 대해 메일 써줘."

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.9],
    ):
        anchor = select_anchor(text, "AUDIENCE")

    assert anchor.sentence_index == 0
    assert anchor.char_offset == len(text)


def test_audience_selects_semantically_related_sentence():
    text = (
        "프로젝트 일정이 지연됐어. "
        "책임자가 이해할 수 있는 메일을 작성해줘."
    )

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.31, 0.87],
    ):
        anchor = select_anchor(text, "AUDIENCE")

    assert anchor.sentence_index == 1
    assert anchor.char_offset == len(text)


def test_context_selects_semantically_related_sentence():
    text = (
        "팀장님께 메일 써줘. "
        "모델 검증 절차가 추가되어 일정이 늦어지고 있어."
    )

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.28, 0.91],
    ):
        anchor = select_anchor(text, "CONTEXT")

    expected = (
        text.index(
            "모델 검증 절차가 추가되어 일정이 늦어지고 있어."
        )
        + len(
            "모델 검증 절차가 추가되어 일정이 늦어지고 있어."
        )
    )

    assert anchor.sentence_index == 1
    assert anchor.char_offset == expected


def test_semantic_score_not_keyword_rule_decides_anchor():
    text = (
        "프로젝트 내용을 전달해야 해. "
        "결재권자가 바로 이해할 수 있도록 작성해줘."
    )

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.37, 0.83],
    ):
        anchor = select_anchor(text, "AUDIENCE")

    assert anchor.sentence_index == 1


def test_newline_keeps_original_character_offset():
    text = (
        "프로젝트 일정이 늦어졌어.\n"
        "책임자가 읽을 메일을 작성해줘."
    )

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.30, 0.88],
    ):
        anchor = select_anchor(text, "AUDIENCE")

    expected = (
        text.index("책임자가 읽을 메일을 작성해줘.")
        + len("책임자가 읽을 메일을 작성해줘.")
    )

    assert anchor.sentence_index == 1
    assert anchor.char_offset == expected


def test_equal_scores_prefer_later_sentence():
    text = "첫 번째 문장이야. 두 번째 문장이야."

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.5, 0.5],
    ):
        anchor = select_anchor(text, "CONTEXT")

    assert anchor.sentence_index == 1
    assert anchor.char_offset == len(text)


def test_bge_failure_falls_back_to_last_sentence():
    text = "첫 번째 문장이야. 두 번째 문장이야."

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        side_effect=RuntimeError("BGE unavailable"),
    ):
        anchor = select_anchor(text, "CONTEXT")

    assert anchor.sentence_index == 1
    assert anchor.char_offset == len(text)


def test_unknown_element_falls_back_to_last_sentence():
    text = "첫 번째 문장이야. 두 번째 문장이야."

    anchor = select_anchor(text, "UNKNOWN")

    assert anchor.sentence_index == 1
    assert anchor.char_offset == len(text)


def test_empty_text_returns_empty_anchor():
    anchor = select_anchor("", "AUDIENCE")

    assert anchor.sentence_index == -1
    assert anchor.char_offset == 0


def test_char_offset_can_be_used_for_exact_insertion():
    text = "팀장님께 메일 써줘. 일정이 지연됐어."

    with patch(
        "app.services.anchor_selector.calculate_similarities",
        return_value=[0.9, 0.2],
    ):
        anchor = select_anchor(text, "AUDIENCE")

    suggestion = " 수신자를 프로젝트 담당자로 설정해줘."

    result = (
        text[: anchor.char_offset]
        + suggestion
        + text[anchor.char_offset :]
    )

    assert result == (
        "팀장님께 메일 써줘."
        " 수신자를 프로젝트 담당자로 설정해줘."
        " 일정이 지연됐어."
    )
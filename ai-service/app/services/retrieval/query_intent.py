from __future__ import annotations

import re


_FIRST_PERSON_RE = re.compile(
    r"(?<![가-힣])(?:나|내|저|제)(?:는|가|를|의|\s)"
)

_WHO_RE = re.compile(
    r"^\s*(?P<subject>.+?)(?:은|는|이|가)?\s+"
    r"누구(?:야|예요|에요|인가요|인지|지)?\s*[?!.]*\s*$",
    re.IGNORECASE,
)

_WHAT_RE = re.compile(
    r"^\s*(?P<subject>.+?)(?:은|는|이|가)?\s+"
    r"(?:뭐|무엇)(?:야|예요|에요|인가요|인지|지)?\s*[?!.]*\s*$",
    re.IGNORECASE,
)

_KIND_RE = re.compile(
    r"^\s*(?P<subject>.+?)(?:은|는|이|가)?\s+"
    r"(?:뭐|무엇)\s*하는\s*"
    r"(?:사람|회사|기업|팀|그룹|서비스|제품|조직)"
    r"(?:이야|야|예요|에요|인가요)?\s*[?!.]*\s*$",
    re.IGNORECASE,
)


_PROFILE_LOOKUP_RE = re.compile(
    r"^\s*(?P<subject>.+?)(?:은|는|이|가|의)?\s+"
    r"(?:이력서|프로필|경력|약력|학력|소속)"
    r"(?:을|를|은|는|이|가|도)?\s*"
    r"(?:알려줘|알려주세요|알려|정리해줘|정리해|"
    r"보여줘|설명해줘|소개해줘|찾아줘)?"
    r"\s*[?!.]*\s*$",
    re.IGNORECASE,
)


_DEICTIC_SUBJECTS = {
    "그 사람",
    "그분",
    "그 회사",
    "그 팀",
    "그 그룹",
    "그 프로젝트",
    "그 문서",
    "그 파일",
    "이 문서",
    "이 파일",
}


def extract_external_entity_subject(query: str) -> str | None:
    text = re.sub(r"\s+", " ", str(query or "").strip())

    if not text:
        return None

    if _FIRST_PERSON_RE.search(text):
        return None

    for pattern in (
        _WHO_RE,
        _WHAT_RE,
        _KIND_RE,
        _PROFILE_LOOKUP_RE,
    ):
        match = pattern.match(text)

        if not match:
            continue

        subject = match.group("subject").strip(" ,.!?")

        if subject in _DEICTIC_SUBJECTS:
            return None

        if len(subject) < 2 or len(subject) > 80:
            return None

        return subject

    return None


def is_external_entity_lookup_query(query: str) -> bool:
    return extract_external_entity_subject(query) is not None

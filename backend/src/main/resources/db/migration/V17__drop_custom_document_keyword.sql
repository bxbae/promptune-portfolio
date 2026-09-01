-- 관리자 개념이 없어지면서(팀 결정: 개인이 직접 문서 업로드) 이 테이블의
-- 존재 이유(관리자가 등록하는 회사 키워드 사전)가 성립하지 않게 됨.
-- 내부문서 검색 핵심 규칙은 업무유형(_internal/application)만으로 이미 완전히 동작 중.
DROP TABLE custom_document_keyword;

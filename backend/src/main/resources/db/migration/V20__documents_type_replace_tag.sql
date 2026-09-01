-- tag(일반/업무) 폐지, document_type이 분류 역할 대체
-- 기존 문서들은 일단 OTHER로 이관 (나중에 사용자가 직접 재분류 가능)
ALTER TABLE documents ADD (
    description CLOB,
    document_type VARCHAR2(30) DEFAULT 'OTHER'
);

UPDATE documents SET document_type = 'OTHER' WHERE document_type IS NULL;

ALTER TABLE documents DROP COLUMN tag;

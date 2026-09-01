-- 원본은 PostgreSQL의 ADD/DROP COLUMN IF [NOT] EXISTS로 재실행 안전성을
-- 보장했지만, Flyway는 각 마이그레이션을 스키마 이력에 기록하고 정확히 한
-- 번만 실행하므로 이 가드가 필요 없다 — 애초에 Oracle의 ADD/DROP은 컬럼
-- 단위 IF [NOT] EXISTS를 지원하지 않아 그대로 옮길 수도 없다(Oracle 23ai의
-- IF [NOT] EXISTS는 테이블 등 객체 존재 여부만 검사하고, 개별 컬럼 존재
-- 여부는 검사하지 못한다).
ALTER TABLE documents ADD owner_user_id NUMBER(19) REFERENCES users(id);

ALTER TABLE documents DROP (company_id, content, embedding);

ALTER TABLE documents ADD (
    tag VARCHAR2(20) DEFAULT '일반',
    s3_key VARCHAR2(500),
    file_type VARCHAR2(20)
);

-- 회사명도 부서/직급과 같은 이유로 캐싱 (자주 안 바뀌는 정보)
ALTER TABLE microsoft_connections ADD company_name VARCHAR2(255);

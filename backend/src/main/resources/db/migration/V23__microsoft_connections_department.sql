-- 부서/직급은 자주 안 바뀌는 정보라 캐싱. display_name과 같은 패턴.
-- 일정(events)은 실시간성이 중요해서 캐싱하지 않고 매번 MS Graph 실시간 호출.
ALTER TABLE microsoft_connections ADD (
    department VARCHAR2(255),
    job_title VARCHAR2(255)
);

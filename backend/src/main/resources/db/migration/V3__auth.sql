-- 인증 관련 컬럼 추가 (로컬 로그인 + 향후 소셜 대비)

ALTER TABLE users ADD (
    password_hash VARCHAR2(255),           -- BCrypt 해시 (로컬 로그인용)
    name VARCHAR2(100),                    -- 표시 이름
    provider VARCHAR2(20) DEFAULT 'local', -- local / google / kakao / naver
    provider_id VARCHAR2(255)              -- 소셜 로그인 시 제공자의 사용자 ID
);

-- 소셜 로그인은 이메일이 없을 수도 있어 이메일 unique 제약을 완화하고
-- (provider, provider_id) 조합으로 고유성 보장.
-- Oracle은 WHERE절이 붙은 partial unique index를 지원하지 않으므로, provider_id가
-- NULL이면 두 식이 모두 NULL이 되도록 만드는 함수 기반 unique index로 같은 효과를
-- 낸다 — Oracle의 unique index는 키 컬럼이 전부 NULL인 행은 색인에서 제외하므로,
-- provider_id가 NULL인 행들끼리는 서로 충돌하지 않는다.
CREATE UNIQUE INDEX idx_provider_user ON users(
    CASE WHEN provider_id IS NOT NULL THEN provider END,
    CASE WHEN provider_id IS NOT NULL THEN provider_id END
);

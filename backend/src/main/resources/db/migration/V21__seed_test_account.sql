-- 팀 공용 로컬 테스트 계정. 매번 curl로 회원가입/로그인 안 해도 프론트에서 바로 로그인 가능.
-- 비밀번호: test1234 (아래는 BCrypt 해시값, 평문 아님)
-- 각자 로컬 DB에 이미 같은 이메일로 다른 계정을 만들어뒀어도 안전하게 무시됨
-- (ON CONFLICT → Oracle은 MERGE로 동일하게 구현)
MERGE INTO users tgt
USING (SELECT 1 dummy FROM dual) src
ON (tgt.email = 'test@promptune.dev')
WHEN NOT MATCHED THEN
    INSERT (email, password_hash, name, provider, created_at)
    VALUES ('test@promptune.dev', '$2b$10$M/Ip/o2KekDpOvhkQJkYEOYVJPrrotKv/zLaoTjZmzaMzXGNG4UQi', '테스트 계정', 'local', SYSTIMESTAMP);

-- V2 시드 데이터가 예전 한글 컨벤션으로 남아있던 것을 영어로 통일
UPDATE user_preferences
SET speed = 'accurate', detail = 'detailed', preserve = 'improve'
WHERE user_id = 1 AND speed = '정확하게';

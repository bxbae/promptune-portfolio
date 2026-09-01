-- AI 생성 응답 원문 저장 컬럼 (지금까지 저장 안 되고 있던 것)
ALTER TABLE prompt_sessions ADD ai_response_text CLOB;

-- 채팅 삭제 시 메시지도 같이 지워지도록 CASCADE로 변경.
-- V13에서 미리 이름을 fk_prompt_sessions_chat_session으로 고정해뒀으므로
-- (Postgres의 기본 생성 이름이던 prompt_sessions_chat_session_id_fkey 대신)
-- 그 이름으로 참조한다.
ALTER TABLE prompt_sessions DROP CONSTRAINT fk_prompt_sessions_chat_session;
ALTER TABLE prompt_sessions
    ADD CONSTRAINT fk_prompt_sessions_chat_session
    FOREIGN KEY (chat_session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE;

-- 활동 로그를 클릭했을 때 그 당시 대화 스레드로 이동하려면 어느 대화에서 나온 기록인지 알아야 함
ALTER TABLE behavior_logs ADD chat_session_id NUMBER(19) REFERENCES chat_sessions(id) ON DELETE SET NULL;
-- CASCADE가 아니라 SET NULL인 이유: 대화를 지워도 습관 학습 통계(대시보드 계산 근거)는 남아있어야 함

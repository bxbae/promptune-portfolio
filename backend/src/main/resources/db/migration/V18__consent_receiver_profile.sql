-- 수신자별로 개인화 저장 동의를 따로 받을 수 있도록 확장.
-- null이면 기존처럼 사용자 전체 단위 동의, 값이 있으면 그 수신자에 한정된 동의.
ALTER TABLE consent_records ADD receiver_profile_id NUMBER(19) REFERENCES receiver_profile(id) ON DELETE CASCADE;

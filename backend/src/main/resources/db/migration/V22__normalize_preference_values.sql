-- Phase 2-A: user_preferences 값 정규화.
--
-- UserPreference.speed/detail/preserve는 온보딩 화면(frontend/src/app/onboarding/page.tsx)이
-- 저장하는 영문 enum 문자열(fast/accurate, brief/detailed, keep/improve)이어야
-- Prompt Rule(Phase 2-B) 등에서 값을 비교할 수 있다. 그런데 실제 DB에는 이 규칙을
-- 벗어나는 값이 두 종류 존재해서 함께 정규화한다.
--
-- (순수 UPDATE/문자열 비교만 사용하므로 Oracle에서도 문법 변경 없이 그대로 동작한다.)

-- 1) 온보딩 화면의 기존 오타: preserve="imporve" (올바른 값은 "improve").
--    이 값으로 저장된 기존 행이 있다면 정정한다.
UPDATE user_preferences
SET preserve = 'improve'
WHERE preserve = 'imporve';

-- 2) V2__seed.sql이 심은 개발용 시드 데이터(user_id=1)가 온보딩 화면과 다른
--    한국어 값('정확하게'/'자세하게'/'적극보완')으로 들어가 있어, 실제 온보딩을
--    거치지 않고 시드로만 존재하는 행은 아래 값들과 절대 일치하지 않는다.
--    알려진 한국어 시드 값을 동일 의미의 영문 값으로 정규화한다.
UPDATE user_preferences SET speed = 'accurate' WHERE speed = '정확하게';
UPDATE user_preferences SET speed = 'fast' WHERE speed = '빠르게';

UPDATE user_preferences SET detail = 'detailed' WHERE detail = '자세하게';
UPDATE user_preferences SET detail = 'brief' WHERE detail = '간결하게';

UPDATE user_preferences SET preserve = 'improve' WHERE preserve = '적극보완';
UPDATE user_preferences SET preserve = 'keep' WHERE preserve = '원문유지';

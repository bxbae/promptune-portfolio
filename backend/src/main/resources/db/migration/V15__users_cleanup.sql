-- department/position: 실사용처 없는 죽은 컬럼 삭제
-- (getter 없음, 프론트 "부서" 표시는 MS Graph 실시간 응답값이라 무관함을 확인함)
ALTER TABLE users DROP (department, position);

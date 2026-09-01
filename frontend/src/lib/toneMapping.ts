// 직급 기반 존댓말 수위 추천 규칙 (1차 버전)
// 값은 receiver_profile.preferred_tone에 그대로 저장되고,
// ai-service generate_hcx.py의 labels 딕셔너리와 표현을 맞춤 (1단계 참고)

const SENIOR_TITLES = ["이사", "부장", "상무", "전무", "대표"];
const MID_TITLES = ["차장", "과장", "팀장"];
// 그 외(사원, 대리 등)는 편한 존댓말로 취급

export function suggestToneFromJobTitle(jobTitle: string | null | undefined): string | null {
  if (!jobTitle) return null;
  if (SENIOR_TITLES.some((t) => jobTitle.includes(t))) return "격식체";
  if (MID_TITLES.some((t) => jobTitle.includes(t))) return "정중체";
  return "편한존댓말";
}

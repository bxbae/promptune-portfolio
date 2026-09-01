// onboarding과 history/personalization이 이 세 문항을 공유함에 따라 상수 파일로 따로 작성.
// key/value/title/desc는 두 화면 모두 동일

export type QKey = "speed" | "detail" | "preserve";

export type PreferenceOption = {
  value: string;
  label: string;          // 온보딩용 (자세히)
  summaryLabel?: string;  // 개인화 설정 요약용 (간결히)
  desc: string;
};

export type PreferenceQuestion = {
  key: QKey;
  title: string;
  options: PreferenceOption[];
};

export const PREF_QUESTIONS: PreferenceQuestion[] = [
  {
    key: "speed",
    title: "1. 속도 vs 정확도",
    options: [
      { value: "fast", label: "빠르게", desc: "짧게 다듬고 바로 다음 작업으로" },
      { value: "accurate", label: "정확하게", desc: "시간이 걸려도 꼼꼼하게 검토" },
    ],
  },
  {
    key: "detail",
    title: "2. 설명 분량",
    options: [
      { value: "brief", label: "간결하게", desc: "핵심만 짧게, 바로 적용" },
      { value: "detailed", label: "자세하게", desc: "추천 근거까지 알고 싶어요" },
    ],
  },
  {
    key: "preserve",
    title: "3. 원문 존중도",
    options: [
      { value: "keep", label: "최대한 유지", desc: "빠진 조건만 채우고 말투는 그대로" },
      { value: "improve", label: "적극적으로 보완", summaryLabel: "적극적 보완", desc: "더 매끄러운 쪽으로 바꿔도 OK" },
    ],
  },
];

// dashboard/page.tsx에서 값 조회하는 용도
export const PREF_LABEL: Record<string, string> = Object.fromEntries(
  PREF_QUESTIONS.flatMap((q) => q.options.map((opt) => [opt.value, opt.label])),
);
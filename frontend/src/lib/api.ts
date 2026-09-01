// 백엔드 API 호출. 흐름도 2번(입력중단 감지·이전요청 취소)의 AbortController 포함.
import { getToken } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface DiagnoseResult {
  missing: Record<string, number>;
  taskType: string;
  typos: { span: string; suggest: string }[];
  needsInternalDocs: boolean;
}

export interface SuggestionAnchor {
  sentenceIndex: number;
  charOffset: number;
}

export interface SuggestionItem {
  element: string;
  primary: string;
  alternatives: string[];
  anchor: SuggestionAnchor;
}

export interface SuggestResult {
  suggestions: SuggestionItem[];
}

export interface AnalyzeResponse {
  gate: { passed: boolean; reason: string };
  diagnose: DiagnoseResult | null;
  recommend: { targetElements: string[] } | null;
  suggest: SuggestResult | null;
}

// 2번: 분석 요청 (이전 요청은 signal로 취소)
export async function analyze(
  text: string,
  signal: AbortSignal,
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!res.ok) throw new Error(`분석 실패: ${res.status}`);
  return res.json();
}

// "다듬기" 버튼 - HCX가 문장 전체를 재작성, 부족한 요소는 placeholder로 표시되어 반환됨
export interface PlaceholderSuggestion {
  element: string;
  placeholderText: string;
  primary: string;
  alternatives: string[];
}

export interface ImproveResponse {
  improvedPrompt: string;
  usedFallback: boolean;
  placeholders: PlaceholderSuggestion[];
}

export async function improve(text: string): Promise<ImproveResponse> {
  const res = await fetch(`${API}/api/improve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`다듬기 실패: ${res.status}`);
  return res.json();
}

// 11번: 실행
export async function execute(
  finalPrompt: string,
  chatSessionId?: number,
  documentIds?: number[],
  receiverProfileId?: number,
  signal?: AbortSignal,
) {
  const res = await fetch(`${API}/api/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      finalPrompt,
      chatSessionId,
      documentIds,
      receiverProfileId,
    }),
    signal,
  });
  if (!res.ok) throw new Error(`실행 실패: ${res.status}`);
  return res.json();
}

// 밑줄 제안에 대한 사용자 행동(적용/거절) 기록
// 실패해도 채팅 흐름을 막으면 안되므로 호출부에서 항상 .catch()로 감쌀 것.
export async function recordBehaviorAction(
  element: string,
  action: "applied" | "rejected",
  chatSessionId?: number,
): Promise<void> {
  const res = await fetch(`${API}/api/behavior-actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      element,
      action: action === "applied" ? "APPLY" : "REJECT",
      chatSessionId: chatSessionId ?? null,
    }),
  });
  if (!res.ok) throw new Error(`행동 기록 실패: ${res.status}`);
}

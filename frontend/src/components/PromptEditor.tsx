"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { analyze, execute, recordBehaviorAction, type AnalyzeResponse, improve, type ImproveResponse, type PlaceholderSuggestion } from "@/lib/api";
import { uploadDocument, listDocuments, type DocumentItem, type DocType } from "@/api/documents";
import type { ReceiverProfile } from "@/api/receiverProfiles";

interface ElementUiMeta {
  label: string;
  question: string;
}

const ELEMENT_UI: Record<string, ElementUiMeta> = {
  TASK: {
    label: "요청할 작업을 조금 더 명확히 하면 좋아요",
    question: "무엇을 해드리면 될까요?",
  },
  AUDIENCE: {
    label: "결과물을 볼 대상이 더 명확하면 좋아요",
    question: "누구를 위한 결과물인가요?",
  },
  CONTEXT: {
    label: "업무 배경이나 목적이 조금 더 필요해요",
    question: "어떤 상황이나 목적으로 사용하는 건가요?",
  },
  FORMAT: {
    label: "원하는 출력 형식을 지정하면 좋아요",
    question: "어떤 형식으로 작성할까요?",
  },
  TONE: {
    label: "말투나 문체를 지정하면 좋아요",
    question: "어떤 어조로 작성할까요?",
  },
  LENGTH: {
    label: "원하는 분량을 지정하면 좋아요",
    question: "어느 정도 길이로 작성할까요?",
  },
  CONSTRAINT: {
    label: "지켜야 할 조건을 추가하면 좋아요",
    question: "반드시 지켜야 할 조건이 있나요?",
  },
  EXAMPLE: {
    label: "참고할 예시가 있으면 결과가 더 정확해져요",
    question: "참고할 예시나 형태가 있나요?",
  },
};

// 사용자가 AI 추천 대신 직접 입력해서 보완한 요소 기록.
// 기존 onSubmit(text, directEdits) 계약을 유지한다.
export interface DirectEdit {
  element: string;
  generated: string;
  userFinal: string;
}

type TypoItem = {
  span: string;
  suggest: string;
};

type TypoRange = TypoItem & {
  start: number;
  end: number;
};

// diagnose 응답은 오탈자 문자열(span)만 주고 offset은 주지 않으므로
// 현재 textarea의 원문에서 실제 위치를 결정한다. 같은 문자열이 여러 번 등장해도
// 이미 사용한 범위와 겹치지 않는 다음 위치를 찾아 중복 밑줄을 방지한다.
function buildTypoRanges(fullText: string, typos: TypoItem[]): TypoRange[] {
  const ranges: TypoRange[] = [];

  for (const typo of typos) {
    const span = typo.span;
    if (!span) continue;

    let searchFrom = 0;

    while (searchFrom <= fullText.length - span.length) {
      const start = fullText.indexOf(span, searchFrom);
      if (start < 0) break;

      const end = start + span.length;
      const overlaps = ranges.some(
        (range) => start < range.end && end > range.start,
      );

      if (!overlaps) {
        ranges.push({ ...typo, start, end });
        break;
      }

      searchFrom = start + Math.max(span.length, 1);
    }
  }

  return ranges.sort((a, b) => a.start - b.start || a.end - b.end);
}

interface PromptEditorProps {
  onSubmit?: (
    displayText: string,
    directEdits: DirectEdit[],
    sentAttachments: DocumentItem[],
    // 실제로 AI에 보내는 텍스트(인용 블록·파일만 첨부 시 기본 지시문 포함).
    // 없으면 displayText를 그대로 전송용으로도 사용.
    sendText?: string,
  ) => void;
  compact?: boolean;
  disabled?: boolean;
  placeholder?: string;
  chatSessionId?: number;
  // 이전 메시지를 인용해서 다음 프롬프트에 맥락으로 참고시킬 때 사용.
  quotedMessage?: { role: "user" | "assistant"; content: string } | null;
  onClearQuote?: () => void;
  receiverProfiles?: ReceiverProfile[];
  onReceiverProfileChange?: (profile: ReceiverProfile | null) => void;
}

type AttachmentState = {
  key: string;
  name: string;
  status: "uploading" | "done" | "error";
  doc?: DocumentItem;
};

export default function PromptEditor({
  onSubmit,
  compact = false,
  disabled = false,
  placeholder,
  chatSessionId,
  quotedMessage,
  onClearQuote,
  receiverProfiles = [],
  onReceiverProfileChange,
}: PromptEditorProps = {}) {
  const [text, setText] = useState("");
  const [selectedReceiverId, setSelectedReceiverId] = useState<number | null>(
    null,
  );
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  const directEditsRef = useRef<DirectEdit[]>([]);

  const [optIdx, setOptIdx] = useState(0);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0);
  const [customOpen, setCustomOpen] = useState(false);
  const [customValue, setCustomValue] = useState("");

  const [gate, setGate] = useState<{
    passed: boolean;
    reason: string;
  } | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalyzeResponse | null>(
    null,
  );
  const [analyzing, setAnalyzing] = useState(false);
  // analyze API 자체가 실패(500/503/504/timeout/network error)했을 때만 채워짐.
  // suggestions=[]는 정상 응답이라 이거랑 무관 - 그 경우엔 이 state를 안 건드림.
  const [analyzeError, setAnalyzeError] = useState(false);

  const [result, setResult] = useState("");
  const [sending, setSending] = useState(false);

  // "다듬기" 모드 상태
  const [improveResult, setImproveResult] = useState<ImproveResponse | null>(null);
  const [improving, setImproving] = useState(false);
  const [textBeforeImprove, setTextBeforeImprove] = useState<string | null>(null);
  const [activePlaceholderIndex, setActivePlaceholderIndex] = useState<number | null>(null);
  const [placeholderOptIdx, setPlaceholderOptIdx] = useState(0);
  const [placeholderCustomOpen, setPlaceholderCustomOpen] = useState(false);
  const [placeholderCustomValue, setPlaceholderCustomValue] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const receiverCandidate =
    receiverProfiles
      .filter((profile) => profile.receiverName && text.includes(profile.receiverName))
      .sort(
        (a, b) =>
          new Date(b.updatedAt).getTime() -
          new Date(a.updatedAt).getTime(),
      )[0] ?? null;

  useEffect(() => {
    if (!text && selectedReceiverId !== null) {
      setSelectedReceiverId(null);
      onReceiverProfileChange?.(null);
    }
  }, [text, selectedReceiverId, onReceiverProfileChange]);
  const overlayRef = useRef<HTMLDivElement>(null);
  const inputWrapRef = useRef<HTMLDivElement>(null);
  const anchorMarkerRef = useRef<HTMLSpanElement>(null);
  // 방향키로 옵션을 넘길 때, 목록이 스크롤되어 있으면(카드 높이 초과) 선택된
  // 옵션이 화면 밖으로 나가있을 수 있다. 그 옵션을 담고 있는 스크롤 컨테이너(.ai-suggestion-card)
  // 자체에 ref를 걸어두고, optIdx/placeholderOptIdx가 바뀔 때마다 안의 .active 요소를
  // scrollIntoView로 따라오게 한다.
  const activeSuggestionCardRef = useRef<HTMLDivElement>(null);
  const activePlaceholderCardRef = useRef<HTMLDivElement>(null);

  const [anchorCardLeft, setAnchorCardLeft] = useState(0);
  const submittingRef = useRef(false);
  // 한글 (조합형 입력) 중 Enter로 오전송되는 것 방지 플래그.
  // macOS IME는 마지막 글자 확정 전에 keydown(Enter)이 먼저 발생할 수 있어서 조합이 끝났는지 여기서 직접 추적.
  const isComposingRef = useRef(false);

  const [attachments, setAttachments] = useState<AttachmentState[]>([]);

  // 파일을 선택한 즉시 전송 버튼을 누를 수 있게 하되, 실제 전송은
  // 업로드/인덱싱이 끝난 뒤 진행한다.
  // 기존 구현은 status=done일 때만 전송 버튼을 활성화해서 업로드가
  // 오래 걸리면 사용자가 텍스트를 입력해야만 보낼 수 있는 것처럼 보였다.
  const uploadTasksRef = useRef<Map<string, Promise<DocumentItem | null>>>(
    new Map(),
  );
  const uploadedDocsRef = useRef<Map<string, DocumentItem>>(new Map());

  // 파일 드래그앤드롭 (input-wrap 전체가 드롭존).
  // dragCounterRef: input-wrap 안 자식(textarea/overlay/popup 등) 경계를
  // 넘나들 때마다 발생하는 dragEnter/dragLeave로 isDragOver가 깜빡이는 것을 방지.
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounterRef = useRef(0);

  // "현재 처리할 요소"는 AI 추천(suggestions) 존재 여부가 아니라
  // 부족 요소 목록(targetElements) 기준으로 잡아야 한다.
  // suggestions=[]는 AI가 hallucination 방지 차 의도적으로 비웠을 수 있는 정상 응답이라,
  // 그 경우에도 질문/직접입력/건너뛰기는 그대로 보여줘야 함.
  const targetElements = analysisResult?.recommend?.targetElements ?? [];
  const unresolvedElements = targetElements.filter((element) => !resolved.has(element));
  const activeElement = unresolvedElements[activeSuggestionIndex] ?? unresolvedElements[0] ?? null;

  const activeSuggestion = activeElement
    ? (analysisResult?.suggest?.suggestions.find(
      (suggestion) => suggestion.element === activeElement,
    ) ?? null)
    : null;

  const activeAnchorOffset =
    activeSuggestion?.anchor != null
      ? Math.max(0, Math.min(activeSuggestion.anchor.charOffset, text.length))
      : null;

  const activeMeta = activeElement
    ? (ELEMENT_UI[activeElement] ?? {
      label: `${activeElement} 요소를 보완하면 좋아요`,
      question: "어떤 내용을 추가할까요?",
    })
    : null;

  const activeOptions = activeSuggestion
    ? [activeSuggestion.primary, ...activeSuggestion.alternatives].filter(
      (option, index, array) =>
        option.trim().length > 0 && array.indexOf(option) === index,
    )
    : [];

  const typoRanges = buildTypoRanges(
    text,
    analysisResult?.diagnose?.typos ?? [],
  );

  const syncAnchorCardLeft = useCallback(() => {
    const wrap = inputWrapRef.current;
    const marker = anchorMarkerRef.current;

    if (!wrap || !marker || activeAnchorOffset === null) {
      setAnchorCardLeft(0);
      return;
    }

    const wrapRect = wrap.getBoundingClientRect();
    const markerRect = marker.getBoundingClientRect();

    const cardWidth = Math.min(320, wrapRect.width);

    const rawLeft = markerRect.left - wrapRect.left;

    const maxLeft = Math.max(0, wrapRect.width - cardWidth);

    setAnchorCardLeft(Math.max(0, Math.min(rawLeft, maxLeft)));
  }, [activeAnchorOffset]);

  useLayoutEffect(() => {
    const frame = window.requestAnimationFrame(syncAnchorCardLeft);

    const handleResize = () => {
      syncAnchorCardLeft();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.cancelAnimationFrame(frame);

      window.removeEventListener("resize", handleResize);
    };
  }, [syncAnchorCardLeft, text, activeElement, compact]);

  // 다듬기 카드에서 텍스트에 등장하는 순서대로 정렬된 placeholder 목록
  const orderedPlaceholders: PlaceholderSuggestion[] = improveResult
    ? splitTextByPlaceholders(text, improveResult.placeholders)
      .filter(
        (seg): seg is { type: "placeholder"; content: string; data: PlaceholderSuggestion } =>
          seg.type === "placeholder"
      )
      .map((seg) => seg.data)
    : [];

  const scheduleAnalyze = useCallback((value: string) => {
    // 입력이 연속으로 바뀌면 이전 debounce 타이머를 취소해
    // 오래된 텍스트로 analyze 요청이 여러 번 발생하지 않게 한다.
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setAnalyzing(false);
    }

    setOptIdx(0);
    setActiveSuggestionIndex(0);
    setCustomOpen(false);
    setCustomValue("");
    // 새로 분석을 시작하니 직전 에러 배너는 일단 내림 (재시도 결과를 기다림)
    setAnalyzeError(false);

    if (!value.trim()) {
      setAnalyzing(false);
      setGate(null);
      setAnalysisResult(null);
      setResolved(new Set());
      return;
    }

    timerRef.current = setTimeout(async () => {
      timerRef.current = null;
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        setAnalyzing(true);
        const response = await analyze(value, ctrl.signal);

        if (abortRef.current !== ctrl) {
          return;
        }

        setGate(response.gate);
        setAnalysisResult(response);

        const diagnose = response.diagnose;

        if (diagnose) {
          const missingEntries = Object.entries(diagnose.missing);

          setResolved((prev) => {
            const updated = new Set(prev);

            for (const [element, missingValue] of missingEntries) {
              if (missingValue === 1) {
                // 최신 재진단에서 다시 부족하다고 판단되면
                // 이전 resolved 상태를 제거해서 추천 대상으로 복구한다.
                updated.delete(element);
              } else {
                // 최신 재진단에서 충족된 요소는 해결 상태로 유지한다.
                updated.add(element);
              }
            }

            return updated;
          });
        }
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        console.error("프롬프트 분석 실패:", error);

        // 500/503/504/timeout/network error 등 API 자체 실패.
        // 직전에 알고 있던 analysisResult/gate는 일부러 안 지운다 -
        // 그래야 사용자가 이미 보고 있던 질문에서 직접입력·건너뛰기를 계속할 수 있음.
        if (abortRef.current === ctrl) {
          setAnalyzeError(true);
        }
      } finally {
        if (abortRef.current === ctrl) {
          abortRef.current = null;
          setAnalyzing(false);
        }
      }
    }, 800);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, []);

  // 사용자가 드롭존(input-wrap) 밖에서 파일을 놓치면 브라우저가 그 파일을
  // 새 탭으로 열어버리므로, window 레벨에서도 기본 동작을 막아준다.
  useEffect(() => {
    const preventDefault = (e: DragEvent) => e.preventDefault();

    window.addEventListener("dragover", preventDefault);
    window.addEventListener("drop", preventDefault);

    return () => {
      window.removeEventListener("dragover", preventDefault);
      window.removeEventListener("drop", preventDefault);
    };
  }, []);

  // 방향키(↑↓)로 옵션을 넘길 때, 카드가 스크롤된 상태(옵션이 많아 maxHeight를 넘김)면
  // 방금 선택된 옵션이 화면 밖에 있을 수 있다. .active로 표시된 옵션을 카드 안에서
  // scrollIntoView로 따라오게 한다 (block:"nearest"라 이미 보이는 옵션이면 스크롤 안 함).
  useEffect(() => {
    const card = activeSuggestionCardRef.current;
    if (!card) return;
    const activeEl = card.querySelector(".active");
    activeEl?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [optIdx, customOpen]);

  useEffect(() => {
    const card = activePlaceholderCardRef.current;
    if (!card) return;
    const activeEl = card.querySelector(".active");
    activeEl?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [placeholderOptIdx, placeholderCustomOpen]);

  // 프롬프트가 길어질수록 textarea 높이를 내용에 맞게 늘려준다.
  // compact(대화 중 하단 컴포저)와 홈 화면 컴포저는 허용 높이를 다르게 둔다.
  // overlay는 mirror-div라 textarea와 정확히 같은 높이/스크롤 위치를 유지해야
  // 밑줄 위치가 어긋나지 않는다.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;

    const maxHeight = compact ? 160 : 320;

    el.style.height = "auto";
    const nextHeight = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${nextHeight}px`;

    if (overlayRef.current) {
      overlayRef.current.style.height = `${nextHeight}px`;
      overlayRef.current.scrollTop = el.scrollTop;
    }
  }, [text, compact]);

  // Diagnose가 반환한 오탈자 제안을 사용자가 밑줄을 클릭하는 즉시 적용한다.
  // LLM이 새 문구를 만드는 것이 아니라 span -> suggest의 결정적 치환이라
  // 원문에서 해당 span이 여전히 같은 위치에 있을 때만 수정한다.
  function applyTypoCorrection(typo: TypoRange) {
    const suggestion = typo.suggest.trim();

    if (!suggestion || suggestion === typo.span) {
      return;
    }

    // 분석 응답 이후 사용자가 텍스트를 바꿨다면 stale offset으로 수정하지 않는다.
    if (text.slice(typo.start, typo.end) !== typo.span) {
      return;
    }

    const nextText =
      text.slice(0, typo.start) + suggestion + text.slice(typo.end);
    const nextCaret = typo.start + suggestion.length;

    setText(nextText);
    scheduleAnalyze(nextText);

    // 클릭 때문에 textarea 포커스가 빠지지 않게 하고, 교정된 단어 뒤로 커서를 이동한다.
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      textarea.focus();
      textarea.setSelectionRange(nextCaret, nextCaret);
    });
  }

  function applySuggestion(value: string, isCustom = false) {
    if (!activeElement) {
      return;
    }

    const trimmedValue = value.trim();
    if (!trimmedValue) {
      return;
    }

    if (isCustom) {
      directEditsRef.current.push({
        element: activeElement,
        generated: activeOptions.join(" / "),
        userFinal: trimmedValue,
      });
    }

    recordBehaviorAction(activeElement, "applied", chatSessionId).catch(() => {
      // 행동 기록 실패는 채팅 흐름을 막지 않음 (조용히 무시)
    });

    const anchorOffset = activeSuggestion?.anchor?.charOffset;

    const nextText = anchorOffset !== undefined
      ? insertSuggestionAtAnchor(text, trimmedValue, anchorOffset)
      : mergePromptWithSuggestion(text, trimmedValue);

    setResolved((prev) => {
      const updated = new Set(prev);
      updated.add(activeElement);
      return updated;
    });

    setText(nextText);
    setOptIdx(0);
    setCustomOpen(false);
    setCustomValue("");

    scheduleAnalyze(nextText);
  }

  async function onImprove() {
    if (improving || !text.trim()) return;
    setImproving(true);
    setTextBeforeImprove(text); // "되돌리기"용 스냅샷 - 전체 단위 복원
    try {
      const result = await improve(text);
      setImproveResult(result);
      setText(result.improvedPrompt); // 화면엔 재작성된 문장을 보여줌
      setActivePlaceholderIndex(result.placeholders.length > 0 ? 0 : null);
      setPlaceholderOptIdx(0);
      textareaRef.current?.focus(); // 버튼 클릭으로 뺏긴 포커스를 다시 textarea로 - 방향키/tab이 먹히려면 필수
    } catch {
      alert("다듬기에 실패했습니다.");
      setTextBeforeImprove(null);
    } finally {
      setImproving(false);
    }
  }

  // "되돌리기" - 다듬기 누르기 전 원문으로 전체 복원 (부분 되돌리기 없음, 팀 결정)
  function onRevertImprove() {
    if (textBeforeImprove === null) return;
    const reverted = textBeforeImprove;
    setText(reverted);
    setImproveResult(null);
    setActivePlaceholderIndex(null);
    setTextBeforeImprove(null);
    scheduleAnalyze(reverted); // 원문 기준으로 실시간 시스템 다시 켜기
    textareaRef.current?.focus();
  }

  function applyPlaceholderSuggestion(placeholder: PlaceholderSuggestion, chosenText: string) {
    if (!improveResult) return;

    recordBehaviorAction(placeholder.element, "applied", chatSessionId).catch(() => {
      // 행동 기록 실패는 채팅 흐름을 막지 않음 (조용히 무시)
    });

    const newText = text.replace(placeholder.placeholderText, chosenText);
    setText(newText);

    const remaining = improveResult.placeholders.filter(
      (p) => p.placeholderText !== placeholder.placeholderText
    );

    if (remaining.length === 0) {
      // 다 채웠으면 다듬기 모드 종료, 실시간 시스템에 제어권 반환
      setImproveResult(null);
      setActivePlaceholderIndex(null);
      setTextBeforeImprove(null);
      scheduleAnalyze(newText);
    } else {
      setImproveResult({ ...improveResult, placeholders: remaining });
      setPlaceholderOptIdx(0);
      setActivePlaceholderIndex((prev) => {
        if (prev === null) return null;
        return Math.min(prev, remaining.length - 1);
      });
    }
  }

  function removePlaceholder(placeholder: PlaceholderSuggestion) {
    if (!improveResult) return;

    recordBehaviorAction(placeholder.element, "rejected", chatSessionId).catch(() => {
      // 행동 기록 실패는 채팅 흐름을 막지 않음 (조용히 무시)
    });

    // placeholder 문구와, 그 앞뒤에 붙은 쉼표/공백까지 같이 정리
    const newText = text
      .replace(`, ${placeholder.placeholderText}`, "")
      .replace(`${placeholder.placeholderText}, `, "")
      .replace(placeholder.placeholderText, "")
      .replace(/\s{2,}/g, " ")
      .trim();
    setText(newText);

    const remaining = improveResult.placeholders.filter(
      (p) => p.placeholderText !== placeholder.placeholderText
    );

    if (remaining.length === 0) {
      setImproveResult(null);
      setActivePlaceholderIndex(null);
      setTextBeforeImprove(null);
      scheduleAnalyze(newText);
    } else {
      setImproveResult({ ...improveResult, placeholders: remaining });
      setPlaceholderOptIdx(0);
      setActivePlaceholderIndex((prev) =>
        (prev === null ? null : Math.min(prev, remaining.length - 1))
      );
    }
  }

  // text를 placeholder 구간과 일반 구간으로 쪼갬 (오버레이 렌더링용)
  type TextSegment =
    | { type: "plain"; content: string }
    | { type: "placeholder"; content: string; data: PlaceholderSuggestion };

  function splitTextByPlaceholders(
    fullText: string,
    placeholders: PlaceholderSuggestion[]
  ): TextSegment[] {
    if (placeholders.length === 0) {
      return [{ type: "plain", content: fullText }];
    }

    // 각 placeholder가 실제로 text 안에서 몇 번째 글자에 있는지 찾기
    const matches: { start: number; end: number; data: PlaceholderSuggestion }[] = [];
    for (const p of placeholders) {
      const idx = fullText.indexOf(p.placeholderText);
      if (idx !== -1) {
        matches.push({ start: idx, end: idx + p.placeholderText.length, data: p });
      }
    }
    matches.sort((a, b) => a.start - b.start);

    const segments: TextSegment[] = [];
    let cursor = 0;
    for (const m of matches) {
      if (m.start > cursor) {
        segments.push({ type: "plain", content: fullText.slice(cursor, m.start) });
      }
      segments.push({ type: "placeholder", content: m.data.placeholderText, data: m.data });
      cursor = m.end;
    }
    if (cursor < fullText.length) {
      segments.push({ type: "plain", content: fullText.slice(cursor) });
    }

    return segments;
  }

  // 실시간 overlay에서 Promptune 오탈자 밑줄과 Suggest anchor marker를 동시에 렌더링한다.
  // 브라우저 기본 spellcheck 밑줄은 textarea에서 꺼두므로, 여기 보이는 물결 밑줄은
  // diagnose가 실제로 반환한 typo.span에만 생긴다.
  function renderLiveOverlay() {
    const nodes = [];
    let cursor = 0;
    let key = 0;
    let anchorInserted = false;
    const anchor = activeAnchorOffset;

    const pushText = (start: number, end: number, typo?: TypoRange) => {
      if (start >= end) return;

      const pushChunk = (chunkStart: number, chunkEnd: number) => {
        if (chunkStart >= chunkEnd) return;

        nodes.push(
          <span
            key={`overlay-text-${key++}`}
            className={typo ? "ov-underline-word" : undefined}
            data-typo-suggest={typo?.suggest}
            title={typo ? `${typo.suggest}로 수정` : undefined}
            style={
              typo ? { pointerEvents: "auto", cursor: "pointer" } : undefined
            }
            onMouseDown={
              typo
                ? (event) => {
                  event.preventDefault();
                  applyTypoCorrection(typo);
                }
                : undefined
            }
          >
            {text.slice(chunkStart, chunkEnd)}
          </span>,
        );
      };

      if (
        !anchorInserted &&
        anchor !== null &&
        anchor >= start &&
        anchor <= end
      ) {
        pushChunk(start, anchor);

        nodes.push(
          <span
            key={`overlay-anchor-${key++}`}
            ref={anchorMarkerRef}
            className="suggestion-anchor-marker"
          />,
        );
        anchorInserted = true;

        pushChunk(anchor, end);
        return;
      }

      pushChunk(start, end);
    };

    for (const typo of typoRanges) {
      if (typo.start > cursor) {
        pushText(cursor, typo.start);
      }

      pushText(typo.start, typo.end, typo);
      cursor = typo.end;
    }

    if (cursor < text.length) {
      pushText(cursor, text.length);
    }

    // 빈 텍스트이거나 특수한 경계값에서도 anchor ref가 유실되지 않게 안전장치.
    if (!anchorInserted && anchor !== null) {
      nodes.push(
        <span
          key={`overlay-anchor-${key++}`}
          ref={anchorMarkerRef}
          className="suggestion-anchor-marker"
        />,
      );
    }

    if (nodes.length === 0 && text) {
      nodes.push(<span key="overlay-plain">{text}</span>);
    }

    return nodes;
  }

  function skipActiveSuggestion() {
    if (!activeElement) {
      return;
    }

    recordBehaviorAction(activeElement, "rejected", chatSessionId).catch(() => {
      // 행동 기록 실패는 채팅 흐름을 막지 않음 (조용히 무시)
    });

    setResolved((prev) => {
      const updated = new Set(prev);
      updated.add(activeElement);
      return updated;
    });

    setOptIdx(0);
    setActiveSuggestionIndex(0);
    setCustomOpen(false);
    setCustomValue("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // 실시간 모드(다듬기 아님)에서 좌우 방향키로 카드 넘기기
    if (!improveResult && unresolvedElements.length > 0 && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      e.preventDefault();
      setOptIdx(0);
      setCustomOpen(false);
      setCustomValue("");
      setActiveSuggestionIndex((prev) => {
        const delta = e.key === "ArrowRight" ? 1 : -1;
        return (prev + delta + unresolvedElements.length) % unresolvedElements.length;
      });
      return;
    }

    // 다듬기 모드일 땐 이 블록이 전부 처리 - 아래 기존 실시간 카드 로직은 안 탐
    if (improveResult && orderedPlaceholders.length > 0) {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        setPlaceholderOptIdx(0);
        setActivePlaceholderIndex((prev) => {
          const current = prev ?? 0;
          const delta = e.key === "ArrowRight" ? 1 : -1;
          return (current + delta + orderedPlaceholders.length) % orderedPlaceholders.length;
        });
        return;
      }

      if (activePlaceholderIndex !== null && !placeholderCustomOpen) {
        const activePh = orderedPlaceholders[activePlaceholderIndex];
        const options = activePh ? [activePh.primary, ...activePh.alternatives] : [];

        if (e.key === "Enter" && !e.shiftKey) {
          // 한글 등 조합 중인 Enter는 "적용"으로 취급하지 않음 (조합 확정 Enter가 여기로 새면
          // 타이핑 중에 의도치 않게 제안이 적용돼버림 - 아래 전송용 Enter와 같은 이유)
          if (isComposingRef.current || e.nativeEvent.isComposing) {
            return;
          }
          e.preventDefault();
          if (!activePh) return;

          if (placeholderOptIdx === options.length) {
            // 직접입력 슬롯
            setPlaceholderCustomOpen(true);
            return;
          }

          if (placeholderOptIdx === options.length + 1) {
            // 건너뛰기 슬롯
            removePlaceholder(activePh);
            return;
          }

          const chosen = options[placeholderOptIdx];
          if (chosen) {
            applyPlaceholderSuggestion(activePh, chosen);
          }
          return;
        }

        if (e.key === "Escape") {
          e.preventDefault();
          if (activePh) {
            removePlaceholder(activePh);
          }
          return;
        }

        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          // 옵션(0~N-1) + 직접입력(N) + 건너뛰기(N+1) 를 순환
          const total = options.length + 2;
          const delta = e.key === "ArrowDown" ? 1 : -1;
          setPlaceholderOptIdx((index) => (index + delta + total) % total);
          return;
        }
      }
    }

    if (activeElement && !customOpen) {
      if (e.key === "Enter" && !e.shiftKey) {
        // 한글 등 조합 중인 Enter는 "적용"으로 취급하지 않음
        if (isComposingRef.current || e.nativeEvent.isComposing) {
          return;
        }
        e.preventDefault();

        if (optIdx === activeOptions.length) {
          // 직접입력 슬롯 - 입력창 열기 (실제 확정은 입력창 자체 onKeyDown의 Enter가 처리)
          setCustomOpen(true);
          return;
        }

        if (optIdx === activeOptions.length + 1) {
          // 건너뛰기 슬롯
          skipActiveSuggestion();
          return;
        }

        const option = activeOptions[optIdx];
        if (option) {
          applySuggestion(option);
        }
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        skipActiveSuggestion();
        return;
      }

      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        // 옵션(0~N-1) + 직접입력(N) + 건너뛰기(N+1) 를 순환
        const total = activeOptions.length + 2;
        const delta = e.key === "ArrowDown" ? 1 : -1;
        setOptIdx((index) => (index + delta + total) % total);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      // 한글 등 조합 중(예: 마지막 글자가 아직 확정 안 됨)인 Enter는 전송 트리거로 취급하지 않는다.
      // ref와 nativeEvent.isComposing을 둘 다 체크하는 이유:
      // 브라우저별로 "조합 확정 순간의 Enter"에 isComposing 값이 다르게 찍히는 경우가 있어서
      // 하나만 믿으면 여전히 새는 케이스가 생김.
      if (isComposingRef.current || e.nativeEvent.isComposing) {
        return;
      }

      e.preventDefault();
      void onExecute();
    }
  }

  function mergePromptWithSuggestion(text: string, suggestion: string): string {
    let base = text.trim();
    const addition = suggestion.trim();

    if (base && !/[.!?。！？]$/.test(base)) {
      base = `${base}.`;
    }

    return `${base} ${addition}`.trim();
  }

  function insertSuggestionAtAnchor(
    text: string,
    suggestion: string,
    charOffset: number,
  ): string {
    const addition = suggestion.trim();

    if (!addition) {
      return text;
    }

    const safeOffset = Math.max(0, Math.min(charOffset, text.length));

    const before = text.slice(0, safeOffset);
    const after = text.slice(safeOffset);

    const leadingSpace = before.length > 0 && !/\s$/.test(before) ? " " : "";

    const trailingSpace = after.length > 0 && !/^\s/.test(after) ? " " : "";

    return before + leadingSpace + addition + trailingSpace + after;
  }

  // 파일명에 특정 키워드가 있으면 카테고리를 추측한다. 완벽한 분류는 아니고,
  //"전부 기타로만 쌓이는" 문제를 줄이기 위한 간단한 휴리스틱.
  // 더 정교하게 하려면 추후 AI 기반 분류로 교체 가능.
  function guessDocumentType(filename: string): DocType {
    const name = filename.toLowerCase();

    if (/규정|정책|policy|규칙/.test(name)) return "규정";
    if (/양식|템플릿|template|서식/.test(name)) return "양식";
    if (/가이드|guide|매뉴얼|manual|안내/.test(name)) return "가이드";
    if (/보고서|report|리포트/.test(name)) return "보고서";

    return "기타";
  }

  async function handleFilesSelected(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) {
      return;
    }

    const files = Array.from(fileList);

    for (const file of files) {
      const key = `${file.name}-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 7)}`;

      setAttachments((prev) => [
        ...prev,
        { key, name: file.name, status: "uploading" },
      ]);

      // 업로드를 여기서 await하지 않는다. 여러 파일은 병렬로 올리고,
      // 사용자가 먼저 전송을 눌렀다면 onExecute()가 이 Promise를 기다린다.
      const task = uploadDocument(
        file,
        file.name,
        guessDocumentType(file.name),
        undefined,
      )
        .then(async (doc) => {
          // 업로드 자체(S3 저장 + DB row 생성)는 이미 성공한 상태.
          // 인덱싱(검색 가능하게 만드는 작업)이 아직 안 끝났으면 실패가 아니라
          // "처리 중"으로 보고, 최대 몇 차례 목록을 다시 조회하며 기다린다.
          // (단일 조회 API가 없어서 목록 조회로 대체)
          let current = doc;
          let attempts = 0;
          const maxAttempts = 5;

          while (
            current.indexStatus &&
            !["READY", "TEXT_READY", "FAILED"].includes(current.indexStatus) &&
            attempts < maxAttempts
          ) {
            await new Promise((resolve) => setTimeout(resolve, 1500));
            const list = await listDocuments();
            const found = list.find((d) => d.id === doc.id);
            if (found) current = found;
            attempts += 1;
          }

          if (current.indexStatus === "FAILED") {
            throw new Error(`파일 분석에 실패했습니다: ${current.indexError || file.name}`);
          }

          uploadedDocsRef.current.set(key, current);

          setAttachments((prev) =>
            prev.map((attachment) =>
              attachment.key === key
                ? { ...attachment, status: "done", doc: current }
                : attachment,
            ),
          );

          return current;
        })
        .catch((error) => {
          console.error("문서 업로드 실패:", error);

          setAttachments((prev) =>
            prev.map((attachment) =>
              attachment.key === key
                ? { ...attachment, status: "error" }
                : attachment,
            ),
          );

          return null;
        })
        .finally(() => {
          uploadTasksRef.current.delete(key);
        });

      uploadTasksRef.current.set(key, task);
    }

    // 같은 파일을 다시 선택해도 onChange가 다시 발생하도록 즉시 초기화한다.
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function removeAttachment(key: string) {
    uploadedDocsRef.current.delete(key);
    uploadTasksRef.current.delete(key);

    setAttachments((prev) =>
      prev.filter((attachment) => attachment.key !== key),
    );
  }

  function resetEditor() {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }

    setText("");
    setResolved(new Set());
    directEditsRef.current = [];
    setOptIdx(0);
    setCustomOpen(false);
    setCustomValue("");
    setGate(null);
    setAnalysisResult(null);
    setAnalyzing(false);
    setAttachments([]);
    uploadTasksRef.current.clear();
    uploadedDocsRef.current.clear();
  }

  async function onExecute() {
    const typedText = text.trim();
    const selectedAttachments = [...attachments];
    const hasSelectedAttachments = selectedAttachments.length > 0;
    const hasUploadCandidate = selectedAttachments.some(
      (attachment) => attachment.status !== "error",
    );

    // 파일을 막 선택해서 아직 uploading이어도 전송 요청 자체는 허용한다.
    // 실제 onSubmit은 아래에서 해당 업로드 Promise가 끝난 뒤 호출된다.
    if (
      (!typedText && !hasUploadCandidate) ||
      sending ||
      disabled ||
      submittingRef.current
    ) {
      return;
    }

    // 실패한 첨부를 조용히 빼고 텍스트만 보내면 사용자는 파일도 전달된
    // 것으로 오해한다. 실패 파일은 제거/재첨부하기 전까지 전송하지 않는다.
    if (selectedAttachments.some((attachment) => attachment.status === "error")) {
      window.alert(
        "첨부파일 업로드에 실패했습니다. 실패한 파일을 제거한 뒤 다시 첨부해주세요.",
      );
      return;
    }

    submittingRef.current = true;

    try {
      const selectedKeys = selectedAttachments.map((attachment) => attachment.key);
      const pendingUploads = selectedKeys
        .map((key) => uploadTasksRef.current.get(key))
        .filter(
          (task): task is Promise<DocumentItem | null> => Boolean(task),
        );

      if (pendingUploads.length > 0) {
        // 버튼을 누른 뒤에는 중복 전송을 막고, 현재 업로드/인덱싱이
        // 완료되는 즉시 같은 클릭으로 채팅 전송까지 이어간다.
        setSending(true);
        await Promise.all(pendingUploads);
      }

      const sentAttachments = selectedKeys
        .map((key) => uploadedDocsRef.current.get(key))
        .filter((doc): doc is DocumentItem => Boolean(doc));

      // 첨부를 선택했는데 하나라도 최종 업로드에 실패했다면 텍스트만
      // 전송하지 않는다. 파일이 빠진 채 질문되는 기존 문제를 막는다.
      if (
        hasSelectedAttachments &&
        sentAttachments.length !== selectedAttachments.length
      ) {
        window.alert(
          "첨부파일 준비가 완료되지 않았습니다. 잠시 후 다시 시도하거나 실패한 파일을 다시 첨부해주세요.",
        );
        return;
      }

      // 텍스트 없이 파일만 첨부한 경우에도 정상적인 문서 읽기 요청으로 보낸다.
      const baseText = typedText || "첨부된 파일의 내용을 읽고 핵심 내용을 알려주세요.";

      // 인용된 이전 메시지가 있으면 입력창 표시 텍스트는 그대로 두고
      // AI에 보내는 finalPrompt에만 인용 블록을 붙인다.
      const finalPrompt = quotedMessage
        ? `[인용된 이전 ${quotedMessage.role === "user" ? "내 메시지" : "AI 응답"}]\n${quotedMessage.content}\n\n[위 내용을 참고해서 답변]\n${baseText}`
        : baseText;

      if (onSubmit) {
        onSubmit(
          typedText,
          [...directEditsRef.current],
          sentAttachments,
          finalPrompt,
        );
        resetEditor();
        onClearQuote?.();
        return;
      }

      setSending(true);

      try {
        const response = await execute(finalPrompt);
        setResult(response?.result?.result ?? JSON.stringify(response));
        onClearQuote?.();
      } catch (error) {
        console.error("프롬프트 실행 실패:", error);
        setResult("요청 실행 중 오류가 발생했습니다.");
      }
    } finally {
      setSending(false);
      setTimeout(() => {
        submittingRef.current = false;
      }, 0);
    }
  }

  const gateBlocked = Boolean(gate && !gate.passed);
  const missing = analysisResult?.diagnose?.missing ?? {};
  const typoCount = analysisResult?.diagnose?.typos?.length ?? 0;

  return (
    <div className={`composer-wrap ${compact ? "compact" : ""}`}>
      {!compact && !improveResult && (
        <h1 className="composer-heading">오늘은 뭘 다듬어볼까요?</h1>
      )}

      <div className="composer-box">
        {receiverCandidate && (
          <div
            className={`receiver-candidate-card ${
              selectedReceiverId === receiverCandidate.id ? "selected" : "unselected"
            }`}
          >
            <div className="receiver-candidate-main">
              <div className="receiver-candidate-label">
                개인화 수신자 후보
              </div>

              <div className="receiver-candidate-name">
                👤 {receiverCandidate.receiverName}
              </div>

              <div className="receiver-candidate-meta">
                {receiverCandidate.relationship && (
                  <span>{receiverCandidate.relationship}</span>
                )}

                {receiverCandidate.preferredTone && (
                  <span>선호 톤 {receiverCandidate.preferredTone}</span>
                )}

                {receiverCandidate.updatedAt && (
                  <span>
                    최근 학습{" "}
                    {new Date(
                      receiverCandidate.updatedAt,
                    ).toLocaleDateString("ko-KR")}
                  </span>
                )}
              </div>
            </div>

            <button
              type="button"
              className="receiver-candidate-action"
              aria-pressed={selectedReceiverId === receiverCandidate.id}
              onClick={() => {
                const selecting = selectedReceiverId !== receiverCandidate.id;
                setSelectedReceiverId(selecting ? receiverCandidate.id : null);
                onReceiverProfileChange?.(selecting ? receiverCandidate : null);
                textareaRef.current?.focus();
              }}
            >
              {selectedReceiverId === receiverCandidate.id
                ? "적용됨 ✓"
                : "적용"}
            </button>
          </div>
        )}
        {quotedMessage && (
          <div className="quote-preview">
            <div className="quote-preview-body">
              <span className="quote-preview-label">
                {quotedMessage.role === "user" ? "내 메시지 인용" : "AI 응답 인용"}
              </span>
              <span className="quote-preview-text">{quotedMessage.content}</span>
            </div>
            <button
              type="button"
              className="quote-preview-close"
              onClick={() => onClearQuote?.()}
              aria-label="인용 취소"
            >
              ×
            </button>
          </div>
        )}
        <div
          ref={inputWrapRef}
          className={`input-wrap ${isDragOver ? "drag-over" : ""}`}
          onDragEnter={(e) => {
            e.preventDefault();
            if (disabled) return;
            dragCounterRef.current += 1;
            setIsDragOver(true);
          }}
          onDragOver={(e) => {
            // 필수: 이게 없으면 onDrop 자체가 브라우저에서 안 잡힘
            e.preventDefault();
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            dragCounterRef.current -= 1;
            if (dragCounterRef.current <= 0) {
              dragCounterRef.current = 0;
              setIsDragOver(false);
            }
          }}
          onDrop={(e) => {
            e.preventDefault();
            dragCounterRef.current = 0;
            setIsDragOver(false);
            if (disabled) return;
            void handleFilesSelected(e.dataTransfer.files);
          }}
        >
          <textarea
            ref={textareaRef}
            value={text}
            spellCheck={false}
            onChange={(e) => {
              const value = e.target.value;
              setText(value);

              if (selectedReceiverId !== null) {
                const selected = receiverProfiles.find(
                  (profile) => profile.id === selectedReceiverId,
                );

                if (!selected || !value.includes(selected.receiverName)) {
                  setSelectedReceiverId(null);
                  onReceiverProfileChange?.(null);
                }
              }

              scheduleAnalyze(value);
            }}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onBlur={(e) => {
              // 카드(질문)가 떠 있는데 버튼 아닌 영역 클릭 등으로 포커스가 빠지면
              // 방향키 탐색(onKeyDown)이 textarea 포커스가 있어야만 동작해서 그 순간 멈춰버림.
              // 실시간 카드(activeElement)·다듬기 카드(activePlaceholderIndex) 둘 다 커버.
              // activeSuggestion이 아니라 activeElement 기준 - 추천이 비어있어도(직접입력/건너뛰기만
              // 있는 카드) 동일하게 포커스를 지켜줘야 함.
              // 직접입력 칸(popup-custom-input)에 포커스를 넘기는 중이면 그건 그대로 둬야 하니 제외.
              const shouldKeepFocus =
                (activeElement && !customOpen) ||
                (activePlaceholderIndex !== null && !placeholderCustomOpen);

              if (shouldKeepFocus) {
                const target = e.currentTarget;
                setTimeout(() => {
                  if (!customOpen && !placeholderCustomOpen) target.focus();
                }, 0);
              }
            }}
            onKeyDown={onKeyDown}
            onScroll={(e) => {
              // 캡(maxHeight)에 도달해 내부 스크롤이 생기면
              // overlay(밑줄 레이어)도 같은 스크롤 위치를 따라가야 함
              if (overlayRef.current) {
                overlayRef.current.scrollTop = e.currentTarget.scrollTop;
              }
            }}
            placeholder={placeholder ?? "보내기 전에 먼저 다듬어드려요"}
            rows={1}
          />
          {/* textarea와 완전히 겹치는 오버레이(mirror-div 기법).
              font-size/line-height/padding이 textarea와 정확히 같아야 줄바꿈 위치가 어긋나지 않음(globals.css 참고).
              다듬기 모드에서는 placeholder 구간만 밑줄로 표시하고, 실시간 모드에서는
              diagnose가 반환한 실제 오탈자 span만 물결 밑줄로 표시한다. Suggest anchor가
              있으면 같은 overlay 안에서 정확한 charOffset 위치에 marker도 함께 표시한다.
              suggestions=[]처럼 anchor가 없을 때 전체 문장을 밑줄 긋지는 않는다. */}
          <div className="overlay" ref={overlayRef} aria-hidden="true">
            {improveResult && improveResult.placeholders.length > 0 ? (
              () => {
                let phIndex = -1;
                return splitTextByPlaceholders(text, improveResult.placeholders).map((seg, i) => {
                  if (seg.type !== "placeholder") {
                    return <span key={i}>{seg.content}</span>;
                  }
                  phIndex += 1;
                  const idx = phIndex;
                  const isDimmed = activePlaceholderIndex !== null && activePlaceholderIndex !== idx;
                  return (
                    <span
                      key={i}
                      className="ov-underline-word placeholder-underline"
                      style={{ pointerEvents: "auto", opacity: isDimmed ? 0.35 : 1, transition: "opacity 0.2s ease" }}
                      onMouseEnter={() => {
                        setActivePlaceholderIndex(idx);
                        setPlaceholderOptIdx(0);
                      }}
                    >
                      {seg.content}
                    </span>
                  );
                });
              })()
              : renderLiveOverlay()}
          </div>

          {/* 현재 보완 요소의 플로팅 카드.
              anchor가 있으면 해당 x 위치를 따라가고, anchor가 없는 직접입력/건너뛰기
              fallback 카드는 입력창 왼쪽을 기준으로 표시한다. */}
          {!improveResult && unresolvedElements.length > 0 && (
            <div
              style={{
                position: "absolute",
                bottom: "calc(100% + 10px)",
                left: activeAnchorOffset !== null ? `${anchorCardLeft}px` : 0,
                zIndex: 100,
                width: "min(320px, 100%)",
                transition: "left 0.18s ease",
              }}
            >
              {unresolvedElements.map((element, idx) => {
                const offset = idx - activeSuggestionIndex;
                const isActive = offset === 0;
                const suggestion = analysisResult?.suggest?.suggestions.find(
                    (s) => s.element === element,
                  ) ?? null;
                const meta = ELEMENT_UI[element] ?? {
                  label: `${element} 요소를 보완하면 좋아요`,
                  question: "어떤 내용을 추가할까요?",
                };
                const options = suggestion
                  ? [suggestion.primary, ...suggestion.alternatives].filter(
                    (option, index, array) =>
                      option.trim().length > 0 && array.indexOf(option) === index,
                  )
                  : [];

                return (
                  <div
                    key={element}
                    className="ai-suggestion-card"
                    ref={isActive ? activeSuggestionCardRef : undefined}
                    role="region"
                    aria-label={`${element} 요소 추천`}
                    style={{
                      position: isActive ? "relative" : "absolute",
                      bottom: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateX(${offset * 26}px) translateY(${Math.abs(offset) * -6}px) scale(${1 - Math.abs(offset) * 0.05})`,
                      filter: isActive ? "none" : "blur(2.5px)",
                      zIndex: 10 - Math.abs(offset),
                      pointerEvents: isActive ? "auto" : "none",
                      transition: "transform 0.2s ease, filter 0.2s ease",
                      maxHeight: "38vh",
                      overflowY: "auto",
                    }}
                  >
                    <div className="popup-label">
                      <span className="popup-dot" />
                      {meta.label}
                    </div>

                    <div className="popup-question">{meta.question}</div>

                    {options.map((option, index) => (
                      <button
                        key={`${element}-${option}`}
                        type="button"
                        className={`popup-option ${isActive && index === optIdx && !customOpen ? "active" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          applySuggestion(option);
                        }}
                        onMouseEnter={() => {
                          if (isActive) setOptIdx(index);
                        }}
                      >
                        {option}
                      </button>
                    ))}

                    {isActive && (!customOpen ? (
                      <button
                        type="button"
                        className={`popup-custom-btn input-style ${optIdx === activeOptions.length ? "active" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setCustomOpen(true);
                        }}
                        onMouseEnter={() => setOptIdx(activeOptions.length)}
                      >
                        Enter로 직접 입력
                      </button>
                    ) : (
                      <input
                        className="popup-custom-input"
                        autoFocus
                        value={customValue}
                        onChange={(e) => setCustomValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                            e.preventDefault();
                            setCustomOpen(false);
                            setCustomValue("");
                            const total = activeOptions.length + 2;
                            const delta = e.key === "ArrowDown" ? 1 : -1;
                            setOptIdx((index) => (index + delta + total) % total);
                            textareaRef.current?.focus();
                            return;
                          }

                          e.stopPropagation();

                          if (e.key === "Enter") {
                            e.preventDefault();
                            applySuggestion(customValue, true);
                          }

                          if (e.key === "Escape") {
                            e.preventDefault();
                            setCustomOpen(false);
                            setCustomValue("");
                          }
                        }}
                        placeholder="직접 입력 후 Enter"
                      />
                    ))}

                    {isActive && (
                      <button
                        type="button"
                        className={`popup-custom-btn ${optIdx === activeOptions.length + 1 ? "active" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          skipActiveSuggestion();
                        }}
                        onMouseEnter={() => setOptIdx(activeOptions.length + 1)}
                      >
                        이 요소는 건너뛰기
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {improveResult && activePlaceholderIndex !== null && orderedPlaceholders.length > 0 && (
            <div style={{ position: "absolute", bottom: "calc(100% + 10px)", left: 0, zIndex: 100, width: "min(320px, 100%)" }}>
              {orderedPlaceholders.map((ph, idx) => {
                const offset = idx - activePlaceholderIndex;
                const isActive = offset === 0;
                const options = [ph.primary, ...ph.alternatives];
                return (
                  <div
                    key={ph.placeholderText}
                    className="ai-suggestion-card"
                    ref={isActive ? activePlaceholderCardRef : undefined}
                    role="region"
                    aria-label={`${ph.element} 요소 추천`}
                    style={{
                      position: isActive ? "relative" : "absolute",
                      bottom: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateX(${offset * 26}px) translateY(${Math.abs(offset) * -6}px) scale(${1 - Math.abs(offset) * 0.05})`,
                      filter: isActive ? "none" : "blur(2.5px)",
                      zIndex: 10 - Math.abs(offset),
                      pointerEvents: isActive ? "auto" : "none",
                      transition: "transform 0.2s ease, filter 0.2s ease",
                      maxHeight: "38vh",
                      overflowY: "auto",
                    }}
                  >
                    <div className="popup-label">
                      <span className="popup-dot" />
                      {ELEMENT_UI[ph.element]?.label ?? `${ph.element} 요소를 보완하면 좋아요`}
                    </div>

                    <div className="popup-question">
                      {ELEMENT_UI[ph.element]?.question ?? "어떤 내용을 추가할까요?"}
                    </div>

                    {options.map((option, i2) => (
                      <button
                        key={`${ph.element}-${i2}`}
                        type="button"
                        className={`popup-option ${isActive && i2 === placeholderOptIdx ? "active" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          applyPlaceholderSuggestion(ph, option);
                        }}
                        onMouseEnter={() => {
                          if (isActive) setPlaceholderOptIdx(i2);
                        }}
                      >
                        {option}
                      </button>
                    ))}

                    {isActive && (!placeholderCustomOpen ? (
                      <button
                        type="button"
                        className={`popup-custom-btn input-style ${placeholderOptIdx === options.length ? "active" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setPlaceholderCustomOpen(true);
                        }}
                        onMouseEnter={() => setPlaceholderOptIdx(options.length)}
                      >
                        Enter로 직접 입력
                      </button>
                    ) : (
                      <input
                        className="popup-custom-input"
                        autoFocus
                        value={placeholderCustomValue}
                        onChange={(e) => setPlaceholderCustomValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                            e.preventDefault();
                            setPlaceholderCustomOpen(false);
                            setPlaceholderCustomValue("");
                            const total = options.length + 2;
                            const delta = e.key === "ArrowDown" ? 1 : -1;
                            setPlaceholderOptIdx((index) => (index + delta + total) % total);
                            textareaRef.current?.focus();
                            return;
                          }

                          e.stopPropagation();

                          if (e.key === "Enter") {
                            e.preventDefault();
                            const trimmed = placeholderCustomValue.trim();
                            if (trimmed) {
                              applyPlaceholderSuggestion(ph, trimmed);
                            }
                            setPlaceholderCustomOpen(false);
                            setPlaceholderCustomValue("");
                          }

                          if (e.key === "Escape") {
                            e.preventDefault();
                            setPlaceholderCustomOpen(false);
                            setPlaceholderCustomValue("");
                          }
                        }}
                        placeholder="직접 입력 후 Enter"
                      />
                    ))}

                    {isActive && (
                      <button
                        type="button"
                        className={`popup-custom-btn ${placeholderOptIdx === options.length + 1 ? "active" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          removePlaceholder(ph);
                        }}
                        onMouseEnter={() => setPlaceholderOptIdx(options.length + 1)}
                      >
                        이 요소는 건너뛰기
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {attachments.length > 0 && (
          <div className="attach-chip-row">
            {attachments.map((attachment) => (
              <div
                key={attachment.key}
                className={`attach-chip ${attachment.status}`}
              >
                <span className="attach-chip-name" title={attachment.name}>
                  {attachment.name}
                </span>

                {attachment.status === "uploading" && (
                  <span className="attach-chip-status">파일 준비 중…</span>
                )}

                {attachment.status === "error" && (
                  <span className="attach-chip-status">실패</span>
                )}

                <button
                  type="button"
                  className="attach-chip-remove"
                  onClick={() => removeAttachment(attachment.key)}
                  aria-label="첨부 제거"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="composer-actions">
          <div className="composer-icons">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt,.md,.xlsx,.pptx"
              multiple
              hidden
              onChange={(e) => {
                void handleFilesSelected(e.target.files);
              }}
            />

            <button
              className="icon-btn"
              type="button"
              title="파일 첨부"
              onClick={() => fileInputRef.current?.click()}
            >
              <img src="/icons/plus-muted.png" alt="" />
            </button>

            <button
              type="button"
              title="프롬프트 다듬기"
              disabled={improving || !text.trim()}
              onClick={() => void onImprove()}
              className="trim-btn"
            >
              {improving ? "다듬는 중…" : "다듬기"}
            </button>

            {improveResult && (
              <button
                type="button"
                title="다듬기 이전으로 되돌리기"
                onClick={onRevertImprove}
                className="trim-btn"
              >
                되돌리기
              </button>
            )}
          </div>

          <div className="composer-right">
            <span className="char-analyzing">{analyzing && "분석 중…"}</span>

            <button
              className="send-btn"
              disabled={
                (!text.trim() &&
                  !attachments.some((a) => a.status !== "error")) ||
                sending ||
                disabled
              }
              onClick={() => {
                void onExecute();
              }}
              title="Enter로도 실행됩니다"
            >
              ↑
            </button>
          </div>
        </div>
      </div>

      {!compact && (
        <div className="hint">
          <b>PrompTune</b>이 프롬프트의 모호함을 진단하고, 보완이 필요한 요소 중 우선순위가 높은 항목에 대해 추천 문구를 제안해요.
        </div>
      )}

      {analysisResult?.diagnose && !gateBlocked && (
        <div className="prompt-analysis-summary">
          <span>
            보완 필요:{" "}
            {Object.values(missing).filter((value) => value === 1).length}개
          </span>

          {targetElements.length > 0 && (
            <span> · 우선 추천: {targetElements.join(", ")}</span>
          )}

          {typoCount > 0 && <span> · 오탈자 후보: {typoCount}개</span>}
        </div>
      )}

      {gateBlocked && <div className="gate-block">⚠ {gate?.reason}</div>}

      {analyzeError && (
        <div className="gate-block">
          ⚠ AI 추천을 불러오지 못했습니다. 직접 입력하거나 이 요소를 건너뛸 수 있습니다.
        </div>
      )}

      {result && (
        <div className="result">
          <label className="eyebrow">생성 결과</label>
          <pre>{result}</pre>
        </div>
      )}
    </div>
  );
}

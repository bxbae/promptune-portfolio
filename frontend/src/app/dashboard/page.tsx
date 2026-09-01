"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getElementCoverage,
  getApplyRate,
  getWeeklyActivity,
  getToneApplyRate,
  getSatisfactionRate,
  getTaskTypeDistribution,
  ElementCoverage,
  ApplyRate,
  WeeklyActivity,
  ToneApplyRate,
  SatisfactionRate,
  TaskTypeDistribution,
} from "@/api/dashboard";
import { listReceiverProfiles, ReceiverProfile } from "@/api/receiverProfiles";
import { getPreference, UserPreference } from "@/api/userPreferences";
import { listActivityLogs } from "@/api/activityLogs";
import { PREF_LABEL } from "@/lib/preferenceQuestions";

// 최근 7일 배열, 오래된 순
function last7Days(): string[] {
  const days: string[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

const WEEKDAY_KO = ["일", "월", "화", "수", "목", "금", "토"];

function weekdayLabel(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return WEEKDAY_KO[d.getDay()];
}

// 업무유형 라벨별 색상 팔레트 (실데이터 키 개수가 가변이라 순서대로 배정)
const TASK_TYPE_COLORS = ["#55806A", "#7FA391", "#B7AFB2", "#dd5e3e", "#F2A99A", "#D8D3D0", "#EFEBE9", "#A9C4B8"];

const KNOWN_TASK_TYPES = ["email", "report", "notice", "application", "support", "report_internal", "notice_internal"];

// AI 진단이 사용하는 고정 8요소. 데이터가 없어도 0%로 8개 다 표시하기 위한 고정 목록.
const KNOWN_ELEMENTS = ["Task", "Context", "Format", "Audience", "Constraint", "Length", "Tone", "Example"];

// 대시보드 페이지
export default function DashboardPage() {
  const [coverage, setCoverage] = useState<ElementCoverage[]>([]);
  const [applyRate, setApplyRate] = useState<ApplyRate | null>(null);
  const [weekly, setWeekly] = useState<WeeklyActivity>({});
  const [receivers, setReceivers] = useState<ReceiverProfile[]>([]);
  const [preference, setPreference] = useState<UserPreference | null>(null);
  const [toneApplyRate, setToneApplyRate] = useState<ToneApplyRate | null>(null);
  const [satisfactionRate, setSatisfactionRate] = useState<SatisfactionRate | null>(null);
  const [taskTypeDist, setTaskTypeDist] = useState<TaskTypeDistribution>({});
  const [weeklyEditCount, setWeeklyEditCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      getElementCoverage(),
      getApplyRate(),
      getWeeklyActivity(),
      listReceiverProfiles(),
      getPreference(),
      getToneApplyRate(),
      getSatisfactionRate(),
      getTaskTypeDistribution(),
      listActivityLogs(),
    ])
      .then(([c, a, w, r, p, tone, sat, taskDist, logs]) => {
        setCoverage(c);
        setApplyRate(a);
        setWeekly(w);
        setReceivers(r);
        setPreference(p);
        setToneApplyRate(tone);
        setSatisfactionRate(sat);
        setTaskTypeDist(taskDist);

        // 최근 일주일(오늘 포함 7일) 안에 일어난 프롬프트 수정 카운트 (거절은 제외)
        const weekAgo = new Date();
        weekAgo.setDate(weekAgo.getDate() - 6);
        weekAgo.setHours(0, 0, 0, 0);
        const count = logs.filter(
          (e) => e.type !== "rejected" && new Date(e.occurredAt) >= weekAgo
        ).length;
        setWeeklyEditCount(count);
      })
      .catch((e) => setError(e.message || "대시보드 데이터를 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={{ padding: "20px 0", color: "var(--muted)" }}>불러오는 중...</div>;
  if (error) return <div style={{ padding: "20px 0", color: "var(--block)" }}>{error}</div>;

  const days = last7Days();
  const weeklyValues = days.map((d) => weekly[d] ?? 0);
  const weeklyMax = Math.max(1, ...weeklyValues);
  // 0 나눗셈 방지용 weeklyMax(최소 1)와 별개로, "진짜 최고 건수"를 따로 계산 (그래야 전부 0건일 때 강조 안 함)
  const weeklyRealMax = Math.max(0, ...weeklyValues);
  const weeklyTotal = weeklyValues.reduce((a, b) => a + b, 0);

  const topReceivers = [...receivers]
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
    .slice(0, 3);

  // element-coverage 배열에서 특정 요소만 찾기 (없으면 0%로 표시)
  function findCoverage(element: string) {
    return coverage.find((c) => c.element === element)?.coverageRate ?? 0;
  }

  // 0건인 요소도 항상 보이도록 KNOWN_ELEMENTS 기준으로 채움 (업무유형 분포와 같은 방식)
  const coverageItems = KNOWN_ELEMENTS.map((element) => ({
    element,
    coverageRate: findCoverage(element),
  }));

  // 요소 포함률이 가장 낮은(=가장 많이 놓친) 요소 하나
  const mostMissedElement = [...coverageItems].sort((a, b) => a.coverageRate - b.coverageRate)[0];

  // 0건인 카테고리도 항상 보이도록 KNOWN_TASK_TYPES 기준으로 채움
  const taskTypeTotal = Object.values(taskTypeDist).reduce((sum, count) => sum + count, 0);
  const taskTypeItems = KNOWN_TASK_TYPES
    .map((label, i) => ({
      label,
      count: taskTypeDist[label] ?? 0,
      pct: taskTypeTotal === 0 ? 0 : Math.round(((taskTypeDist[label] ?? 0) / taskTypeTotal) * 100),
      color: TASK_TYPE_COLORS[i % TASK_TYPE_COLORS.length],
    }))
    .sort((a, b) => b.count - a.count);

  return (
    <div>
      <h1>대시보드</h1>
      {/* 현재 개인화 설정 */}
      <div className="dash-pref-bar">
        <span className="dash-pref-label">현재 개인화 설정</span>
        {preference ? (
          <>
            <span className="dash-pref-pill">{PREF_LABEL[preference.speed] ?? preference.speed}</span>
            <span className="dash-pref-pill">{PREF_LABEL[preference.detail] ?? preference.detail}</span>
            <span className="dash-pref-pill">{PREF_LABEL[preference.preserve] ?? preference.preserve}</span>
          </>
        ) : (
          <span className="dash-pref-pill">설정 안 함</span>
        )}
        <Link href="/history/personalization" className="dash-more-link" style={{ marginLeft: "auto" }}>
          히스토리 &gt; 개인화 설정에서 수정 →
        </Link>
      </div>

      {/* 상단 KPI 4개: 전부 실데이터 */}
      <div className="dash-kpi-row">
        <div className="dash-kpi-card">
          <div className="dash-kpi-label">최근 일주일 수정횟수</div>
          <div className="dash-kpi-value">{weeklyEditCount} <span className="dash-kpi-unit">회</span></div>
        </div>
        <div className="dash-kpi-card">
          <div className="dash-kpi-label">가장 많이 누락된 요소</div>
          <div className="dash-kpi-value dash-kpi-value-text">
            {mostMissedElement.element}
              <span className="dash-kpi-unit dash-kpi-unit-small"> ({Math.round(mostMissedElement.coverageRate * 100)}%)</span>
          </div>
        </div>
        <div className="dash-kpi-card">
          <div className="dash-kpi-label">말투 적용률</div>
          <div className="dash-kpi-value">
            {toneApplyRate ? Math.round(toneApplyRate.coverageRate * 100) : 0} <span className="dash-kpi-unit">%</span>
          </div>
        </div>
        <div className="dash-kpi-card">
          <div className="dash-kpi-label">결과 만족도</div>
          <div className="dash-kpi-value">
            {satisfactionRate ? Math.round(satisfactionRate.satisfactionRate * 100) : 0} <span className="dash-kpi-unit">%</span>
          </div>
        </div>
      </div>

      {/* 1행: 요소 포함률(2fr) | 업무유형 분포(4fr) */}
      <div className="dash-grid-featured">
        {/* 요소 포함률 */}
        <div className="dash-panel">
          <div className="dash-section-title">요소 포함률</div>
            <div className="dash-coverage-list">
            {coverageItems.map((c) => {
                const pct = Math.round(c.coverageRate * 100);
                const good = c.coverageRate >= 0.5;
                return (
                  <div className="dash-coverage-row" key={c.element}>
                    <span className="dash-coverage-label">{c.element}</span>
                    <div className="dash-coverage-bar-track">
                      <div className={`dash-coverage-bar-fill ${good ? "good" : "bad"}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className={`dash-coverage-pct ${good ? "good" : "bad"}`}>{pct}%</span>
                  </div>
                );
              })}
            </div>
        </div>

        {/* 업무유형 분포 */}
        <div className="dash-panel">
          <div className="dash-section-title">업무유형 분포</div>
          {taskTypeTotal === 0 ? (
            <div className="dash-empty">아직 쌓인 데이터가 없어요.</div>
          ) : (
            <>
              <div className="dash-tasktype-stackbar">
                {taskTypeItems.map((t) => (
                  <div
                    key={t.label}
                    className="dash-tasktype-stackbar-seg"
                    title={`${t.label} ${t.pct}%`}
                    style={{ flexGrow: t.count, flexBasis: 0, background: t.color }}
                  />
                ))}
              </div>

              <div className="dash-tasktype-grid">
                {taskTypeItems.map((t) => (
                  <div className="dash-tasktype-item" key={t.label}>
                    <span className="dash-tasktype-dot" style={{ background: t.color }} />
                    <span className="dash-tasktype-label">{t.label}</span>
                    <span className="dash-tasktype-pct">{t.pct}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* 2행: 수신자별 스타일(2fr) | 추천 적용률(2fr) | 주간 활동 추이(2fr) */}
      <div className="dash-grid-3">
        {/* 수신자별 스타일 */}
        <div className="dash-panel">
          <div className="dash-section-title-row">
            <div className="dash-section-title">수신자별 스타일</div>
          </div>
          <div className="dash-panel-sub">읽기 전용 · 수정은 히스토리에서</div>
          {topReceivers.length === 0 ? (
            <div className="dash-empty">아직 학습된 수신자가 없어요.</div>
          ) : (
            <div className="dash-receiver-list-vertical">
              {topReceivers.map((r) => (
                <div className="dash-receiver-row" key={r.id}>
                  <div>
                    <div className="dash-receiver-name">{r.receiverName}</div>
                    <div className="dash-receiver-relationship">{r.relationship || "-"}</div>
                  </div>
                  <div className="dash-receiver-rate">
                    적용률 {r.applyRate != null ? `${Math.round(r.applyRate * 100)}%` : "-"}
                  </div>
                </div>
              ))}
            </div>
          )}
          <Link href="/history/styles" className="dash-more-link">더보기 →</Link>
        </div>

        {/* 추천 적용률 */}
        <div className="dash-panel">
          <div className="dash-section-title">추천 적용률</div>
          <div className="dash-mock-note">
            전체 적용률(실제):{" "}
            {applyRate ? `${Math.round(applyRate.applyRate * 100)}%` : "-"}
          </div>
          <div className="dash-coverage-list">
            {[
              { label: "말투", pct: Math.round(findCoverage("Tone") * 100) },
              { label: "형식", pct: Math.round(findCoverage("Format") * 100) },
              { label: "예시", pct: Math.round(findCoverage("Example") * 100) },
            ].map((m) => {
              const good = m.pct >= 50;
              return (
                <div className="dash-coverage-row" key={m.label}>
                  <span className="dash-coverage-label">{m.label}</span>
                <div className="dash-coverage-bar-track">
                  <div className={`dash-coverage-bar-fill ${good ? "good" : "bad"}`} style={{ width: `${m.pct}%` }} />
                </div>
                  <span className={`dash-coverage-pct ${good ? "good" : "bad"}`}>{m.pct}%</span>
              </div>
              );
            })}
        </div>
      </div>

        {/* 주간 활동 추이 */}
        <div className="dash-panel">
          <div className="dash-section-title-row">
            <div className="dash-section-title">주간 활동 추이</div>
            <span className="dash-panel-sub">이번 주 총 {weeklyTotal}건</span>
          </div>
          <div className="dash-weekly-chart">
            {days.map((d, i) => {
              const isMax = weeklyRealMax > 0 && weeklyValues[i] === weeklyRealMax;
              return (
              <div className="dash-weekly-col" key={d}>
                <div className="dash-weekly-bar-track">
                  <div
                      className={`dash-weekly-bar-fill ${isMax ? "dash-weekly-bar-fill-max" : ""}`}
                    style={{ height: `${(weeklyValues[i] / weeklyMax) * 100}%` }}
                    title={`${d}: ${weeklyValues[i]}건`}
                  />
                </div>
                <span className="dash-weekly-count">{weeklyValues[i]}</span>
                <span className="dash-weekly-day">{weekdayLabel(d)}</span>
              </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import { getPreference, upsertPreference } from "@/api/userPreferences";
import { PREF_QUESTIONS, type QKey } from "@/lib/preferenceQuestions";
import PersonalizationDataActions from "./PersonalizationDataActions";

export default function PersonalizationPage() {
  const [answers, setAnswers] = useState<Partial<Record<QKey, string>>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getPreference()
      .then((pref) => {
        if (!pref) return;
        setAnswers({
          speed: pref.speed ?? undefined,
          detail: pref.detail ?? undefined,
          preserve: pref.preserve ?? undefined,
        });
      })
      .catch((e) => setError(e.message || "설정을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    if (saving) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await upsertPreference({
        speed: answers.speed ?? null,
        detail: answers.detail ?? null,
        preserve: answers.preserve ?? null,
      });
      setSaved(true);
    } catch (e: any) {
      setError(e.message || "저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div style={{ padding: "20px 0", color: "var(--muted)" }}>불러오는 중...</div>;
  }

  return (
    <div>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>
        첫 이용 때 고른 3가지 설정이에요. 언제든 다시 바꿀 수 있어요.
      </p>

      <div className="pref-questions">
        {PREF_QUESTIONS.map((q) => (
          <div
            className="pref-question-card"
            key={q.key}
          >
            <div style={{ fontWeight: 600, fontSize: 14 }}>{q.title}</div>

            <div className="pref-question-btns">
              {q.options.map((opt) => {
                const active = answers[q.key] === opt.value;
                return (
                  <button
                    className={`pref-question-btn ${active ? `active` : ""}`}
                    key={opt.value}
                    onClick={() => { setAnswers((a) => ({ ...a, [q.key]: opt.value })); setSaved(false); }}
                  >
                    {opt.summaryLabel ?? opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {error && <div style={{ color: "var(--block)", marginTop: 16 }}>{error}</div>}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 28 }}>
        <button
          onClick={save}
          disabled={saving}
          style={{
            padding: "10px 20px", borderRadius: 8, border: "none",
            background: "var(--accent)", color: "#fff",
            cursor: saving ? "default" : "pointer", opacity: saving ? 0.7 : 1,
          }}
        >
          {saving ? "저장 중..." : "변경사항 저장"}
        </button>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          {saved ? "저장했어요. 대시보드·홈 화면에 바로 반영돼요." : "대시보드·홈 화면에 바로 반영돼요"}
        </span>
      </div>

      <PersonalizationDataActions />
    </div>
  )
}
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { upsertPreference } from "@/api/userPreferences";
import { PREF_QUESTIONS, type QKey } from "@/lib/preferenceQuestions";

export default function OnboardingPage() {
  const router = useRouter();
  const [answers, setAnswers] = useState<Partial<Record<QKey, string>>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function finish() {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      await upsertPreference({
        speed: answers.speed ?? null,
        detail: answers.detail ?? null,
        preserve: answers.preserve ?? null,
      });
      router.replace("/chat");
    } catch (e: any) {
      setError(e.message || "설정 저장에 실패했습니다. 다시 시도해주세요.");
      setSaving(false);
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: "0 auto" }}>
      <h1>결과물을 어떤 형식으로 받고 싶으세요?</h1>
      <p style={{ color: "var(--muted)" }}>
        3가지만 골라주시면, 다음부턴 물어보지 않고 학습한 내용을 바탕으로 추천해드려요.
      </p>

      {/* 질문-선택지 */}
      {PREF_QUESTIONS.map((q) => (
        <div key={q.key} style={{ marginTop: 24 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            {q.title}
          </div>

          <div style={{ display: "flex", gap: 12 }}>
            {q.options.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setAnswers((a) => ({ ...a, [q.key]: opt.value }))}
                style={{
                  flex: 1, textAlign: "left", padding: 14, borderRadius: 10,
                  border: `1px solid ${answers[q.key] === opt.value ? "var(--accent)" : "var(--line)"}`,
                  background: answers[q.key] === opt.value ? "var(--accent-tint)" : "var(--panel)",
                  cursor: "pointer", fontFamily: "inherit",
                }}
              >
                <div style={{ fontWeight: 600, color: "var(--ink)" }}>{opt.label}</div>
                <div style={{ fontSize: 13, color: "var(--muted)" }}>{opt.desc}</div>
              </button>
            ))}
          </div>
        </div>
      ))}

      {/* 하단 버튼 */}
      {error && <div style={{ color: "var(--block)", marginTop: 16 }}>{error}</div>}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 32}}>
        <span>3개 중 {Object.keys(answers).length}개 선택함</span>

        <div style={{ display: "flex", gap: 12 }}>
          <button
            onClick={finish}
            disabled={saving}
            style={{ background: "none", border: "none", color: "var(--muted)", cursor: saving ? "default" : "pointer" }}
          >
            나중에 설정할게요
          </button>
          <button
            onClick={finish}
            disabled={saving}
            style={{ padding: "10px 20px", borderRadius: 8, border: "none", background: "var(--accent)", color: "#fff", cursor: saving ? "default" : "pointer", opacity: saving ? 0.7 : 1 }}
          >
            {saving ? "저장 중..." : "시작하기"}
          </button>
        </div>
      </div>
    </div>
  );
}
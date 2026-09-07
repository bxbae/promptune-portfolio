"use client";
import { useState } from "react";
import { login, signup, saveToken } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function AuthForm({ onSuccess }: { onSuccess: (name: string) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [wakingUp, setWakingUp] = useState(false);

  async function handleSubmit() {
    setError(""); setLoading(true); setWakingUp(false);
    // 데모 서버(Render 무료 플랜)는 잠시 방치되면 슬립 상태에 들어가고,
    // 다시 깨어나는 데 최대 2분 정도 걸릴 수 있다. 그 사이엔 자동으로
    // 재시도하면서 이 배너로 상황을 알려준다 (진짜 오류는 즉시 표시됨).
    const onWaking = () => setWakingUp(true);
    try {
      const res = mode === "login"
        ? await login(email, password, onWaking)
        : await signup(email, password, name, onWaking);
      saveToken(res.token);
      onSuccess(res.name || res.email);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
      setWakingUp(false);
    }
  }

  // 소셜 로그인: 백엔드 OAuth2 시작 경로로 이동
  function social(provider: "google" | "kakao" | "naver") {
    window.location.href = `${API}/oauth2/authorization/${provider}`;
  }

  return (
    <div className="auth">
      <div className="auth-tabs">
        <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>로그인</button>
        <button className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>회원가입</button>
      </div>

      {mode === "signup" && (
        <input placeholder="이름" value={name} onChange={(e) => setName(e.target.value)} />
      )}
      <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input type="password" placeholder="비밀번호" value={password}
        onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }} />

      {wakingUp && (
        <div className="auth-waking">
          서버를 깨우는 중이에요. 첫 접속 시 최대 2분 정도 걸릴 수 있어요 — 잠시만 기다려 주세요.
        </div>
      )}
      {error && <div className="auth-error">{error}</div>}

      <button className="auth-submit" onClick={handleSubmit} disabled={loading}>
        {loading ? (wakingUp ? "서버 깨우는 중…" : "처리 중…") : mode === "login" ? "로그인" : "가입하기"}
      </button>

      <div className="auth-divider">또는</div>
      <div className="social-buttons">
        <button className="social google" onClick={() => social("google")}>Google로 계속</button>
        <button className="social kakao" onClick={() => social("kakao")}>카카오로 계속</button>
        <button className="social naver" onClick={() => social("naver")}>네이버로 계속</button>
      </div>
      {/* <p className="auth-note">소셜 로그인은 각 제공자 키 설정 후 작동합니다 (docs/AUTH.md).</p> */}
    </div>
  );
}

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

  async function handleSubmit() {
    setError(""); setLoading(true);
    try {
      const res = mode === "login"
        ? await login(email, password)
        : await signup(email, password, name);
      saveToken(res.token);
      onSuccess(res.name || res.email);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
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

      {error && <div className="auth-error">{error}</div>}

      <button className="auth-submit" onClick={handleSubmit} disabled={loading}>
        {loading ? "처리 중…" : mode === "login" ? "로그인" : "가입하기"}
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

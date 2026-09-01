"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import AuthForm from "@/components/AuthForm";
import { getToken } from "@/lib/auth";
import { getPreference } from "@/api/userPreferences";

export default function Home() {
  const router = useRouter();
  const [user, setUser] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // 토큰 있으면 로그인 상태로
    if (getToken()) setUser("사용자");
    setReady(true);
  }, []);

  // 로그인되면: 온보딩 안 했으면 /onboarding, 했으면 /chat으로
  // (DB에 개인화 설정이 저장되어있는지로 판단)
  useEffect(() => {
    if (!ready || !user) return;
    getPreference()
      .then((pref) => router.replace(pref ? "/chat" : "/onboarding"))
      .catch(() => router.replace("/onboarding"));  // 조회 실패해도 온보딩부터 보여주는 것이 안전
  }, [ready, user, router]);

  if (!ready || user) return null;


  // 로그인 전: 사이드바 없이 인증 화면만
  return (
    <main className="page">
      <header className="head">
        <h1>PrompTune</h1>
        <p>거친 지시문을 입력하면 부족한 요소를 짚어 되묻고,<br />다듬어진 프롬프트로 결과를 만듭니다.</p>
      </header>
      <AuthForm onSuccess={setUser} />
    </main>
  );
}

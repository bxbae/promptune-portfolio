"use client";

import { useEffect, useState } from "react";
import { CurrentUser, getCurrentUser, logout } from "@/lib/auth";
import MicrosoftProfileView from "./components/MicrosoftProfileView";
import MicrosoftMembersView from "./components/MicrosoftMembersView";
import ConfirmDialog from "@/components/ConfirmDialog";
import {
  microsoftConnect,
  microsoftDisconnect,
  microsoftEvents,
  microsoftFiles,
  microsoftMembers,
  microsoftProfile,
  microsoftStatus,
  MicrosoftMember,
} from "@/lib/microsoft";

type MsStatus = {
  connected: boolean;
  microsoftEmail?: string;
  displayName?: string;
};

export default function SettingsPage() {
  const [user, setUser] = useState<CurrentUser | null>(null);

  const [msStatus, setMsStatus] = useState<MsStatus>({ connected: false });
  const [msLoading, setMsLoading] = useState(true);
  const [msCallback, setMsCallback] = useState<string | null>(null);
  const [msResult, setMsResult] = useState<unknown>(null);
  const [msError, setMsError] = useState("");

  // 로그아웃/MS 연결 해제 확인 모달 - 누른 버튼 기억
  const [pendingConfirm, setPendingConfirm] = useState<"msDisconnect" | "logout" | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  useEffect(() => {
    setUser(getCurrentUser());
  }, []);

  async function loadMsStatus() {
    try {
      setMsStatus(await microsoftStatus());
    } catch {
      setMsError("Microsoft 연결 상태를 불러오지 못했습니다.");
    } finally {
      setMsLoading(false);
    }
  }

  useEffect(() => {
    setMsCallback(new URLSearchParams(window.location.search).get("microsoft"));
    void loadMsStatus();
  }, []);

  async function handleMsConnect() {
    try {
      const data = await microsoftConnect();
      window.location.href = data.url;
    } catch {
      setMsError("Microsoft 계정 연결을 시작하지 못했습니다.");
    }
  }

  // 연결 해제 - 모달 띄움
  function handleMsDisconnect() {
    setPendingConfirm("msDisconnect");
  }

  async function doMsDisconnect() {
    setConfirmBusy(true);
    try {
      await microsoftDisconnect();
      setMsResult(null);
      await loadMsStatus();
    } catch {
      setMsError("Microsoft 연결 해제에 실패했습니다.");
    } finally {
      setConfirmBusy(false);
      setPendingConfirm(null);
    }
  }

  async function runMsQuery(fn: () => Promise<unknown>) {
    try {
      setMsError("");
      setMsResult(await fn());
    } catch (e) {
      setMsError(e instanceof Error ? e.message : "조회에 실패했습니다.");
    }
  }

  function handleLogout() {
    setPendingConfirm("logout");
  }

  function doLogout() {
    logout();
    window.location.href = "/";
  }

  async function handleConfirm() {
    if (pendingConfirm === "msDisconnect") {
      await doMsDisconnect();
    } else if (pendingConfirm === "logout") {
      doLogout(); // 페이지 이동, 모달 닫기 불필요
    }
  }

  const CONFIRM_TEXT: Record<"msDisconnect" | "logout", { title: string; message: string }> = {
    msDisconnect: { title: "Microsoft 연결 해제", message: "Microsoft 계정 연결을 해제할까요?" },
    logout: { title: "로그아웃", message: "로그아웃할까요?" },
  };

  return (
    <div>
      <h1>설정</h1>
      <p style={{ color: "var(--muted)", marginTop: 4, marginBottom: 24 }}>
        계정과 연동 상태를 관리해요.
      </p>

      <div className="settings-list">
        {/* 계정 정보 */}
        <div className="settings-card">
          <div className="settings-card-header">
            <span className="settings-card-title">계정 정보</span>
            <button className="settings-btn" onClick={handleLogout}>로그아웃</button>
          </div>
          <div className="settings-account-row">
            <div className="settings-avatar">{(user?.name || user?.email || "?")[0].toUpperCase()}</div>
            <div>
              <div className="settings-account-name">{user?.name || "이름 없음"}</div>
              <div className="settings-account-email">{user?.email}</div>
            </div>
          </div>
        </div>

        {/* Microsoft 업무 계정 */}
        {!msLoading && (
          <div className="settings-card">
            {msStatus.connected ? (
              <>
                <div className="settings-card-header">
                  <span className="settings-card-title">Microsoft 업무 계정</span>
                  <span className="settings-badge-connected">연결됨</span>
                </div>
                <p className="settings-card-desc">
                  {msStatus.microsoftEmail || msStatus.displayName || "Microsoft 계정"}
                </p>

                <div className="settings-ms-actions">
                  <button className="settings-ms-action-btn" onClick={() => runMsQuery(microsoftProfile)}>내 프로필</button>
                  <button className="settings-ms-action-btn" onClick={() => runMsQuery(microsoftMembers)}>구성원 프로필</button>
                  <button className="settings-ms-action-btn" onClick={() => runMsQuery(microsoftEvents)}>캘린더</button>
                  <button className="settings-ms-action-btn" onClick={() => runMsQuery(microsoftFiles)}>OneDrive</button>
                </div>

                <button className="settings-btn-danger" onClick={handleMsDisconnect}>연결 해제</button>

                {Array.isArray(msResult) ? (
                  <MicrosoftMembersView members={msResult as MicrosoftMember[]} />
                ) : msResult !== null && typeof msResult === "object" && "displayName" in msResult ? (
                  <MicrosoftProfileView data={msResult} />
                ) : msResult !== null ? (
                  <pre className="settings-ms-result">{JSON.stringify(msResult, null, 2)}</pre>
                ) : null}
              </>
            ) : (
              <div className="settings-ms-empty">
                <div className="settings-ms-empty-icon">
                  <img src="/icons/microsoft.png" alt="" />
                </div>
                <p className="settings-ms-empty-title">Microsoft 업무 계정</p>
                <p className="settings-ms-empty-desc">
                  연결하면 캘린더·OneDrive·메일 정보를<br />프롬프트 개인화에 활용할 수 있어요.
                </p>
                <button className="settings-btn-primary" onClick={handleMsConnect}>Microsoft 계정 연결</button>
              </div>
            )}

            {msCallback === "connected" && <p className="settings-saved-msg">Microsoft 계정 연결 완료</p>}
            {msCallback === "error" && <p style={{ color: "var(--block)", fontSize: 13, marginTop: 8 }}>Microsoft 계정 연결 실패</p>}
            {msError && <p style={{ color: "var(--block)", fontSize: 13, marginTop: 8 }}>{msError}</p>}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingConfirm !== null}
        title={pendingConfirm ? CONFIRM_TEXT[pendingConfirm].title : ""}
        message={pendingConfirm ? CONFIRM_TEXT[pendingConfirm].message : ""}
        confirmLabel={pendingConfirm === "logout" ? "로그아웃" : "해제"}
        danger={pendingConfirm === "msDisconnect"}
        loading={confirmBusy}
        onConfirm={handleConfirm}
        onCancel={() => setPendingConfirm(null)}
      />
    </div>
  );
}

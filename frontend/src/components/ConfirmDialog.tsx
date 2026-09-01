"use client";

// 사이트 전역에서 파괴적 액션(삭제/연결해제/로그아웃 등) 확인에 사용하는 공용 모달.
// window.confirm()을 대체
type ConfirmDialogProps = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;     // 되돌릴 수 없는 액션(삭제 등)이면 true - 확인버튼이 danger로
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "확인",
  cancelLabel = "취소",
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={loading ? undefined : onCancel}>
      <div className="modal-box confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        <p className="confirm-dialog-message">{message}</p>

        <div className="modal-actions">
          <button className="modal-cancel" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </button>
          <button 
            className={`modal-submit${danger ? " modal-submit-danger" : ""}`}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? "처리 중..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
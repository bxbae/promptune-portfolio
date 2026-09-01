"use client";
import { useEffect, useState } from "react";
import {
  listDocuments,
  uploadDocument,
  updateDocument,
  deleteDocument,
  fetchDocumentContent,
  DocumentItem,
  DocType,
} from "@/api/documents";
import ConfirmDialog from "@/components/ConfirmDialog";

type Category = "전체" | DocType;
const TABS: Category[] = ["전체", "규정", "양식", "가이드", "보고서", "기타"];
const DOC_TYPES: DocType[] = ["규정", "양식", "가이드", "보고서", "기타"];

// 파일명을 이름부분/확장자로 분리 (CSS에서 이름부분만 ellipsis 처리, 확장자는 항상 온전히 표시)
function splitFilename(name: string): { base: string; ext: string } {
  const dotIndex = name.lastIndexOf(".");
  if (dotIndex <= 0) return { base: name, ext: "" }; // 확장자 없는 파일명
  return { base: name.slice(0, dotIndex), ext: name.slice(dotIndex) };
}

// 썸네일
function previewKind(fileType: string | null): "doc" | "slide" | "photo" {
  const t = (fileType || "").toLowerCase();
  if (["ppt", "pptx"].includes(t)) return "slide";
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(t)) return "photo";
  return "doc"; // docx / pdf / txt / 기타
}

// txt/md는 실제 내용을 그대로 텍스트로 보여줄 수 있는 타입 (pdf/docx는 별도 렌더링 필요해서 제외)
function isTextPreviewType(fileType: string | null): boolean {
  const t = (fileType || "").toLowerCase();
  return t === "txt" || t === "md";
}

const TEXT_PREVIEW_MAX_CHARS = 220;

export default function FilesPage() {
  const [tab, setTab] = useState<Category>("전체");
  const [files, setFiles] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editDocType, setEditDocType] = useState<DocType>("기타");
  const [showUpload, setShowUpload] = useState(false);
  // 파일 id -> 실제로 읽어온 앞부분 텍스트 (txt/md 썸네일용). 아직 안 불러왔으면 키 자체가 없음.
  const [textPreviews, setTextPreviews] = useState<Record<number, string>>({});
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  function refresh() {
    setLoading(true);
    listDocuments()
      .then(setFiles)
      .catch((e) => setError(e.message || "파일 목록을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, []);

  // txt/md 파일은 목업 줄 대신 실제 앞부분 내용을 썸네일에 보여준다.
  // 목록에 아직 안 불러온 txt/md가 있으면 하나씩 fetch해서 textPreviews에 채워넣는다.
  useEffect(() => {
    const targets = files.filter(
      (f) => isTextPreviewType(f.fileType) && textPreviews[f.id] === undefined
    );
    if (targets.length === 0) return;

    let cancelled = false;

    (async () => {
      for (const f of targets) {
        try {
          const blob = await fetchDocumentContent(f.id);
          if (cancelled) return;
          const buffer = await blob.arrayBuffer();
          const text = new TextDecoder("utf-8").decode(buffer);
          setTextPreviews((prev) => ({
            ...prev,
            [f.id]: text.slice(0, TEXT_PREVIEW_MAX_CHARS),
          }));
        } catch {
          // 못 불러왔으면 빈 문자열로 표시해서 재시도 루프에 빠지지 않게만 하고, 렌더링에서 목업으로 대체
          if (!cancelled) setTextPreviews((prev) => ({ ...prev, [f.id]: "" }));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  const visible = tab === "전체" ? files : files.filter((f) => f.documentType === tab);

  // 수정
  function startEdit(f: DocumentItem) {
    setOpenMenuId(null);
    setEditingId(f.id);
    setEditTitle(f.title);
    setEditDescription(f.description ?? "");
    setEditDocType(f.documentType);
  }

  // 수정 완료
  async function saveEdit(id: number) {
    try {
      const updated = await updateDocument(id, {
        title: editTitle,
        description: editDescription,
        documentType: editDocType,
      });
      setFiles((prev) => prev.map((f) => (f.id === id ? updated : f)));
      setEditingId(null);
    } catch (e: any) {
      alert(e.message || "수정에 실패했습니다.");
    }
  }

  // 삭제 - 모달 띄움
  function handleDelete(f: DocumentItem) {
    setOpenMenuId(null);
    setDeleteTarget(f);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteDocument(deleteTarget.id);
      setFiles((prev) => prev.filter((x) => x.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (e: any) {
      alert(e.message || "삭제에 실패했습니다.");
    } finally {
      setDeleting(false);
    }
  }

  async function handleOpen(file: DocumentItem) {
    const newTab = window.open("about:blank", "_blank");

    if (!newTab) {
      alert("브라우저에서 팝업을 허용해주세요.");
      return;
    }

    try {
      const blob = await fetchDocumentContent(file.id);
      const extension = (file.fileType || "").toLowerCase();

      let previewBlob = blob;

      if (extension === "md" || extension === "txt") {
        const buffer = await blob.arrayBuffer();
        const text = new TextDecoder("utf-8").decode(buffer);

        const escaped = text.replace(
          /[&<>"']/g,
          (char) =>
            ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              '"': "&quot;",
              "'": "&#039;",
            })[char] || char
        );

        const html = `<!doctype html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${file.title}</title>
<style>
body {
  margin: 0;
  padding: 40px;
  background: #f5f5f5;
  color: #222;
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
    "Noto Sans KR", sans-serif;
}
.document {
  max-width: 1000px;
  margin: 0 auto;
  padding: 48px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 14px rgba(0, 0, 0, 0.08);
}
pre {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: 15px/1.7 ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
</head>
<body>
  <main class="document"><pre>${escaped}</pre></main>
</body>
</html>`;

        previewBlob = new Blob(
          [html],
          { type: "text/html;charset=UTF-8" }
        );
      }

      const url = URL.createObjectURL(previewBlob);
      newTab.location.href = url;
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e: unknown) {
      newTab.close();
      alert(e instanceof Error ? e.message : "파일을 열 수 없습니다.");
    }
  }

  return (
    <div>
      {/* files-header */}
      <div className="files-header">
        <h1>파일관리</h1>
        <div className="files-header-bottom">
          <div className="files-tabs">
            {TABS.map((t) => (
              <button
                key={t}
                className={`files-tab ${tab === t ? "active" : ""}`}
                onClick={() => setTab(t)}
              >
                {t}
              </button>
            ))}
          </div>

          <button
            className="files-upload-btn"
            type="button"
            onClick={() => setShowUpload(true)}
          >
            <img src="/icons/plus-white.png" />
            <span>파일 업로드</span>
          </button>
        </div>
      </div>

      {loading && <div style={{ color: "var(--muted)" }}>불러오는 중...</div>}
      {!loading && error && <div style={{ color: "var(--block)" }}>{error}</div>}

      {/* files-grid */}
      {!loading && !error && (
        <div className="files-grid">
          {visible.map((file) => (
            <div
              className="file-card"
              key={file.id}
              onClick={() => {
                if (editingId !== file.id) void handleOpen(file);
              }}
            >
              <div className="file-thumb">
                <FilePreview
                  kind={previewKind(file.fileType)}
                  textPreview={isTextPreviewType(file.fileType) ? textPreviews[file.id] : undefined}
                />
              </div>

              {/* file-name-wrap: 원래 파일명 자리는 항상 유지하고(높이 그대로), 수정 중이면
                  그 위에 드롭다운으로 편집창을 겹쳐서 띄운다. 예전엔 이 자리가 통째로
                  edit-row로 바뀌면서 카드 높이가 늘어나 같은 행의 다른 카드들까지 밀렸는데,
                  position:absolute 오버레이라 레이아웃에 영향을 안 준다. */}
              <div className="file-name-wrap">
                <div
                  className={`file-name${editingId === file.id ? " editing" : ""}`}
                  title={file.title}
                >
                  <span className="file-name-base">{splitFilename(file.title).base}</span>
                  <span className="file-name-ext">{splitFilename(file.title).ext}</span>
                </div>

                {editingId === file.id && (
                  <div
                    className="file-edit-dropdown"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      className="file-edit-input"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      placeholder="제목"
                      autoFocus
                    />
                    <input
                      className="file-edit-input"
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      placeholder="설명 (선택)"
                    />

                    <select value={editDocType} onChange={(e) => setEditDocType(e.target.value as DocType)}>
                      {DOC_TYPES.map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>

                    <div className="file-edit-actions">
                      <button className="file-edit-save" onClick={() => saveEdit(file.id)}>저장</button>
                      <button className="file-edit-cancel" onClick={() => setEditingId(null)}>취소</button>
                    </div>
                  </div>
                )}
              </div>

              {/* 배지/메뉴 버튼은 이제 file-thumb 밖(=file-card 바로 아래)에 둔다.
                  file-card가 file-thumb과 같은 폭/원점을 가져서 absolute 좌표는 그대로 유지되고
                  (데스크톱은 변화 없음), 모바일 1열 가로형 카드에서는 자연스럽게 행의 끝에
                  오도록 만들 수 있다 (전에는 좁은 thumb 안에 갇혀서 재배치가 불가능했음). */}
              <span className="file-badge">{file.documentType}</span>
              <button
                className="file-menu-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setOpenMenuId(openMenuId === file.id ? null : file.id);
                }}
                aria-label="파일 옵션"
              >
                <img src="/icons/dots.png" />
              </button>

              {openMenuId === file.id && (
                <div
                  className="file-menu"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button onClick={() => startEdit(file)}>수정</button>
                  <button className="danger" onClick={() => handleDelete(file)}>삭제</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 파일이 없을 때 */}
      {!loading && !error && visible.length === 0 && (
        <div style={{ padding: "60px 0", textAlign: "center", color: "var(--muted)" }}>
          해당 분류의 파일이 없어요.
        </div>
      )}

      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onUploaded={(doc) => {
            setFiles((prev) => [doc, ...prev]);
            setShowUpload(false);
          }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="파일 삭제"
        message={`"${deleteTarget?.title}" 파일을 삭제할까요?`}
        confirmLabel="삭제"
        danger
        loading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

// 파일 썸네일
function FilePreview({
  kind,
  textPreview,
}: {
  kind: "doc" | "slide" | "photo";
  textPreview?: string;
}) {
  // txt/md - 실제 파일 앞부분 텍스트를 그대로 보여줌 (fetch 완료된 경우만)
  if (kind === "doc" && textPreview) {
    return (
      <div className="preview-doc-text">
        <pre>{textPreview}</pre>
      </div>
    );
  }
  if (kind === "slide") {
    return (
      <div className="preview-slide">
        <span className="preview-slide-shape" />
      </div>
    );
  }
  if (kind === "photo") {
    return (
      <div className="preview-photo">
        <span className="preview-photo-icon">🖼</span>
      </div>
    );
  }
  // doc / pdf: 텍스트 줄 목업
  return (
    <div className="preview-doc">
      {[90, 70, 80, 60, 75, 50].map((w, i) => (
        <span key={i} className="preview-line" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

// 업로드 모달창
function UploadModal({
  onClose,
  onUploaded
}: {
  onClose: () => void,
  onUploaded: (doc: DocumentItem) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [docType, setDocType] = useState<DocType>("기타");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    // 제목을 아직 안 건드렸으면(비어있으면) 파일명으로 자동 채워줌
    if (f && !title.trim()) {
      setTitle(f.name);
    }
  }

  async function submit() {
    if (!file) {
      setErr("파일을 선택해주세요.");
      return;
    }
    if (!title.trim()) {
      setErr("제목을 입력해주세요.");
      return;
    }
    setSubmitting(true);
    setErr("");
    try {
      const doc = await uploadDocument(file, title.trim(), docType, description.trim() || undefined);
      onUploaded(doc);
    } catch (e: any) {
      setErr(e.message || "업로드에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2>파일 업로드</h2>

        <label className="modal-label">파일</label>
        <input
          className="modal-input"
          type="file"
          accept=".pdf,.docx,.txt,.md,.xlsx,.pptx"
          onChange={handleFileChange}
        />

        <label className="modal-label">제목</label>
        <input className="modal-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 이력서 양식.docx" />

        <label className="modal-label">설명 (선택)</label>
        <input
          className="modal-input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="이 문서가 어떤 내용인지 간단히 적어주세요"
        />

        <label className="modal-label">분류</label>
        <select className="modal-input" value={docType} onChange={(e) => setDocType(e.target.value as DocType)}>
          {DOC_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        {err && <div style={{ color: "var(--block)", fontSize: 12, marginTop: 8 }}>{err}</div>}

        <div className="modal-actions">
          <button className="modal-cancel" onClick={onClose}>취소</button>
          <button className="modal-submit" onClick={submit} disabled={submitting}>
            {submitting ? "업로드 중…" : "업로드"}
          </button>
        </div>
      </div>
    </div>
  );
}

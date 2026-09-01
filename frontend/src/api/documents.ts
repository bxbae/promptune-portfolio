// DocumentController(/api/documents) 전용 API 클라이언트.
// 실제 파일을 multipart/form-data로 업로드하면 백엔드가 S3(promptune-document 버킷)에 저장하고
// 메타데이터(title/documentType/s3Key/fileType)를 DB에 저장한다.

// documentType 표기 규칙: UI 상에서는 한글, 백엔드에서 받는 값은 영문 enum
import { getToken } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export type DocType = "규정" | "양식" | "가이드" | "보고서" | "기타";

const KO_TO_ENUM: Record<DocType, string> = {
  "규정": "POLICY",
  "양식": "TEMPLATE",
  "가이드": "GUIDE",
  "보고서": "REPORT",
  "기타": "OTHER",
};

const ENUM_TO_KO: Record<string, DocType> = {
  POLICY: "규정",
  TEMPLATE: "양식",
  GUIDE: "가이드",
  REPORT: "보고서",
  OTHER: "기타",
};

export function toEnum(k: DocType): string {
  return KO_TO_ENUM[k] ?? "OTHER";
}

export function toKorean(e: string | null | undefined): DocType {
  if (!e) return "기타";
  return ENUM_TO_KO[e] ?? "기타";
}

export interface DocumentItem {
  id: number;
  ownerUserId: number;
  title: string;
  description: string | null;
  documentType: DocType; // 항상 한글로 노출 (원본 응답은 영문 enum, 여기서 변환)
  s3Key: string | null;
  fileType: string | null;
  indexStatus?: "UPLOADED" | "INDEXING" | "TEXT_READY" | "READY" | "FAILED";
  indexError?: string | null;
  indexedAt?: string | null;
}

// 백엔드가 실제로 내려주는 원본 형태 (documentType이 영문 enum)
interface RawDocumentItem extends Omit<DocumentItem, "documentType"> {
  documentType: string;
}

function fromRaw(raw: RawDocumentItem): DocumentItem {
  return { ...raw, documentType: toKorean(raw.documentType) };
}

function authHeaders(): HeadersInit {
  const token = getToken();
  if (!token) throw new Error("로그인이 필요합니다.");
  return { Authorization: `Bearer ${token}` };
}

// Create - POST /api/documents (multipart/form-data)
// 주의: FormData를 쓸 때는 Content-Type 헤더를 직접 지정하면 안 됨
// (브라우저가 boundary를 포함해서 자동으로 설정해야 함)
export async function uploadDocument(
  file: File,
  title: string,
  documentType: DocType,
  description?: string
): Promise<DocumentItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("title", title);
  formData.append("documentType", toEnum(documentType));
  if (description) formData.append("description", description);

  const res = await fetch(`${API}/api/documents`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || `업로드 실패: ${res.status}`);
  }
  const raw: RawDocumentItem = await res.json();
  return fromRaw(raw);
}

// Read - GET /api/documents
export async function listDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API}/api/documents`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`파일 목록 조회 실패: ${res.status}`);
  const raw: RawDocumentItem[] = await res.json();
  return raw.map(fromRaw);
}

// 원본 파일 조회
export async function fetchDocumentContent(id: number): Promise<Blob> {
  const res = await fetch(`${API}/api/documents/${id}/content`, {
    headers: authHeaders(),
  });

  if (!res.ok) {
    throw new Error(`파일 열기 실패: ${res.status}`);
  }

  return res.blob();
}

// Update - PATCH /api/documents/{id} - title, description, documentType 수정 가능
export async function updateDocument(
  id: number,
  patch: { title?: string; description?: string; documentType?: DocType }
): Promise<DocumentItem> {
  const body: Record<string, string> = {};
  if (patch.title !== undefined) body.title = patch.title;
  if (patch.description !== undefined) body.description = patch.description;
  if (patch.documentType !== undefined) body.documentType = toEnum(patch.documentType);

  const res = await fetch(`${API}/api/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new Error(errBody?.error || `수정 실패: ${res.status}`);
  }
  const raw: RawDocumentItem = await res.json();
  return fromRaw(raw);
}

export async function reindexDocument(id: number): Promise<DocumentItem> {
  const res = await fetch(`${API}/api/documents/${id}/reindex`, {
    method: "POST",
    headers: authHeaders(),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || body?.message || `재인덱싱 실패: ${res.status}`);
  }

  const raw: RawDocumentItem = await res.json();
  return fromRaw(raw);
}

// Delete - DELETE /api/documents/{id}
export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`${API}/api/documents/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`삭제 실패: ${res.status}`);
}
export type DocumentFormat = "docx" | "pdf";

export async function generateDocumentFile(
  title: string,
  content: string,
  format: DocumentFormat,
  templateDocumentId?: number,
): Promise<Blob> {
  const res = await fetch(`${API}/api/documents/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      title,
      content,
      format,
      templateDocumentId: templateDocumentId ?? null,
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error || `문서 생성 실패: ${res.status}`
    );
  }

  return res.blob();
}

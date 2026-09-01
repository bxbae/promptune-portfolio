from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.services.documents.document_content import DocumentContent
from app.services.documents.docx_renderer import render_docx


def render_pdf_from_docx(
    doc: DocumentContent,
) -> bytes:
    docx_bytes = render_docx(doc)

    with tempfile.TemporaryDirectory(
        prefix="promptune_pdf_"
    ) as temp_dir:
        workdir = Path(temp_dir)

        docx_path = workdir / "document.docx"
        pdf_path = workdir / "document.pdf"

        docx_path.write_bytes(docx_bytes)

        result = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(workdir),
                str(docx_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "LibreOffice PDF 변환 실패: "
                + result.stderr.strip()
            )

        if not pdf_path.exists():
            raise RuntimeError(
                "LibreOffice가 PDF 파일을 생성하지 않았습니다. "
                f"stdout={result.stdout.strip()} "
                f"stderr={result.stderr.strip()}"
            )

        data = pdf_path.read_bytes()

        if not data.startswith(b"%PDF-"):
            raise RuntimeError(
                "생성된 파일이 유효한 PDF가 아닙니다."
            )

        return data

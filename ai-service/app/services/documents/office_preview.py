from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


SUPPORTED = {
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".ppt", ".pptx",
}


def convert_office_to_pdf(data: bytes, filename: str) -> bytes:
    suffix = Path(filename).suffix.lower()

    if suffix not in SUPPORTED:
        raise ValueError(f"미리보기를 지원하지 않는 형식입니다: {suffix}")

    with tempfile.TemporaryDirectory(
        prefix="promptune_preview_"
    ) as temp_dir:
        workdir = Path(temp_dir)
        source = workdir / f"source{suffix}"
        output = workdir / "source.pdf"
        profile = workdir / "libreoffice-profile"

        source.write_bytes(data)

        result = subprocess.run(
            [
                "libreoffice",
                f"-env:UserInstallation={profile.as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(workdir),
                str(source),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Office PDF 변환 실패: " + result.stderr.strip()
            )

        if not output.exists():
            raise RuntimeError(
                "PDF가 생성되지 않았습니다. "
                f"stdout={result.stdout.strip()} "
                f"stderr={result.stderr.strip()}"
            )

        pdf = output.read_bytes()

        if not pdf.startswith(b"%PDF-"):
            raise RuntimeError("변환 결과가 올바른 PDF가 아닙니다.")

        return pdf

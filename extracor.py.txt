from __future__ import annotations

from typing import Optional

from docx import Document
from pypdf import PdfReader


def _read_txt(data: bytes) -> str:
    # Try UTF-8 first, then fallback
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _read_pdf(data: bytes) -> str:
    reader = PdfReader(stream=data)
    parts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        parts.append(text)
    combined = "\n".join(parts).strip()
    if not combined:
        raise ValueError("PDF text extraction returned empty text (might be scanned image PDF).")
    return combined


def _read_docx(data: bytes) -> str:
    # python-docx expects a file-like object
    import io

    file_like = io.BytesIO(data)
    doc = Document(file_like)
    parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    combined = "\n".join(parts).strip()
    if not combined:
        raise ValueError("DOCX extraction returned empty text.")
    return combined


def extract_text_from_upload(upload) -> str:
    """
    Streamlit UploadedFile -> extract text from TXT, PDF, DOCX.
    Raises helpful errors if extraction fails.
    """
    if upload is None:
        raise ValueError("No file uploaded.")

    name = getattr(upload, "name", "uploaded")
    ext = name.split(".")[-1].lower().strip()

    data = upload.read()
    if not data:
        raise ValueError("Uploaded file is empty.")

    if ext == "txt":
        return _read_txt(data)
    if ext == "pdf":
        return _read_pdf(data)
    if ext == "docx":
        return _read_docx(data)

    raise ValueError(f"Unsupported file type: .{ext}")

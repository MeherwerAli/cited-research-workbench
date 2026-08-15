import hashlib
import io
import re
import uuid
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .models import Chunk, DocumentRecord


class PDFValidationError(ValueError):
    pass


@dataclass(frozen=True)
class IngestedDocument:
    record: DocumentRecord
    chunks: list[Chunk]


def _chunk_text(text: str, max_words: int = 180, overlap_words: int = 30) -> list[str]:
    words = re.findall(r"\S+", text)
    chunks: list[str] = []
    step = max_words - overlap_words
    for start in range(0, len(words), step):
        candidate = " ".join(words[start : start + max_words]).strip()
        if candidate:
            chunks.append(candidate)
        if start + max_words >= len(words):
            break
    return chunks


def ingest_pdf(data: bytes, filename: str, *, max_bytes: int, max_pages: int) -> IngestedDocument:
    if not data or len(data) > max_bytes:
        raise PDFValidationError(f"PDF must contain between 1 and {max_bytes} bytes")
    if not data.startswith(b"%PDF-"):
        raise PDFValidationError("file does not have a PDF signature")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
    except (PdfReadError, OSError, ValueError) as error:
        raise PDFValidationError("PDF is malformed") from error
    if reader.is_encrypted:
        raise PDFValidationError("encrypted PDFs are not supported")
    if not 1 <= len(reader.pages) <= max_pages:
        raise PDFValidationError(f"PDF must contain between 1 and {max_pages} pages")
    source_hash = hashlib.sha256(data).hexdigest()
    document_id = f"doc_{source_hash[:20]}"
    chunks: list[Chunk] = []
    extracted_characters = 0
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = " ".join((page.extract_text() or "").split())
        except Exception as error:
            raise PDFValidationError(f"page {page_number} text extraction failed") from error
        extracted_characters += len(text)
        for index, content in enumerate(_chunk_text(text)):
            chunks.append(
                Chunk(
                    id=f"chk_{uuid.uuid5(uuid.NAMESPACE_URL, f'{source_hash}:{page_number}:{index}').hex}",
                    document_id=document_id,
                    page=page_number,
                    text=content,
                    source_sha256=source_hash,
                )
            )
    if extracted_characters < 40 or not chunks:
        raise PDFValidationError(
            "PDF has no usable digital text; OCR is intentionally out of scope"
        )
    return IngestedDocument(
        record=DocumentRecord(
            id=document_id,
            filename=filename,
            source_sha256=source_hash,
            page_count=len(reader.pages),
            chunk_count=len(chunks),
        ),
        chunks=chunks,
    )

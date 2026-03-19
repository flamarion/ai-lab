"""Document loading and chunking for RAG ingestion."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# File extensions we can load
TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".csv", ".log"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".go", ".rs", ".rb", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".html", ".css",
    ".sql", ".tf", ".hcl", ".Dockerfile",
}
PDF_EXTENSIONS = {".pdf"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | CODE_EXTENSIONS | PDF_EXTENSIONS


def load_file(path: str) -> str:
    """Read a file and return its text content.

    Supports plain text, code, markdown, and PDF files.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return _load_pdf(path)
    if suffix in TEXT_EXTENSIONS | CODE_EXTENSIONS or p.name == "Dockerfile":
        return p.read_text(encoding="utf-8", errors="replace")

    raise ValueError(f"Unsupported file type: {suffix}")


def load_bytes(content: bytes, filename: str) -> str:
    """Load content from bytes (for file uploads)."""
    suffix = Path(filename).suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return _load_pdf_bytes(content)
    return content.decode("utf-8", errors="replace")


def _load_pdf(path: str) -> str:
    """Extract text from a PDF file."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _load_pdf_bytes(content: bytes) -> str:
    """Extract text from PDF bytes."""
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
) -> list[dict]:
    """Split text into overlapping chunks.

    Strategy: split on paragraphs first, then sentences, then by character
    count. Each chunk records its position in the original text.

    Args:
        text: The full document text.
        chunk_size: Target chunk size in characters (~tokens * 4).
        overlap: Number of characters to overlap between chunks.

    Returns:
        List of dicts with keys: text, chunk_index, start_offset, end_offset.
    """
    if not text.strip():
        return []

    # Normalize whitespace but preserve paragraph breaks
    text = re.sub(r"\r\n", "\n", text)

    # Split into paragraphs (double newline)
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    # Build chunks by accumulating paragraphs up to chunk_size
    chunks = []
    current = ""
    current_start = 0
    offset = 0

    for para in paragraphs:
        # Find the actual offset of this paragraph in the original text
        para_start = text.find(para, offset)
        if para_start == -1:
            para_start = offset

        if not current:
            current = para
            current_start = para_start
        elif len(current) + len(para) + 2 <= chunk_size:
            current = current + "\n\n" + para
        else:
            # Flush current chunk
            chunks.append({
                "text": current,
                "chunk_index": len(chunks),
                "start_offset": current_start,
                "end_offset": current_start + len(current),
            })
            # Start new chunk with overlap from the end of the previous
            if overlap > 0 and len(current) > overlap:
                overlap_text = current[-overlap:]
                current = overlap_text + "\n\n" + para
                current_start = current_start + len(current) - len(overlap_text) - len(para) - 2
            else:
                current = para
                current_start = para_start

        offset = para_start + len(para)

    # Don't forget the last chunk
    if current.strip():
        chunks.append({
            "text": current,
            "chunk_index": len(chunks),
            "start_offset": current_start,
            "end_offset": current_start + len(current),
        })

    # If any chunk is still too large, split by sentences
    final_chunks = []
    for chunk in chunks:
        if len(chunk["text"]) <= chunk_size * 1.5:
            chunk["chunk_index"] = len(final_chunks)
            final_chunks.append(chunk)
        else:
            sub_chunks = _split_large_chunk(chunk["text"], chunk_size, chunk["start_offset"])
            for sc in sub_chunks:
                sc["chunk_index"] = len(final_chunks)
                final_chunks.append(sc)

    return final_chunks


def _split_large_chunk(text: str, chunk_size: int, base_offset: int) -> list[dict]:
    """Split an oversized chunk by sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    current_start = base_offset

    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + len(sentence) + 1 <= chunk_size:
            current = current + " " + sentence
        else:
            chunks.append({
                "text": current,
                "chunk_index": 0,
                "start_offset": current_start,
                "end_offset": current_start + len(current),
            })
            current_start = current_start + len(current) + 1
            current = sentence

    if current.strip():
        chunks.append({
            "text": current,
            "chunk_index": 0,
            "start_offset": current_start,
            "end_offset": current_start + len(current),
        })

    return chunks

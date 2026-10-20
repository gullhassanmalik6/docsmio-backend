from pathlib import Path


def sanitize_text(value: str, limit: int = 20000) -> str:
    cleaned = "".join(character for character in value if character in "\n\t" or ord(character) >= 32)
    return cleaned[:limit].strip()


def extract_pdf_text(path: Path) -> tuple[str | None, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "failed"
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return None, "unavailable"
        parts: list[str] = []
        total = 0
        for page in reader.pages[:20]:
            piece = page.extract_text() or ""
            parts.append(piece)
            total += len(piece)
            if total >= 20000:
                break
        text = sanitize_text("\n".join(parts))
        if not text:
            return None, "unavailable"
        return text, "ready"
    except Exception:
        return None, "failed"


def extract_for_mime(mime_type: str, path: Path) -> tuple[str | None, str]:
    if mime_type == "application/pdf":
        return extract_pdf_text(path)
    if mime_type.startswith("image/"):
        return None, "pending"
    return None, "unsupported"

import re
from datetime import date

RULES: list[tuple[str, str, list[str]]] = [
    ("Scholarship", "educational", ["scholarship", "fellowship"]),
    ("Admission", "educational", ["admission", "university application"]),
    ("Academic", "educational", ["marksheet", "transcript", "diploma", "degree", "matriculation", "intermediate", "academic certificate"]),
    ("Identity", "identification", ["passport", "identity card", "national id", "birth certificate", "cnic"]),
    ("Travel and Immigration", "identification", ["visa", "residence permit"]),
    ("Employment", "career", ["resume", "curriculum vitae", "cv", "offer letter", "employment", "experience certificate", "experience letter"]),
    ("Financial", "financial", ["invoice", "receipt", "bank statement", "tax return", "salary slip"]),
    ("Medical", "medical", ["prescription", "medical report", "vaccination", "lab report", "discharge summary"]),
    ("Certificates", "educational", ["certificate", "licence", "license"]),
]

SUGGESTED_CATEGORIES = [name for name, _folder, _terms in RULES] + ["Other"]
DATE_RE = re.compile(r"\b(19\d{2}|20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")


def _hits(haystack: str, terms: list[str]) -> list[str]:
    lowered = haystack.lower()
    return [term for term in terms if term in lowered]


def _confidence(matched: list[str]) -> str:
    if not matched:
        return "low"
    if len(matched) >= 2 or any(" " in term for term in matched):
        return "high"
    return "medium"


def _best(haystack: str) -> tuple[str, str, list[str], str] | None:
    winner: tuple[str, str, list[str], str] | None = None
    for category, folder_key, terms in RULES:
        matched = _hits(haystack, terms)
        if not matched:
            continue
        confidence = _confidence(matched)
        if winner is None or (confidence == "high" and winner[3] != "high") or len(matched) > len(winner[2]):
            winner = (category, folder_key, matched, confidence)
    return winner


def suggest_date(text: str | None) -> tuple[date | None, str | None]:
    if not text:
        return None, None
    lowered = text.lower()
    for match in DATE_RE.finditer(text):
        window = lowered[max(0, match.start() - 48) : min(len(lowered), match.end() + 48)]
        try:
            found = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        if re.search(r"deadline|due date|submit by", window):
            return found, "deadline"
        if re.search(r"expir|valid until|valid thru", window):
            return found, "expiry"
    return None, None


def classify_document(filename: str, text: str | None) -> dict:
    from_name = _best(filename)
    from_text = _best(text or "")
    chosen = from_text or from_name
    method = "file_type"
    if from_text and (from_name is None or from_text[3] == "high" or from_name[3] != "high"):
        chosen = from_text
        method = "text"
    elif from_name:
        chosen = from_name
        method = "filename"
    date_value, date_label = suggest_date(text)
    if chosen is None:
        return {
            "category": "Other",
            "folder_key": "uncategorized",
            "confidence": "low",
            "method": method,
            "matched": [],
            "date": date_value,
            "date_label": date_label,
        }
    return {
        "category": chosen[0],
        "folder_key": chosen[1],
        "confidence": chosen[3],
        "method": method,
        "matched": chosen[2],
        "date": date_value,
        "date_label": date_label,
    }

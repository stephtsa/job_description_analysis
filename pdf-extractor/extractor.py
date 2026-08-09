"""PDF extraction for fillable forms (AcroForm) and text-based position descriptions."""

import re

import fitz

# Broader section (used for text preview / fallback)
START_PATTERNS = [
    r"Introduction",
    r"i\.\s*INTRODUCTION",
    r"II\.\s*MAJOR DUTIES AND RESPONSIBILITIES",
    r"MAJOR\s*DUTIES\s*AND\s*RESPONSIBILITIES",
    r"Major\s*duties\s*and\s*responsibilities",
    r"Major\s*duties:",
    r"Primary\s*responsibilities",
]

END_PATTERNS = [
    r"III\.\s*FACTOR LEVELS",
    r"III\.\s*FACTOR",
    r"FACTOR\s*LEVELS",
    r"Factor 1\s*[–\-]\s*Knowledge",
    r"Factor 1\s*Statements",
    r"III\.\s*FACTOR\s+LEVELS and Factor\s+1\s*\S*\s*Knowledge",
    r"FACTOR\sEVALUATION\sSUMMARY",
]

# Prefer the Major Duties block itself for row-level parsing
DUTY_START_PATTERNS = [
    r"2\.\s*Major Duties and Responsibilities",
    r"II\.\s*MAJOR DUTIES AND RESPONSIBILITIES",
    r"MAJOR\s*DUTIES\s*AND\s*RESPONSIBILITIES",
    r"Major\s*duties\s*and\s*responsibilities",
    r"Major\s*Duties\s*and\s*Responsibilities",
    r"Major\s*duties:",
    r"Primary\s*responsibilities",
]

DUTY_END_PATTERNS = [
    r"3\.\s*Supervisory Controls",
    r"III\.\s*FACTOR LEVELS",
    r"III\.\s*FACTOR",
    r"FACTOR\s*LEVELS",
    r"Factor 1\s*[–\-]\s*Knowledge",
    r"Factor 1\s*Statements",
    r"FACTOR\sEVALUATION\sSUMMARY",
    r"4\.\s*Guidelines",
    r"Supervisory Controls",
]

# "1. Program Evaluation & Analysis — 40%"
LABEL_LINE_RE = re.compile(
    r"(?m)^\s*(?:\d+\.\s*)?(?P<duty_type>[A-Za-z][^\n]{1,120}?)"
    r"\s*[—–\-]\s*(?P<pct>\d{1,3})\s*%\s*$"
)

BULLET_LINE_RE = re.compile(r"(?m)^\s*(?:--|•|●|▪|‣|\*)\s+(.+?)\s*$")


def extract_form_data_pymupdf(pdf_path: str) -> dict:
    """AcroForm field values via PyMuPDF (one dict entry per widget)."""
    form_data = {}
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            for widget in page.widgets() or []:
                name = widget.field_name
                if not name:
                    continue
                val = widget.field_value
                form_data[name] = "" if val is None else str(val)
    finally:
        doc.close()
    return form_data


def _normalize_raw_text(text: str) -> str:
    """Fix common PDF quirks (non-breaking spaces, soft hyphens)."""
    text = text.replace("\xa0", " ").replace("\xad", "-").replace("\u2013", "-")
    text = text.replace("\u2014", "-").replace("\ufb01", "fi").replace("\ufb02", "fl")
    # Normalize unusual separators seen in some PDFs
    text = text.replace("\u037e", ";").replace("\uff1b", ";").replace("；", ";")
    text = text.replace("\u2022", "•").replace("\u00b7", "•")
    return text


def _join_wrapped_lines(section: str) -> str:
    """Join PDF line wraps so bullets/sentences stay intact."""
    lines = section.splitlines()
    if not lines:
        return section

    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if merged and merged[-1] != "":
                merged.append("")
            continue

        # Bare bullets (common when "•" is alone on a line) start a new item.
        if re.fullmatch(r"(?:--|•|●|▪|‣|\*)", stripped):
            merged.append(f"{stripped} ")
            continue

        starts_new = bool(
            re.match(r"^\d+\.\s+\S+", stripped)
            or re.search(r"[—–\-]\s*\d{1,3}\s*%\s*$", stripped)
            or re.match(r"^(?:--|•|●|▪|‣|\*)\s+\S+", stripped)
        )
        prev = merged[-1] if merged else ""
        prev_complete = bool(
            prev
            and (
                prev.endswith((".", "?", "!", ":", ";", "%"))
                or re.search(r"[—–\-]\s*\d{1,3}\s*%\s*$", prev)
            )
        )
        if merged and not starts_new and prev and not prev_complete:
            merged[-1] = f"{prev} {stripped}"
        else:
            merged.append(stripped)
    return "\n".join(merged)


def _clean_inline(text: str) -> str:
    cleaned = _normalize_raw_text(text)
    cleaned = re.sub(r"[\uf000-\uffff]", " ", cleaned)
    cleaned = re.sub(r"_+\s*\d*%?\\?n?", " ", cleaned)
    cleaned = re.sub(r"/s/", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" \t;-•")


def _clean_pdf_text(text: str) -> str:
    cleaned = _normalize_raw_text(text)
    cleaned = re.sub(r"\n+", " ", cleaned)
    cleaned = re.sub(r"_+\s*\d*%?\\?n?[\uf000-\uffff]*", " ", cleaned)
    cleaned = re.sub(r"[\uf000-\uffff]", " ", cleaned)
    cleaned = re.sub(r"\\u[0-9a-fA-F]{4}", " ", cleaned)
    cleaned = re.sub(r"\\u", " ", cleaned)
    cleaned = re.sub(r"/s/", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _extract_section_by_patterns(
    text: str, start_patterns: list[str], end_patterns: list[str]
) -> str | None:
    start_match = None
    for pat in start_patterns:
        start_match = re.search(pat, text, re.IGNORECASE)
        if start_match:
            break
    if not start_match:
        return None

    remainder = text[start_match.end() :]
    end_match = None
    for pat in end_patterns:
        end_match = re.search(pat, remainder, re.IGNORECASE)
        if end_match:
            break

    if end_match:
        section_text = remainder[: end_match.start()].strip()
    else:
        section_text = remainder.strip()
    return section_text if section_text else None


def _dedupe_duty_rows(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    unique_rows: list[dict] = []
    for row in rows:
        key = (
            (row.get("duty_type") or "").strip().lower(),
            str(row.get("percentage_weight") or "").strip(),
            _clean_inline(row.get("duty_text") or "").lower(),
        )
        if not key[2] or key in seen:
            continue
        seen.add(key)
        unique_rows.append(
            {
                "duty_type": row.get("duty_type") or "",
                "percentage_weight": row.get("percentage_weight")
                if row.get("percentage_weight") not in (None, "")
                else "",
                "duty_text": _clean_inline(row.get("duty_text") or ""),
            }
        )
    return unique_rows


def _parse_labeled_duties(section: str) -> list[dict] | None:
    matches = list(LABEL_LINE_RE.finditer(section))
    if not matches:
        return None

    rows: list[dict] = []
    for i, match in enumerate(matches):
        block_start = match.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[block_start:block_end].strip()

        bullets = BULLET_LINE_RE.findall(body)
        if bullets:
            duty_text = " ".join(_clean_inline(b) for b in bullets if _clean_inline(b))
        else:
            # Keep prose under the label if bullets were flattened
            duty_text = _clean_inline(body)

        rows.append(
            {
                "duty_type": _clean_inline(match.group("duty_type")),
                "percentage_weight": int(match.group("pct")),
                "duty_text": duty_text,
            }
        )
    return _dedupe_duty_rows(rows)


def _parse_bullet_duties(section: str) -> list[dict] | None:
    bullets = [_clean_inline(b) for b in BULLET_LINE_RE.findall(section)]
    bullets = [b for b in bullets if b and len(b) > 8]
    if not bullets:
        # Also support inline "-- " separators from cleaned text
        inline = re.split(r"\s+--\s+", section)
        if len(inline) > 1:
            bullets = [_clean_inline(x) for x in inline[1:]]
            bullets = [b for b in bullets if b and len(b) > 8]
    if not bullets:
        return None
    return _dedupe_duty_rows(
        [{"duty_type": "", "percentage_weight": "", "duty_text": b} for b in bullets]
    )


def _parse_sentence_duties(section: str) -> list[dict]:
    text = _clean_pdf_text(section)
    text = re.sub(
        r"^.*?\binclude the following:\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^Duties typically performed include the following:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Prefer semicolon lists when present (common in trainee PDs)
    if text.count(";") >= 2:
        parts = [ _clean_inline(p) for p in text.split(";") ]
        parts = [p for p in parts if p and len(p) > 8]
        if parts:
            return _dedupe_duty_rows(
                [
                    {"duty_type": "", "percentage_weight": "", "duty_text": p}
                    for p in parts
                ]
            )

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    rows = []
    skip_prefixes = (
        "note:",
        "this position",
        "the incumbent of this position",
        "ii.",
        "major duties",
    )
    for sentence in sentences:
        cleaned = _clean_inline(sentence)
        if not cleaned or len(cleaned) < 20:
            continue
        if cleaned.lower().startswith(skip_prefixes):
            continue
        rows.append(
            {"duty_type": "", "percentage_weight": "", "duty_text": cleaned}
        )
    return _dedupe_duty_rows(rows)


def parse_major_duties(section: str | None) -> list[dict]:
    """
    Turn a major-duties section into unique rows.
    Labeled PD: one row per duty type (all bullets in duty_text).
    Unlabeled PD: one row per bullet/sentence.
    """
    if not section or not section.strip():
        return []

    section = _join_wrapped_lines(_normalize_raw_text(section))

    labeled = _parse_labeled_duties(section)
    if labeled:
        return labeled

    bullets = _parse_bullet_duties(section)
    if bullets:
        return bullets

    return _parse_sentence_duties(section)


def extract_text_pdf_data(pdf_path: str) -> dict:
    """Key fields + structured major duties from plain-text PDFs."""
    doc = fitz.open(pdf_path)
    try:
        raw_parts = []
        for page in doc:
            page_text = page.get_text()
            if page_text:
                raw_parts.append(page_text)
    finally:
        doc.close()

    raw_text = _normalize_raw_text("\n".join(raw_parts))
    cleaned = _clean_pdf_text(raw_text)

    title_match = re.search(r"^(.+?)\s+-\s+OHRM\s*$", raw_text, re.MULTILINE)
    if not title_match:
        title_match = re.search(
            r"Position Title:\s*(.+)$", raw_text, re.MULTILINE | re.IGNORECASE
        )
    if not title_match:
        title_match = re.search(r"^(.*?)\s+GS-\d+-\d+", raw_text, re.MULTILINE)

    gs_match = re.search(r"(GS-\d+-\d+)", raw_text)
    if not gs_match:
        gs_match = re.search(
            r"Series/Grade:\s*(GS-\d+-\d+)", raw_text, re.IGNORECASE
        )

    points_match = re.search(
        r"(?:TOTAL POINTS|Total)[:\s\-]+(\d+)", raw_text, re.IGNORECASE
    )

    duty_section = _extract_section_by_patterns(
        raw_text, DUTY_START_PATTERNS, DUTY_END_PATTERNS
    )
    if not duty_section:
        # Fall back to broader cleaned section from notebook-style patterns
        duty_section = _extract_section_by_patterns(
            cleaned, START_PATTERNS, END_PATTERNS
        )

    duties = parse_major_duties(duty_section)

    fields = {
        "Position Title": title_match.group(1).strip() if title_match else "Not Found",
        "GS Classification": gs_match.group(1) if gs_match else "Not Found",
        "Total Factor Points": points_match.group(1) if points_match else "Not Found",
        "Duty count": str(len(duties)),
    }

    return {"fields": fields, "duties": duties}


def process_pdf(pdf_path: str) -> dict:
    """
    Auto-detect PDF type and extract.
    - Fillable (AcroForm): return form field values
    - Plain text PD: return metadata fields + structured major duties
    """
    form_data = extract_form_data_pymupdf(pdf_path)
    if form_data:
        return {
            "pdf_type": "fillable_form",
            "field_count": len(form_data),
            "fields": form_data,
            "duties": [],
        }

    text_data = extract_text_pdf_data(pdf_path)
    return {
        "pdf_type": "text_position_description",
        "field_count": len(text_data["fields"]),
        "fields": text_data["fields"],
        "duties": text_data["duties"],
    }

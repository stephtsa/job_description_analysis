
def extract_form_data_pymupdf(pdf_path: str) -> dict:
    """AcroForm field values via PyMuPDF (one dict entry per widget)."""
    form_data = {}
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            for widget in page.widgets():
                name = widget.field_name
                if not name:
                    continue
                val = widget.field_value
                form_data[name] = "" if val is None else str(val)
    finally:
        doc.close()
    return form_data
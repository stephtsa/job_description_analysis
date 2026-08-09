"""FastAPI backend: accepts one or more PDF uploads and returns extracted fields."""

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from extractor import process_pdf

app = FastAPI(title="PDF Extractor API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


def _extract_one(filename: str, content: bytes) -> dict:
    if not filename or not filename.lower().endswith(".pdf"):
        return {
            "filename": filename or "(unnamed)",
            "ok": False,
            "error": "Please upload a PDF file.",
        }

    suffix = Path(filename).suffix or ".pdf"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        result = process_pdf(tmp_path)
        return {
            "filename": filename,
            "ok": True,
            "pdf_type": result["pdf_type"],
            "field_count": result["field_count"],
            "fields": result["fields"],
            "duties": result.get("duties") or [],
            "duty_count": len(result.get("duties") or []),
        }
    except Exception as exc:
        return {
            "filename": filename,
            "ok": False,
            "error": f"Extraction failed: {exc}",
        }
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):
    """Extract from a single PDF (kept for compatibility)."""
    result = _extract_one(file.filename or "", await file.read())
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/extract-batch")
async def extract_pdfs(files: list[UploadFile] = File(...)):
    """Extract from one or more PDFs in one request."""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one PDF.")

    results = []
    for upload in files:
        content = await upload.read()
        results.append(_extract_one(upload.filename or "", content))

    ok_count = sum(1 for r in results if r["ok"])
    return {
        "file_count": len(results),
        "success_count": ok_count,
        "results": results,
    }

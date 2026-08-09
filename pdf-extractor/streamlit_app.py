"""Streamlit frontend: upload PDFs and download major-duties CSVs."""

import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("PDF_EXTRACTOR_API_URL", "http://127.0.0.1:8000")

PDF_TYPE_LABELS = {
    "fillable_form": "Fillable form (AcroForm)",
    "text_position_description": "Text position description",
}

st.set_page_config(page_title="PDF Extractor", page_icon="📄", layout="wide")
st.title("PDF Extractor")
st.caption(
    "Upload one or more PDFs. The main download is a CSV of major duties "
    "(one row per duty). Fillable cover sheets still show form fields."
)

with st.sidebar:
    st.header("Settings")
    api_url = st.text_input("API URL", value=API_URL)
    st.markdown(
        "Start the API first (from the `pdf-extractor` folder):\n\n"
        "`uvicorn api:app --reload --port 8000`"
    )
    st.divider()
    st.markdown(
        "**Tip:** Hold Ctrl (Windows) while clicking to select multiple files "
        "in the upload dialog."
    )


def check_api(url: str) -> bool:
    try:
        response = requests.get(f"{url.rstrip('/')}/health", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


def results_to_summary_df(results: list[dict]) -> pd.DataFrame:
    rows = []
    for item in results:
        if not item.get("ok"):
            rows.append(
                {
                    "File": item.get("filename", ""),
                    "Type": "Error",
                    "Duties found": 0,
                    "Status": item.get("error", "Failed"),
                }
            )
            continue
        rows.append(
            {
                "File": item["filename"],
                "Type": PDF_TYPE_LABELS.get(item.get("pdf_type", ""), item.get("pdf_type")),
                "Duties found": item.get("duty_count", len(item.get("duties") or [])),
                "Status": "OK",
            }
        )
    return pd.DataFrame(rows)


def duties_to_df(results: list[dict], filenames: list[str] | None = None) -> pd.DataFrame:
    selected = set(filenames) if filenames is not None else None
    rows = []
    for item in results:
        if not item.get("ok"):
            continue
        if selected is not None and item["filename"] not in selected:
            continue
        meta = item.get("fields") or {}
        for duty in item.get("duties") or []:
            rows.append(
                {
                    "File": item["filename"],
                    "Position Title": meta.get("Position Title", ""),
                    "GS Classification": meta.get("GS Classification", ""),
                    "Duty type": duty.get("duty_type", ""),
                    "Percentage weight": duty.get("percentage_weight", ""),
                    "Duty text": duty.get("duty_text", ""),
                }
            )
    return pd.DataFrame(rows)


if not check_api(api_url):
    st.error(
        "Cannot reach the FastAPI backend. "
        "Open a terminal in the `pdf-extractor` folder and run:\n\n"
        "`uvicorn api:app --reload --port 8000`"
    )
    st.stop()

uploaded_files = st.file_uploader(
    "Choose one or more PDFs",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.write(f"**{len(uploaded_files)} file(s) selected.** Click the button to extract.")
    if st.button("Extract all", type="primary"):
        multipart = [
            ("files", (f.name, f.getvalue(), "application/pdf")) for f in uploaded_files
        ]
        with st.spinner(f"Extracting {len(uploaded_files)} PDF(s)..."):
            response = requests.post(
                f"{api_url.rstrip('/')}/extract-batch",
                files=multipart,
                timeout=180,
            )

        if response.status_code != 200:
            detail = response.json().get("detail", "Extraction failed.")
            st.error(detail)
        else:
            payload = response.json()
            st.session_state["last_results"] = payload["results"]
            st.success(
                f"Finished: {payload['success_count']} of {payload['file_count']} succeeded."
            )

if "last_results" in st.session_state:
    results = st.session_state["last_results"]

    st.subheader("Summary")
    st.dataframe(results_to_summary_df(results), use_container_width=True, hide_index=True)

    ok_files = [r["filename"] for r in results if r.get("ok")]
    duties_available = [
        r["filename"] for r in results if r.get("ok") and (r.get("duties") or [])
    ]

    st.subheader("Download major duties CSV")
    st.caption(
        "Select one file for an individual CSV, or multiple files for one consolidated CSV."
    )

    if not duties_available:
        st.warning(
            "No major duties were found. Fillable cover sheets show form fields below; "
            "try a Sample PD-style document for duties."
        )
    else:
        selected_for_download = st.multiselect(
            "Files to include in the duties CSV",
            options=duties_available,
            default=duties_available,
        )
        duties_df = duties_to_df(results, selected_for_download)

        if duties_df.empty:
            st.info("Select at least one file with duties to download.")
        else:
            st.dataframe(duties_df, use_container_width=True, hide_index=True)

            if len(selected_for_download) == 1:
                download_name = f"{Path(selected_for_download[0]).stem}_duties.csv"
                button_label = f"Download duties CSV ({selected_for_download[0]})"
            else:
                download_name = "consolidated_major_duties.csv"
                button_label = (
                    f"Download consolidated duties CSV ({len(selected_for_download)} files)"
                )

            st.download_button(
                label=button_label,
                data=duties_df.to_csv(index=False),
                file_name=download_name,
                mime="text/csv",
                type="primary",
                key="main_duties_download",
            )

    st.subheader("Details by file")
    for item in results:
        label = item.get("filename", "file")
        with st.expander(label, expanded=False):
            if not item.get("ok"):
                st.error(item.get("error", "Extraction failed."))
                continue

            st.write(
                f"**Type:** {PDF_TYPE_LABELS.get(item.get('pdf_type', ''), item.get('pdf_type'))}"
            )

            fields = item.get("fields") or {}
            duties = item.get("duties") or []

            if item.get("pdf_type") == "text_position_description":
                st.write(
                    f"**Title:** {fields.get('Position Title', 'Not Found')}  |  "
                    f"**GS:** {fields.get('GS Classification', 'Not Found')}  |  "
                    f"**Duties:** {len(duties)}"
                )
                if duties:
                    file_duties_df = duties_to_df([item])
                    st.dataframe(file_duties_df, use_container_width=True, hide_index=True)
                    st.download_button(
                        label=f"Download duties CSV for {item['filename']}",
                        data=file_duties_df.to_csv(index=False),
                        file_name=f"{Path(item['filename']).stem}_duties.csv",
                        mime="text/csv",
                        key=f"dl_duties_{item['filename']}",
                    )
                else:
                    st.warning("No major duties parsed from this file.")
            else:
                st.write(f"**Form fields found:** {item.get('field_count', 0)}")
                if fields:
                    field_df = pd.DataFrame(
                        [{"Field name": k, "Value": v} for k, v in fields.items()]
                    )
                    st.dataframe(field_df, use_container_width=True, hide_index=True)
                    st.download_button(
                        label=f"Download form fields CSV for {item['filename']}",
                        data=field_df.to_csv(index=False),
                        file_name=f"{Path(item['filename']).stem}_fields.csv",
                        mime="text/csv",
                        key=f"dl_fields_{item['filename']}",
                    )

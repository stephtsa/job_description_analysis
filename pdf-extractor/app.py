from flask import Flask, render_template, request, jsonify
import pdfplumber
import re   

app = Flask(__name__)

def extract_pdf_data(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"

    # Match Title (e.g., Accountant 05 or Business and Industry Assistant 05)
    title_match = re.search(r'^(.*?)\s+GS-\d+-\d+', text, re.MULTILINE)
    
    # Match GS Code (e.g., GS-0510-05 or GS-1101-05)
    gs_match = re.search(r'(GS-\d+-\d+)', text)
    
    # Match Total Points (e.g., TOTAL POINTS - 940 or Total: 880 pts)
    points_match = re.search(r'(?:TOTAL POINTS|Total)[:\s\-]+(\d+)', text, re.IGNORECASE)

    return {
        "Position Title": title_match.group(1).strip() if title_match else "Not Found",
        "GS Classification": gs_match.group(1) if gs_match else "Not Found",
        "Total Factor Points": points_match.group(1) if points_match else "Not Found",
        "Full Text Summary": text[:300] + "..."  # First 300 characters
    }

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    data = extract_pdf_data(file)
    return jsonify(data)

if __name__ == "__main__":
    app.run(debug=True)
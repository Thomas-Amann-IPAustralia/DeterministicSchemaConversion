import json
import csv
import os
import glob
import sys
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

# Configuration
JSON_DIR = 'json_output-enriched'
HTML_DIR = 'IPFR-Webpages-html'
OUTPUT_DIR = os.path.join('reports', 'validation_reports')
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'Validation_Report.csv')
SIMILARITY_THRESHOLD = 0.85

def normalize_text(text):
    """Normalize whitespace and stripping for comparison."""
    if not text:
        return ""
    return ' '.join(text.split()).lower()

def calculate_similarity(a, b):
    """Returns a ratio 0-1 of similarity between two strings."""
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()

def validate_file(json_path, html_path):
    report_rows = []
    
    # 1. Structural Integrity Check
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        report_rows.append(["Structure", "JSON Syntax", "Valid", "1.0", "PASS"])
    except json.JSONDecodeError as e:
        return [["Structure", "JSON Syntax", str(e), "0.0", "CRITICAL FAIL"]]

    # Load HTML Content
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            html_text = normalize_text(soup.get_text())
    except FileNotFoundError:
        return [["Structure", "HTML Source", "File not found", "0.0", "CRITICAL FAIL"]]

    # 2. Schema Key Checks
    required_keys = ["@context", "@type", "headline", "description"]
    for key in required_keys:
        if key in data:
            report_rows.append(["Schema", f"Key: {key}", "Present", "1.0", "PASS"])
        else:
            report_rows.append(["Schema", f"Key: {key}", "Missing", "0.0", "FAIL"])

    # 3. Semantic & Data Integrity Checks
    # Check Headline alignment
    json_headline = data.get("headline", "")
    if json_headline:
        sim_score = 0.0
        if normalize_text(json_headline) in html_text:
            sim_score = 1.0
        else:
            # Fallback to fuzzy match against title or h1
            html_title = soup.find('h1') or soup.find('title')
            if html_title:
                sim_score = calculate_similarity(json_headline, html_title.get_text())
        
        status = "PASS" if sim_score > SIMILARITY_THRESHOLD else "WARN"
        report_rows.append(["Semantic", "Headline Match", f"Score: {sim_score:.2f}", str(sim_score), status])

    # Check Description alignment
    json_desc = data.get("description", "")
    if json_desc:
        is_present = normalize_text(json_desc) in html_text
        score = 1.0 if is_present else 0.0
        status = "PASS" if score == 1.0 else "WARN"
        report_rows.append(["Semantic", "Description Presence", "Found in body" if is_present else "Not found exactly", str(score), status])

    return report_rows

def main():
    # Pre-flight check: Ensure input directories exist
    if not os.path.exists(JSON_DIR):
        print(f"CRITICAL ERROR: The directory '{JSON_DIR}' was not found.")
        sys.exit(1)

    # Ensure the output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    json_files = glob.glob(os.path.join(JSON_DIR, '*.json'))
    
    if not json_files:
        print(f"WARNING: No JSON files found in {JSON_DIR}. Check your paths.")
        
    print(f"Starting validation for {len(json_files)} files...")
    
    # Master list to hold all rows from all files
    aggregated_results = []
    
    for json_file in json_files:
        filename = os.path.basename(json_file)
        name_root = os.path.splitext(filename)[0]
        html_filename = f"{name_root}-html.html"
        html_path = os.path.join(HTML_DIR, html_filename)
        
        # Run validation
        file_results = validate_file(json_file, html_path)
        
        # Prepend the filename to every row so we know which file it belongs to
        for row in file_results:
            row.insert(0, filename)
            aggregated_results.append(row)
            
    # Write single CSV report
    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Added "File" column header
            writer.writerow(["File", "Category", "Check", "Details", "Score", "Status"])
            writer.writerows(aggregated_results)
        print(f"Validation complete. Aggregated report saved to {OUTPUT_FILE}")
    except PermissionError:
        print(f"ERROR: Could not write to {OUTPUT_FILE}. Is it open in another program?")
        sys.exit(1)

if __name__ == "__main__":
    main()

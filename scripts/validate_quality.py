import json
import csv
import os
import glob
import sys
import re
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
    # Remove non-breaking spaces and extra whitespace
    text = text.replace('\xa0', ' ')
    return ' '.join(text.split()).lower()

def calculate_similarity(a, b):
    """Returns a ratio 0-1 of similarity between two strings."""
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()

def extract_urls_from_html(soup):
    """Extracts a set of all href links from the HTML soup."""
    return {a['href'].strip() for a in soup.find_all('a', href=True)}

def extract_urls_from_json(data):
    """Recursively finds all 'url' values in the JSON."""
    urls = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k == 'url' and isinstance(v, str):
                urls.add(v.strip())
            else:
                urls.update(extract_urls_from_json(v))
    elif isinstance(data, list):
        for item in data:
            urls.update(extract_urls_from_json(item))
    return urls

def validate_file(json_path, html_path, filename):
    report_rows = []
    
    # --- LOAD FILES ---
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        report_rows.append([filename, "Structure", "JSON Syntax", "Valid", "1.0", "PASS"])
    except json.JSONDecodeError as e:
        return [[filename, "Structure", "JSON Syntax", str(e), "0.0", "CRITICAL FAIL"]]

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            html_text = normalize_text(soup.get_text())
            html_urls = extract_urls_from_html(soup)
    except FileNotFoundError:
        return [[filename, "Structure", "HTML Source", "File not found", "0.0", "CRITICAL FAIL"]]

    # --- CHECK 1: SCHEMA KEYS ---
    required_keys = ["@context", "@type", "headline", "description"]
    for key in required_keys:
        if key in data:
            report_rows.append([filename, "Schema", f"Key: {key}", "Present", "1.0", "PASS"])
        else:
            report_rows.append([filename, "Schema", f"Key: {key}", "Missing", "0.0", "FAIL"])

    # --- CHECK 2: IDENTIFIER CONSISTENCY ---
    # Extract ID from filename (e.g., "B1000" from "B1000 - Receiving...")
    filename_id_match = re.search(r'^([A-Z]\d{4})', filename)
    if filename_id_match:
        filename_id = filename_id_match.group(1)
        
        # Extract ID from JSON
        json_id = "Not Found"
        if "identifier" in data and isinstance(data["identifier"], dict):
            json_id = data["identifier"].get("value", "Not Found")
        
        if json_id == filename_id:
            report_rows.append([filename, "Data Integrity", "ID Match", f"{json_id} == {filename_id}", "1.0", "PASS"])
        else:
            report_rows.append([filename, "Data Integrity", "ID Match", f"JSON: {json_id} vs File: {filename_id}", "0.0", "FAIL"])

    # --- CHECK 3: SEMANTIC TEXT MATCHING ---
    checks = {
        "headline": data.get("headline", ""),
        "description": data.get("description", "")
    }

    for field, text in checks.items():
        if text:
            sim_score = 0.0
            if normalize_text(text) in html_text:
                sim_score = 1.0
            else:
                # Fallback: check against H1/Title for headline
                if field == "headline":
                    html_title = soup.find('h1') or soup.find('title')
                    if html_title:
                        sim_score = calculate_similarity(text, html_title.get_text())
                else:
                    # Generic fuzzy check against whole body for description
                    # (This is expensive but effective for small descriptions)
                    if calculate_similarity(text, html_text) > 0.1: # Basic sanity check
                         # If exact match failed, we assume a lower score unless we find a specific substring
                         sim_score = 0.5 # Warning level
            
            status = "PASS" if sim_score > SIMILARITY_THRESHOLD else "WARN"
            report_rows.append([filename, "Semantic", f"{field.capitalize()} Match", f"Score: {sim_score:.2f}", str(sim_score), status])

    # --- CHECK 4: FAQ / SUB-ENTITY VALIDATION ---
    # If mainEntity is a list (FAQPage), check if Questions exist in HTML
    if "mainEntity" in data and isinstance(data["mainEntity"], list):
        for entity in data["mainEntity"]:
            if entity.get("@type") == "Question":
                q_text = entity.get("name", "")
                if q_text:
                    is_found = normalize_text(q_text) in html_text
                    score = 1.0 if is_found else 0.0
                    status = "PASS" if is_found else "WARN"
                    report_rows.append([filename, "Content", "FAQ Question Found", q_text[:30]+"...", str(score), status])

    # --- CHECK 5: LINK INTEGRITY ---
    # Check if links in 'relatedLink' exist in HTML
    if "relatedLink" in data:
        json_links = [l.get('url') for l in data['relatedLink'] if 'url' in l]
        for link in json_links:
            # We check if the exact link exists, or a relative version of it
            # Simple check: is the link present in the set of HTML hrefs?
            is_found = link in html_urls
            # Try matching relative paths if exact match fails
            if not is_found and link.startswith('http'): 
                # check if a relative path exists in html that matches the end of this url
                is_found = any(link.endswith(h) for h in html_urls if h)
            
            score = 1.0 if is_found else 0.0
            status = "PASS" if is_found else "WARN"
            report_rows.append([filename, "Links", "Related Link Exists", link, str(score), status])

    return report_rows

def main():
    if not os.path.exists(JSON_DIR):
        print(f"CRITICAL ERROR: The directory '{JSON_DIR}' was not found.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    json_files = glob.glob(os.path.join(JSON_DIR, '*.json'))
    
    if not json_files:
        print(f"WARNING: No JSON files found in {JSON_DIR}.")
        
    print(f"Starting extended validation for {len(json_files)} files...")
    
    aggregated_results = []
    
    for json_file in json_files:
        filename = os.path.basename(json_file)
        name_root = os.path.splitext(filename)[0]
        html_filename = f"{name_root}-html.html"
        html_path = os.path.join(HTML_DIR, html_filename)
        
        file_results = validate_file(json_file, html_path, filename)
        aggregated_results.extend(file_results)
            
    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["File", "Category", "Check", "Details", "Score", "Status"])
            writer.writerows(aggregated_results)
        print(f"Validation complete. Aggregated report saved to {OUTPUT_FILE}")
    except PermissionError:
        print(f"ERROR: Could not write to {OUTPUT_FILE}. Is it open in another program?")
        sys.exit(1)

if __name__ == "__main__":
    main()

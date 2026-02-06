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

def check_text_quality(field_name, text, filename, report_rows):
    """
    Rule 4 & 5: Check for artifacts, unstripped HTML, and excessive whitespace.
    """
    if not text or not isinstance(text, str):
        return

    # Rule 4: Artifact Cleaning (Control Chars & HTML tags)
    # Check for non-printable control characters (excluding tab \x09 and newline \x0a)
    if re.search(r'[\x00-\x08\x0b-\x1f]', text):
        report_rows.append([filename, "Quality", "Artifacts", f"Control chars in {field_name}", "0.0", "FAIL"])
    
    # Check for leftover HTML like "span lang=" or closing tags
    if "span lang=" in text or re.search(r'</[a-z]+>', text):
        report_rows.append([filename, "Quality", "Artifacts", f"Unstripped HTML in {field_name}", "0.0", "FAIL"])

    # Rule 5: Whitespace Normalization
    # Check for 3 or more consecutive newlines (or newline + spaces)
    if re.search(r'(\n\s*){3,}', text):
        report_rows.append([filename, "Quality", "Whitespace", f"Excessive newlines in {field_name}", "0.5", "WARN"])

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
            html_raw_text = soup.get_text() # Keep raw for case sensitivity checks
            html_text = normalize_text(html_raw_text)
            html_urls = extract_urls_from_html(soup)
            
            # Extract anchors for Rule 2 (Link Preservation)
            # List of (text, href)
            html_anchors = []
            for a in soup.find_all('a', href=True):
                txt = a.get_text(strip=True)
                if txt and len(txt) > 3: # Ignore tiny links to reduce noise
                    html_anchors.append((txt, a['href'].strip()))

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
    filename_id_match = re.search(r'^([A-Z]\d{4})', filename)
    if filename_id_match:
        filename_id = filename_id_match.group(1)
        json_id = "Not Found"
        if "identifier" in data and isinstance(data["identifier"], dict):
            json_id = data["identifier"].get("value", "Not Found")
        
        if json_id == filename_id:
            report_rows.append([filename, "Data Integrity", "ID Match", f"{json_id} == {filename_id}", "1.0", "PASS"])
        else:
            report_rows.append([filename, "Data Integrity", "ID Match", f"JSON: {json_id} vs File: {filename_id}", "0.0", "FAIL"])

    # --- CHECK 3: SEMANTIC TEXT MATCHING & CASING (Rule 3) ---
    checks = {
        "headline": data.get("headline", ""),
        "description": data.get("description", "")
    }

    for field, text in checks.items():
        if text:
            # Run Quality Checks (Rule 4 & 5)
            check_text_quality(field, text, filename, report_rows)

            sim_score = 0.0
            norm_text = normalize_text(text)
            
            if norm_text in html_text:
                sim_score = 1.0
                # Rule 3: Header Casing Consistency
                # If we have a semantic match, check if exact casing exists in HTML
                # We relax this check for descriptions, but enforce for Headings/Acronyms
                if field == "headline":
                    if text not in html_raw_text:
                         report_rows.append([filename, "Quality", "Casing Consistency", f"Headline casing mismatch (HTML preferred)", "0.5", "WARN"])

            else:
                if field == "headline":
                    html_title = soup.find('h1') or soup.find('title')
                    if html_title:
                        sim_score = calculate_similarity(text, html_title.get_text())
                else:
                    if calculate_similarity(text, html_text) > 0.1: 
                         sim_score = 0.5 
            
            status = "PASS" if sim_score > SIMILARITY_THRESHOLD else "WARN"
            report_rows.append([filename, "Semantic", f"{field.capitalize()} Match", f"Score: {sim_score:.2f}", str(sim_score), status])
            
            # Rule 2: Link Contextualization (Check description field)
            # If text matches Anchor Text but URL is missing from the JSON field
            if field == "description":
                for anchor_txt, anchor_href in html_anchors:
                    if anchor_txt in text and anchor_href not in text:
                         report_rows.append([filename, "Quality", "Hyperlink Preservation", f"Link '{anchor_txt}' found but URL lost", "0.0", "FAIL"])


    # --- CHECK 4: FAQ / SUB-ENTITY VALIDATION ---
    def find_questions(node):
        found = []
        if isinstance(node, dict):
            if node.get("@type") == "Question":
                found.append(node)
            for value in node.values():
                found.extend(find_questions(value))
        elif isinstance(node, list):
            for item in node:
                found.extend(find_questions(item))
        return found

    questions = find_questions(data)

    if questions:
        for q in questions:
            q_text = q.get("name", "").strip()
            
            # Rule 4 & 5 on Question Text
            check_text_quality("FAQ Question", q_text, filename, report_rows)

            # 4a: Check if Question Text exists in HTML
            if q_text:
                norm_q = normalize_text(q_text)
                if norm_q in html_text:
                    score = 1.0
                    status = "PASS"
                    report_rows.append([filename, "Content", "FAQ Question Found", q_text[:30]+"...", str(score), status])
                else:
                    # Rule 1: Schema Type Specifics (Question Mark Hallucination)
                    # If exact match failed, check if it was because of a trailing '?'
                    if q_text.endswith('?'):
                        clean_q = q_text.rstrip('?')
                        if normalize_text(clean_q) in html_text:
                            # Found without ?, but JSON has ? -> Hallucination
                            report_rows.append([filename, "Quality", "QM Hallucination", f"HTML missing '?': {q_text}", "0.0", "FAIL"])
                        else:
                            report_rows.append([filename, "Content", "FAQ Question Found", "Not found", "0.0", "WARN"])
                    else:
                        report_rows.append([filename, "Content", "FAQ Question Found", "Not found", "0.0", "WARN"])

            # Prepare Answer Text
            answer = q.get("acceptedAnswer", {})
            ans_text = ""
            if isinstance(answer, dict):
                ans_text = answer.get("text", "")
            ans_text_clean = str(ans_text).strip()

            # Rule 4 & 5 on Answer Text
            check_text_quality("FAQ Answer", ans_text_clean, filename, report_rows)

            # Rule 2: Link Preservation (Check Answer field)
            for anchor_txt, anchor_href in html_anchors:
                # We check if the anchor text appears in the answer, but the markdown link/url is missing
                if anchor_txt in ans_text_clean and anchor_href not in ans_text_clean:
                    report_rows.append([filename, "Quality", "Hyperlink Preservation", f"Link '{anchor_txt}' lost in answer", "0.0", "FAIL"])

            # 4b: Check if Answer Text is missing
            if not ans_text_clean:
                report_rows.append([filename, "Content", "FAQ Answer Status", f"Missing answer for: {q_text[:20]}...", "0.0", "FAIL"])
            else:
                report_rows.append([filename, "Content", "FAQ Answer Status", "Answer populated", "1.0", "PASS"])

            # 4c: QUALITY CONTROL (LENGTH CHECKS)
            if len(q_text) < 12:
                report_rows.append([filename, "Quality", "Question Length", f"Too short ({len(q_text)} chars)", "0.5", "WARN"])
            if len(ans_text_clean) > 0 and len(ans_text_clean) < 20:
                report_rows.append([filename, "Quality", "Answer Length", f"Too short ({len(ans_text_clean)} chars)", "0.5", "WARN"])

    # --- CHECK 5: LINK INTEGRITY ---
    if "relatedLink" in data:
        json_links = [l.get('url') for l in data['relatedLink'] if 'url' in l]
        for link in json_links:
            is_found = link in html_urls
            if not is_found and link.startswith('http'): 
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

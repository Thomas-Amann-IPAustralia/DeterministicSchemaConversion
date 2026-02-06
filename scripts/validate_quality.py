import json
import csv
import os
import glob
import sys
import re
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

# --- CONFIGURATION (Centralized Rules) ---
CONFIG = {
    "directories": {
        "json": 'json_output-enriched',
        "html": 'IPFR-Webpages-html',
        "output": os.path.join('reports', 'validation_reports')
    },
    "thresholds": {
        "similarity": 0.85,
        "min_question_len": 12,
        "min_answer_len": 20,
        "date_match_len": 10  # YYYY-MM-DD
    },
    "weights": {
        "pass": 1.0,
        "warn": 0.5,
        "fail": 0.0
    },
    "ignore_patterns": [
        "Disclaimer", "Copyright", "feedback"
    ]
}

OUTPUT_FILE = os.path.join(CONFIG["directories"]["output"], 'Validation_Report_Extended.csv')

# --- HELPERS ---

def normalize_text(text):
    """Normalize whitespace and stripping for comparison."""
    if not text:
        return ""
    text = str(text).replace('\xa0', ' ')
    # Remove non-printable chars
    text = re.sub(r'[\x00-\x08\x0b-\x1f]', '', text)
    return ' '.join(text.split()).lower()

def calculate_similarity(a, b):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()

def get_string_diff(json_text, html_text):
    """Returns a short string describing the first difference found for the report."""
    a, b = normalize_text(json_text), normalize_text(html_text)
    
    if a in b: return "Exact match found inside content"
    
    # Check length disparity
    if abs(len(a) - len(b)) > 20 and len(a) > 50:
        return f"Length mismatch: JSON({len(a)}) vs HTML content ({len(b)})"
    
    # Find first point of difference
    matcher = SequenceMatcher(None, a, b)
    match = matcher.find_longest_match(0, len(a), 0, len(b))
    
    if match.size == 0:
        return "No common text found"
    
    # If the match isn't the whole string, show where it breaks
    if match.size < len(a):
        # Find the first mismatch index
        for i, (char_a, char_b) in enumerate(zip(a, b)):
            if char_a != char_b:
                start = max(0, i - 15)
                end_a = min(len(a), i + 15)
                end_b = min(len(b), i + 15)
                return f"...{a[start:end_a]}... VS ...{b[start:end_b]}..."
        return f"JSON text has extra suffix: ...{a[match.size:][:20]}..."
        
    return "Partial match found"

def extract_urls_from_html(soup):
    return {a['href'].strip() for a in soup.find_all('a', href=True)}

# --- VALIDATION LOGIC ---

def check_text_quality(field_name, text, filename, report_rows):
    """Rule 4 & 5: Check for artifacts and whitespace."""
    if not text or not isinstance(text, str):
        return

    # Rule 4: Artifact Cleaning
    if re.search(r'[\x00-\x08\x0b-\x1f]', text):
        report_rows.append([filename, "Quality", "Artifacts", f"Control chars in {field_name}", "0.0", "FAIL", "Found \\x00-\\x1f chars", "Sanitize text strings"])
    
    if "span lang=" in text or re.search(r'</[a-z]+>', text):
        report_rows.append([filename, "Quality", "Artifacts", f"Unstripped HTML in {field_name}", "0.0", "FAIL", "Found HTML tags", "Run HTML stripper"])

    # Rule 5: Whitespace
    if re.search(r'(\n\s*){3,}', text):
        report_rows.append([filename, "Quality", "Whitespace", f"Excessive newlines in {field_name}", "0.5", "WARN", "3+ consecutive newlines", "Replace \\n\\n\\n with \\n\\n"])

def validate_file(json_path, html_path, filename):
    report_rows = []
    
    # --- LOAD FILES ---
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        report_rows.append([filename, "Structure", "JSON Syntax", "Valid", "1.0", "PASS", "-", "-"])
    except json.JSONDecodeError as e:
        return [[filename, "Structure", "JSON Syntax", str(e), "0.0", "CRITICAL FAIL", "-", "Fix JSON formatting"]]

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            html_raw_text = soup.get_text()
            html_text = normalize_text(html_raw_text)
            html_urls = extract_urls_from_html(soup)
            
            # HTML Anchors for Link Preservation Check
            html_anchors = []
            for a in soup.find_all('a', href=True):
                txt = a.get_text(strip=True)
                if txt and len(txt) > 3:
                    html_anchors.append((txt, a['href'].strip()))
    except FileNotFoundError:
        return [[filename, "Structure", "HTML Source", "File not found", "0.0", "CRITICAL FAIL", "-", "Ensure HTML file exists"]]

    # --- CHECK 1: SCHEMA KEYS ---
    required_keys = ["@context", "@type", "headline", "description"]
    for key in required_keys:
        if key in data:
            report_rows.append([filename, "Schema", f"Key: {key}", "Present", "1.0", "PASS", "-", "-"])
        else:
            report_rows.append([filename, "Schema", f"Key: {key}", "Missing", "0.0", "FAIL", f"Missing {key}", f"Add '{key}' to JSON root"])

    # --- CHECK 2: IDENTIFIER & DATE ---
    # 2a: ID
    filename_id_match = re.search(r'^([A-Z]\d{4})', filename)
    if filename_id_match:
        filename_id = filename_id_match.group(1)
        json_id = data.get("identifier", {}).get("value", "Not Found") if isinstance(data.get("identifier"), dict) else "Not Found"
        
        if json_id == filename_id:
            report_rows.append([filename, "Data Integrity", "ID Match", f"{json_id} == {filename_id}", "1.0", "PASS", "-", "-"])
        else:
            report_rows.append([filename, "Data Integrity", "ID Match", "Mismatch", "0.0", "FAIL", f"{json_id} vs {filename_id}", "Update identifier.value"])

    # 2b: Date Consistency (New)
    json_date = data.get("dateModified", "")
    if json_date:
        if json_date in html_raw_text:
             report_rows.append([filename, "Data Integrity", "Date Verification", "Date found in HTML", "1.0", "PASS", json_date, "-"])
        else:
             report_rows.append([filename, "Data Integrity", "Date Verification", "Date missing from HTML", "0.5", "WARN", json_date, "Verify dateModified matches HTML footer/meta"])

    # --- CHECK 3: SEMANTIC TEXT MATCHING ---
    # 3a: Headline (Strict H1 Check)
    json_headline = data.get("headline", "")
    if json_headline:
        h1 = soup.find('h1')
        h1_text = h1.get_text(strip=True) if h1 else ""
        
        if normalize_text(json_headline) == normalize_text(h1_text):
            report_rows.append([filename, "Semantic", "Headline H1 Match", "Exact H1 Match", "1.0", "PASS", "-", "-"])
            # Casing check
            if json_headline != h1_text:
                 report_rows.append([filename, "Quality", "Casing", "Headline Casing", "0.5", "WARN", f"{json_headline} vs {h1_text}", "Match HTML casing"])
        else:
            diff = get_string_diff(json_headline, h1_text)
            report_rows.append([filename, "Semantic", "Headline H1 Match", "Mismatch", "0.0", "FAIL", diff, "Update JSON headline to match HTML <h1>"])

    # 3b: Description
    desc = data.get("description", "")
    if desc:
        check_text_quality("Description", desc, filename, report_rows)
        if normalize_text(desc) in html_text:
             report_rows.append([filename, "Semantic", "Description Match", "Found in Body", "1.0", "PASS", "-", "-"])
             
             # Link Preservation in Description
             for anchor_txt, anchor_href in html_anchors:
                if anchor_txt in desc and anchor_href not in desc:
                     report_rows.append([filename, "Quality", "Hyperlink Lost", "Description missing URL", "0.0", "FAIL", f"Link: {anchor_txt}", "Convert to [Text](URL)"])
        else:
             diff = get_string_diff(desc, html_raw_text)
             report_rows.append([filename, "Semantic", "Description Match", "Text Mismatch", "0.5", "WARN", diff, "Review description accuracy"])

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
            
            check_text_quality("FAQ Question", q_text, filename, report_rows)

            # 4a: Question Match
            if q_text:
                if normalize_text(q_text) in html_text:
                    report_rows.append([filename, "Content", "FAQ Question", "Found", "1.0", "PASS", "-", "-"])
                elif q_text.endswith('?') and normalize_text(q_text.rstrip('?')) in html_text:
                    report_rows.append([filename, "Quality", "QM Hallucination", "Extra '?' detected", "0.0", "FAIL", f"{q_text}", "Remove '?' from JSON name"])
                else:
                    report_rows.append([filename, "Content", "FAQ Question", "Not Found", "0.0", "WARN", q_text[:30], "Check against HTML headers"])

            # 4b: Answer Logic
            answer = q.get("acceptedAnswer", {})
            ans_text = str(answer.get("text", "")).strip() if isinstance(answer, dict) else ""
            
            check_text_quality("FAQ Answer", ans_text, filename, report_rows)

            if not ans_text:
                report_rows.append([filename, "Content", "FAQ Answer", "Missing content", "0.0", "FAIL", q_text[:20], "Populate acceptedAnswer.text"])
            else:
                # Length Checks
                if len(q_text) < CONFIG["thresholds"]["min_question_len"]:
                    report_rows.append([filename, "Quality", "Length", "Question too short", "0.5", "WARN", f"{len(q_text)} chars", "Expand question text"])
                if len(ans_text) < CONFIG["thresholds"]["min_answer_len"]:
                    report_rows.append([filename, "Quality", "Length", "Answer too short", "0.5", "WARN", f"{len(ans_text)} chars", "Expand answer text"])
                
                # Link Preservation in Answer
                for anchor_txt, anchor_href in html_anchors:
                    if anchor_txt in ans_text and anchor_href not in ans_text:
                         report_rows.append([filename, "Quality", "Hyperlink Lost", "Answer missing URL", "0.0", "FAIL", f"Link: {anchor_txt}", "Convert to [Text](URL)"])

    # --- CHECK 5: LINK INTEGRITY (Bi-directional) ---
    json_links = set()
    if "relatedLink" in data:
        for l in data['relatedLink']:
            if 'url' in l: json_links.add(l['url'])
            
    # 5a: JSON links exist in HTML
    for link in json_links:
        is_found = link in html_urls
        if not is_found and link.startswith('http'): 
            is_found = any(link.endswith(h) for h in html_urls if h)
        
        if is_found:
             report_rows.append([filename, "Links", "Link Validation", "Valid", "1.0", "PASS", "-", "-"])
        else:
             report_rows.append([filename, "Links", "Link Validation", "Broken/Missing", "0.5", "WARN", link, "Verify link exists in HTML"])

    # 5b: HTML links missing from JSON (Orphaned Links)
    # Filter out common nav links or strict ignore patterns if needed
    for html_link in html_urls:
        if html_link.startswith('http') and html_link not in json_links:
            # We assume description/answers might contain them in markdown, verifying that is hard without parsing markdown.
            # We'll just warn to check relatedLinks.
            # Simple heuristic: ignore if it looks like a resource file (.css, .js)
            if not html_link.endswith(('.css', '.js', '.png', '.ico')):
                 # Only warn if it's NOT in the description/answer text either (rough check)
                 raw_json_str = json.dumps(data)
                 if html_link not in raw_json_str:
                     report_rows.append([filename, "Links", "Orphaned Link", "HTML link not in JSON", "0.5", "WARN", html_link, "Consider adding to relatedLink"])

    return report_rows

def main():
    if not os.path.exists(CONFIG["directories"]["json"]):
        print(f"CRITICAL ERROR: Directory '{CONFIG['directories']['json']}' not found.")
        sys.exit(1)

    os.makedirs(CONFIG["directories"]["output"], exist_ok=True)
    
    json_files = glob.glob(os.path.join(CONFIG["directories"]["json"], '*.json'))
    print(f"Starting extended validation for {len(json_files)} files...")
    
    aggregated_results = []
    
    for json_file in json_files:
        filename = os.path.basename(json_file)
        name_root = os.path.splitext(filename)[0]
        html_filename = f"{name_root}-html.html"
        html_path = os.path.join(CONFIG["directories"]["html"], html_filename)
        
        aggregated_results.extend(validate_file(json_file, html_path, filename))
            
    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["File", "Category", "Check", "Details", "Score", "Status", "Context/Diff", "Suggested Action"])
            writer.writerows(aggregated_results)
        print(f"Validation complete. Report saved to {OUTPUT_FILE}")
    except PermissionError:
        print(f"ERROR: Could not write to {OUTPUT_FILE}. Close the file and try again.")
        sys.exit(1)

if __name__ == "__main__":
    main()

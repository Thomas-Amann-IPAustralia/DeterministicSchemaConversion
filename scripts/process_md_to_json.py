import os
import csv
import json
import re
import datetime
import sys

# Configuration
INPUT_DIR = 'markdown_output'  # Where your .md files live
OUTPUT_DIR = 'json_output'     # Where JSON files will go
REPORTS_DIR = 'reports'        # Where the report will be saved
CSV_PATH = '260203_IPFRMetaTable.csv'
REPORT_FILENAME = 'after_action_report.txt'

def load_metadata(csv_path):
    """Loads CSV metadata into a dictionary keyed by Canonical URL."""
    meta_dict = {}
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'canonical url' in row and row['canonical url']:
                    meta_dict[row['canonical url'].strip()] = row
    except FileNotFoundError:
        print(f"CRITICAL: CSV file not found at {csv_path}")
        sys.exit(1)
    return meta_dict

def extract_content_between_headers(text, start_header, end_header_pattern=r'^#+ '):
    """Extracts text between a specific header and the next header."""
    pattern = re.compile(rf'{re.escape(start_header)}(.*?)(?={end_header_pattern}|\Z)', re.DOTALL | re.MULTILINE)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None

def parse_markdown_file(filepath, meta_db, report_log):
    filename = os.path.basename(filepath)
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # --- Phase 1: Validation & Metadata ---
    url_match = re.search(r'PageURL:\s*"(.*?)"', content)
    if not url_match:
        report_log.append(f"[SKIP] {filename}: No 'PageURL' found in markdown header.")
        return None

    page_url = url_match.group(1).strip()
    meta_data = meta_db.get(page_url)
    
    if not meta_data:
        report_log.append(f"[SKIP] {filename}: URL '{page_url}' not found in CSV.")
        return None

    # --- Phase 2: Archetype & Structure ---
    archetype = meta_data.get('Archetype', '').strip()
    
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "headline": meta_data.get('Main Title', ''),
        "description": meta_data.get('Description', ''),
        "url": page_url,
        "identifier": {
            "@type": "PropertyValue",
            "propertyID": "UDID",
            "value": meta_data.get('UDID', '')
        },
        "inLanguage": "en-AU",
        "datePublished": datetime.date.today().isoformat(),
        "dateModified": datetime.date.today().isoformat(),
        "audience": {
            "@type": "BusinessAudience",
            "audienceType": ["Australian Small Business Owners"],
            "geographicArea": {"@type": "Country", "name": "Australia"}
        },
        "mainEntity": []
    }

    if meta_data.get('Entry Point'):
        json_ld['audience']['audienceType'].append(meta_data['Entry Point'])

    item_1 = {"@type": "Service", "provider": {"@type": "Organization", "name": "Third-Party Provider"}}
    item_2 = {"@type": "FAQPage", "mainEntity": []}
    item_3 = {"@type": "HowTo", "name": f"How to proceed with {meta_data.get('Main Title', 'Service')}", "step": []}

    include_item_3 = True

    if "Self-Help Strategy" in archetype:
        item_1["@type"] = "HowTo"
        include_item_3 = False
    elif "Government Service" in archetype:
        item_1["@type"] = "GovernmentService"
        item_1["provider"] = {"@type": "Organization", "name": "IP Australia"}
    
    # --- Phase 3: Global Extraction ---
    links = re.findall(r'\[(.*?)\]\((http.*?)\)', content)
    related_links = [url for _, url in links if "mailto:" not in url]
    if related_links:
        json_ld["relatedLink"] = list(set(related_links))

    citation_text = meta_data.get('Relevant IP right', '')
    citation = {"@type": "Legislation", "name": citation_text}
    if "Act" in citation_text:
        citation["legislationType"] = "Act"
    elif "Regulations" in citation_text:
        citation["legislationType"] = "Regulations"
    json_ld["citation"] = citation

    # --- Phase 4: Field Mapping ---
    desc_text = extract_content_between_headers(content, "What is it?")
    if desc_text:
        desc_text = desc_text.replace('**', '')
        if item_1["@type"] == "GovernmentService":
            item_1["abstract"] = desc_text
        else:
            item_1["description"] = desc_text

    cost_text = extract_content_between_headers(content, "Cost") or extract_content_between_headers(content, "Fees")
    item_1["serviceOutput"] = {} 
    if cost_text:
        item_1["serviceOutput"]["priceRange"] = cost_text.replace('\n', ' ')
        if "Free" in cost_text or "No cost" in cost_text:
            item_1["isAccessibleForFree"] = True

    time_text = extract_content_between_headers(content, "How long") or extract_content_between_headers(content, "Timeframe")
    if time_text:
        item_1["serviceOutput"]["timeRequired"] = time_text.replace('\n', ' ')

    # --- Phase 5: FAQ Generation ---
    lines = content.split('\n')
    skip_headers = ["What is it?", "How much does it cost?", "How long does it take?", "Obtain legal advice", "IP attorney"]
    
    current_question = None
    current_answer_buffer = []

    def flush_question():
        if current_question and current_answer_buffer:
            ans_text = " ".join(current_answer_buffer).strip()
            if ans_text:
                item_2["mainEntity"].append({
                    "@type": "Question",
                    "name": current_question,
                    "acceptedAnswer": {"@type": "Answer", "text": ans_text}
                })

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        is_question = False
        
        if line.endswith("?") and (line.startswith("#") or (i > 0 and not lines[i-1].strip())):
             if not any(skip in line for skip in skip_headers):
                 is_question = True
        
        if line.startswith("#") and not line.endswith("?") and not is_question:
             clean_header = line.lstrip('#').strip()
             if "RISK" in clean_header.upper() or "BENEFIT" in clean_header.upper() or "WATCH OUT" in clean_header.upper():
                 is_question = True
                 report_log.append(f"[WARN] {filename}: Converted header '{clean_header}' to FAQ.")
        
        if is_question:
            flush_question()
            current_question = line.lstrip('#').strip()
            current_answer_buffer = []
        elif current_question:
            if line.startswith("#") and not is_question:
                 flush_question()
                 current_question = None
            else:
                current_answer_buffer.append(line)

    flush_question()

    # --- Phase 6: HowTo & Instructions ---
    howto_text = extract_content_between_headers(content, "What do you need to proceed?") or \
                 extract_content_between_headers(content, "Next steps") or \
                 extract_content_between_headers(content, "How to proceed")
    
    if howto_text:
        steps = []
        for line in howto_text.split('\n'):
            line = line.strip()
            if line.startswith('*') or line.startswith('-') or (line[0:1].isdigit() and line[1] == '.'):
                step_text = re.sub(r'^[\*\-\d\.]+\s*', '', line)
                steps.append({
                    "@type": "HowToStep",
                    "name": "[INSERT-STEP-NAME]",
                    "text": step_text
                })
        item_3["step"] = steps

    json_ld["mainEntity"].append(item_1)
    json_ld["mainEntity"].append(item_2)
    if include_item_3:
        json_ld["mainEntity"].append(item_3)

    return json_ld

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    # Ensure Reports Directory Exists
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)
        
    meta_db = load_metadata(CSV_PATH)
    report_log = []
    
    if not os.path.exists(INPUT_DIR):
        print(f"Error: {INPUT_DIR} does not exist.")
        return

    for filename in os.listdir(INPUT_DIR):
        if filename.endswith(".md"):
            filepath = os.path.join(INPUT_DIR, filename)
            try:
                result = parse_markdown_file(filepath, meta_db, report_log)
                if result:
                    out_name = filename.replace('.md', '.json')
                    with open(os.path.join(OUTPUT_DIR, out_name), 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    report_log.append(f"[SUCCESS] Generated {out_name}")
            except Exception as e:
                report_log.append(f"[ERROR] Failed processing {filename}: {str(e)}")

    # Write Report to dedicated folder
    report_path = os.path.join(REPORTS_DIR, REPORT_FILENAME)
    with open(report_path, 'w') as f:
        f.write("\n".join(report_log))
    print(f"Processing complete. Check {report_path}")

if __name__ == "__main__":
    main()

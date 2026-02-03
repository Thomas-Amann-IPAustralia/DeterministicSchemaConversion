import os
import csv
import json
import re
import datetime
import sys

# Configuration
INPUT_DIR = 'IPFR-Webpages'    # Where your .md files live
OUTPUT_DIR = 'json_output'     # Where JSON files will go
REPORTS_DIR = 'reports'        # Where the report will be saved
CSV_PATH = '260203_IPFRMetaTable.csv'
REPORT_FILENAME = 'after_action_report.txt'

# --- Static Data Blocks (Boilerplate) ---
PUBLISHER_BLOCK = {
    "@type": "GovernmentOrganization",
    "name": "IP Australia",
    "url": "https://www.ipaustralia.gov.au",
    "parentOrganization": {
        "@type": "GovernmentOrganization",
        "name": "Australian Government"
    }
}

WEBSITE_BLOCK = {
    "@type": "WebSite",
    "name": "IP First Response",
    "url": "https://ipfirstresponse.ipaustralia.gov.au",
    "description": "A first port of call for businesses to easily understand complex intellectual property issues."
}

AUDIENCE_ALIASES = [
    "Startups", "Entrepreneurs", "SME", "Spinout Company", 
    "Startup", "Spinout", "Small to Medium Enterprise", "Sole Trader"
]

def load_metadata(csv_path):
    """Loads CSV metadata into a dictionary keyed by Canonical URL."""
    meta_dict = {}
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # specific key handling for the CSV provided in context
                if 'canonical url' in row and row['canonical url']:
                    meta_dict[row['canonical url'].strip()] = row
                elif 'Canonical URL' in row and row['Canonical URL']:
                    meta_dict[row['Canonical URL'].strip()] = row
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

def extract_disclaimer(content):
    """Extracts the italicized disclaimer text typically found at the top."""
    # Looks for text starting with *This IP First Response... and ending before a header
    match = re.search(r'^\*(This IP First Response.*?)(?=\n#|\n\*)', content, re.DOTALL | re.MULTILINE)
    if match:
        # Clean up markdown links inside the disclaimer if necessary, or keep them text
        clean_text = match.group(1).replace('\n', ' ').strip()
        # Remove trailing asterisk if captured
        if clean_text.endswith('*'):
            clean_text = clean_text[:-1]
        return clean_text
    return "This IP First Response website has been designed to help IP rights holders navigate IP infringement."

def parse_markdown_file(filepath, meta_db, report_log):
    filename = os.path.basename(filepath)
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # --- Phase 1: Validation & Metadata ---
    url_match = re.search(r'PageURL:\s*"(.*?)"', content)
    if not url_match:
        # Fallback: Try without quotes
        url_match = re.search(r'PageURL:\s*(http.*)', content)
        
    if not url_match:
        report_log.append(f"[SKIP] {filename}: No 'PageURL' found in markdown header.")
        return None

    # Cleaning URL
    raw_url_string = url_match.group(1).strip()
    if '](' in raw_url_string:
        page_url = raw_url_string.split('](')[1].rstrip(')')
    else:
        page_url = raw_url_string

    meta_data = meta_db.get(page_url)
    
    if not meta_data:
        report_log.append(f"[SKIP] {filename}: URL '{page_url}' not found in CSV keys.")
        return None

    # --- Phase 2: Archetype & Structure Setup ---
    archetype = meta_data.get('Archetype', '').strip()
    main_title = meta_data.get('Main Title', '')
    
    # Try to extract the H2 (Entity Name) from markdown to create a better headline
    # e.g., ## ASBFEO -> ASBFEO
    h2_match = re.search(r'^##\s+(.*?)$', content, re.MULTILINE)
    entity_name = h2_match.group(1).strip() if h2_match else ""

    if entity_name and entity_name not in main_title:
        headline = f"{entity_name} – {main_title}"
        alt_headline = main_title
    else:
        headline = main_title
        alt_headline = None

    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "headline": headline,
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
            "audienceType": "Australian Small Business Owners", # Changed from list to string to match ideal
            "alternateName": AUDIENCE_ALIASES,
            "geographicArea": {
                "@type": "Country",
                "name": "Australia"
            }
        },
        "publisher": PUBLISHER_BLOCK,
        "isPartOf": WEBSITE_BLOCK,
        "mainEntity": []
    }

    if alt_headline:
        json_ld["alternativeHeadline"] = alt_headline

    # Usage Info / Disclaimer
    disclaimer_text = extract_disclaimer(content)
    json_ld["usageInfo"] = {
        "@type": "CreativeWork",
        "name": "Disclaimer and Feedback Policy",
        "text": disclaimer_text,
        "url": "mailto:IPFirstResponse@IPAustralia.gov.au?subject=Feedback on IP First Response"
    }

    # About (IP Right)
    # If metadata has 'Relevant IP right', use it
    ip_right = meta_data.get('Relevant IP right', 'Intellectual Property')
    json_ld["about"] = {
        "@type": "Thing",
        "name": ip_right,
        # "sameAs": "https://www.wikidata.org/..." # Add logic if you have wikidata links
    }

    # Citations (Legislation)
    # Transforming single CSV entry into List structure
    citation_text = meta_data.get('Relevant IP right', '')
    # Logic: If specific acts are mentioned in metadata, split them. 
    # For now, we create a list structure to match the ideal schema.
    json_ld["citation"] = []
    
    # If we have specific known acts in the metadata or context, we would add them here.
    # Placeholder logic for structure:
    if "Trade Mark" in citation_text or "Trade Mark" in main_title:
         json_ld["citation"].append({
            "@type": "Legislation",
            "name": "Trade Marks Act 1995",
            "legislationType": "Act"
         })
    elif citation_text:
         json_ld["citation"].append({
            "@type": "Legislation",
            "name": citation_text,
            "legislationType": "Legislation"
         })


    # --- Phase 3: Main Entity Construction ---
    
    # ITEM 1: SERVICE / PROVIDER
    item_1 = {
        "@id": "#the-service", # Critical for linking
        "@type": "Service", 
        "name": headline,
        "description": meta_data.get('Description', ''),
        "areaServed": {
            "@type": "Country",
            "name": "Australia"
        }
    }

    # Logic to switch types based on Archetype
    if "Government Service" in archetype or "Government" in archetype:
        item_1["@type"] = "GovernmentService"
        item_1["serviceType"] = main_title
        item_1["serviceOperator"] = {
            "@type": "GovernmentOrganization",
            "name": entity_name if entity_name else "IP Australia",
            "alternateName": entity_name if entity_name else "IPA"
        }
    else:
        # Standard Service
        item_1["provider"] = {
            "@type": "Organization", 
            "name": entity_name if entity_name else "Third-Party Provider"
        }

    # Extract Content for Description overrides
    desc_text = extract_content_between_headers(content, "What is it?")
    if desc_text:
        desc_text = desc_text.replace('**', '')
        item_1["description"] = desc_text

    # Service Output (Costs/Time)
    cost_text = extract_content_between_headers(content, "What might the costs be?") or \
                extract_content_between_headers(content, "Cost")
    if not cost_text:
         cost_text = extract_content_between_headers(content, "What might the cost be?")

    # Extract Time
    time_text = extract_content_between_headers(content, "How much time might be involved?") or \
                extract_content_between_headers(content, "Timeframe")

    # While FAQ handles the text, Service needs structured data if possible. 
    # Keeping simple for now as per Ideal JSON which relies heavily on FAQ for text.


    # ITEM 2: FAQ PAGE
    item_2 = {
        "@type": "FAQPage", 
        "about": { "@id": "#the-service" },
        "mainEntity": []
    }

    # ITEM 3: HOW TO
    item_3 = {
        "@type": "HowTo", 
        "name": f"How to proceed with {headline}", 
        "about": { "@id": "#the-service" },
        "step": []
    }

    include_item_3 = True
    if "Self-Help Strategy" in archetype:
        # If self-help, the main entity acts more like a HowTo
        item_1["@type"] = "HowTo"
        include_item_3 = False # Or merge logic


    # --- Phase 4: Links Extraction ---
    links = re.findall(r'\[(.*?)\]\((http.*?)\)', content)
    related_links = [url for _, url in links if "mailto:" not in url]
    if related_links:
        json_ld["relatedLink"] = list(set(related_links))


    # --- Phase 5: FAQ Processing ---
    # Improved parser to capture multi-line answers and list items
    lines = content.split('\n')
    skip_headers = ["What is it?", "How much does it cost?", "How long does it take?", "See also", "Want to give us feedback?"]
    
    current_question = None
    current_answer_lines = []

    def flush_question():
        if current_question and current_answer_lines:
            # Join lines. If they are list items (*), preserve formatting slightly or join with spaces
            full_ans = "\n".join(current_answer_lines).strip()
            # Basic cleanup: remove bolding from entire answer if weird
            if full_ans:
                item_2["mainEntity"].append({
                    "@type": "Question",
                    "name": current_question,
                    "acceptedAnswer": {"@type": "Answer", "text": full_ans}
                })

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # Detect Question Headers
        is_question = False
        if line.startswith("#"):
            header_text = line.lstrip('#').strip()
            # If it ends with ? it's definitely a question
            if header_text.endswith("?"):
                is_question = True
            # Allow list-like questions or specific keywords
            elif any(k in header_text.lower() for k in ["risk", "benefit", "outcome", "involved", "used"]):
                is_question = True
            
            # Filter out excluded headers
            if any(skip.lower() in header_text.lower() for skip in skip_headers):
                is_question = False

            if is_question:
                flush_question()
                current_question = header_text
                current_answer_lines = []
                continue
            elif current_question:
                # We hit a header that isn't a question, stop capturing previous answer
                flush_question()
                current_question = None
        
        # Capture Answer Text
        if current_question:
            current_answer_lines.append(line)

    flush_question() # Flush last buffer

    # --- Phase 6: HowTo Steps ---
    howto_text = extract_content_between_headers(content, "What do you need to proceed?") or \
                 extract_content_between_headers(content, "Next steps")
    
    if howto_text:
        # Split by bullet points or newlines
        raw_steps = re.split(r'\n(?=[\*\-])', howto_text)
        for step in raw_steps:
            clean_step = re.sub(r'^[\*\-\d\.]+\s*', '', step.strip())
            if clean_step:
                item_3["step"].append({
                    "@type": "HowToStep",
                    "name": clean_step.split('.')[0] if '.' in clean_step else "Step",
                    "text": clean_step
                })

    # Assemble Main Entity
    json_ld["mainEntity"].append(item_1)
    json_ld["mainEntity"].append(item_2)
    if include_item_3 and item_3["step"]:
        json_ld["mainEntity"].append(item_3)

    return json_ld

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
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
                # print(e) # Uncomment for debug

    report_path = os.path.join(REPORTS_DIR, REPORT_FILENAME)
    with open(report_path, 'w') as f:
        f.write("\n".join(report_log))
    print(f"Processing complete. Check {report_path}")

if __name__ == "__main__":
    main()

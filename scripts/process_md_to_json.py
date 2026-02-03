import os
import csv
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
# Check if 'IPFR-Webpages' exists, otherwise default to current directory '.'
INPUT_DIR = 'IPFR-Webpages' if os.path.exists('IPFR-Webpages') else '.'
OUTPUT_DIR = 'json_output'
CSV_FILE = '260203_IPFRMetaTable.csv'

# --- STATIC RICH DATA & LOOKUPS ---
LEGISLATION_DB = {
    "Trade Marks Act 1995": "https://www.legislation.gov.au/C2004A04969/latest/versions",
    "Trade Marks Regulations 1995": "https://www.legislation.gov.au/F1996B00084/latest/versions",
    "Patents Act 1990": "https://www.legislation.gov.au/C2004A04014/latest/versions",
    "Patents Regulations 1991": "https://www.legislation.gov.au/F1996B02697/latest/versions",
    "Designs Act 2003": "https://www.legislation.gov.au/C2004A01232/latest/versions",
    "Designs Regulations 2004": "https://www.legislation.gov.au/F2004B00136/latest/versions",
    "Copyright Act 1968": "https://www.legislation.gov.au/C1968A00063/latest/text",
    "Copyright Regulations 2017": "https://www.legislation.gov.au/F2017L01649/latest/text",
    "Customs Act 1901": "https://www.legislation.gov.au/C1901A00006/latest/text",
    "Customs Regulation 2015": "https://www.legislation.gov.au/F2015L00373/latest/text",
    "Plant Breeder's Rights Act 1994": "https://www.legislation.gov.au/C2004A04838/latest/versions"
}

AUDIENCE_BLOCK = {
    "@type": "BusinessAudience",
    "audienceType": "Australian Small Business Owners",
    "alternateName": [
        "Startups", "Entrepreneurs", "SME", "Spinout Company", 
        "Startup", "Spinout", "Small to Medium Enterprise", "Sole Trader"
    ],
    "geographicArea": {"@type": "Country", "name": "Australia"}
}

PUBLISHER_BLOCK = {
    "@type": "GovernmentOrganization",
    "name": "IP Australia",
    "url": "https://www.ipaustralia.gov.au",
    "parentOrganization": {"@type": "GovernmentOrganization", "name": "Australian Government"}
}

USAGE_INFO_BLOCK = {
    "@type": "CreativeWork",
    "name": "Disclaimer and Feedback Policy",
    "text": "This IP First Response website has been designed to help IP rights holders navigate IP infringement and enforcement by making it visible, accessible, and to provide information about the factors involved in pursuing different options. It does not provide legal, business or other professional advice, and none of the content should be regarded as recommending a specific course of action. We welcome any feedback via our IP First Response feedback form and by emailing us.",
    "url": "mailto:IPFirstResponse@IPAustralia.gov.au?subject=Feedback on IP First Response"
}

IP_TOPIC_MAP = {
    "Intellectual Property Right": "https://www.wikidata.org/wiki/Q108855835",
    "Trade Mark": "https://www.wikidata.org/wiki/Q165196",
    "Patent": "https://www.wikidata.org/wiki/Q253623",
    "Design": "https://www.wikidata.org/wiki/Q1240325",
    "Copyright": "https://www.wikidata.org/wiki/Q12978"
}

def load_csv_metadata(csv_path):
    """Loads CSV metadata. Returns a list of rows to allow flexible searching."""
    rows = []
    if not os.path.exists(csv_path):
        print(f"CRITICAL WARNING: CSV file '{csv_path}' not found in {os.getcwd()}")
        return rows
        
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            print(f"Loaded {len(rows)} rows from CSV.")
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return rows

def find_metadata_for_file(filename, csv_rows):
    """
    Tries to find the CSV row matching the filename.
    1. Checks if UDID (Dxxxx) is in the filename.
    2. Checks if the exact filename is in a 'Filename' column.
    3. Checks if 'Main Title' vaguely matches the filename.
    """
    # Strategy 1: UDID in filename
    udid_match = re.search(r'(D\d{4})', filename)
    if udid_match:
        udid = udid_match.group(1)
        for row in csv_rows:
            if row.get('UDID') == udid:
                return row, "Matched by UDID"

    # Strategy 2: Filename Match (if CSV has a filename column)
    for row in csv_rows:
        # Check commonly used column names for filenames
        csv_fname = row.get('Filename') or row.get('File Name') or row.get('file_name')
        if csv_fname and csv_fname.strip() == filename:
            return row, "Matched by Filename Column"

    # Strategy 3: Fallback - If only 1 row exists, assume it's for this file (Testing mode)
    if len(csv_rows) == 1:
         return csv_rows[0], "Single row fallback"

    return None, "No match found"

def build_citation_list(csv_legislation_str):
    if not csv_legislation_str:
        return []
    citations = []
    raw_items = re.split(r'[;|\n]', csv_legislation_str)
    for item in raw_items:
        clean_name = item.strip()
        if not clean_name: continue
        url = LEGISLATION_DB.get(clean_name)
        leg_type = "Legislative Instrument" if "Regulation" in clean_name else "Act"
        citation_obj = {"@type": "Legislation", "name": clean_name, "legislationType": leg_type}
        if url: citation_obj["url"] = url
        citations.append(citation_obj)
    return citations

def parse_markdown_content(md_text):
    faq_matches = re.findall(r'### (.*?)\n(.*?)(?=\n###|\Z)', md_text, re.DOTALL)
    faqs = []
    for q, a in faq_matches:
        q_text = q.strip()
        if "?" in q_text:
            faqs.append({
                "@type": "Question",
                "name": q_text,
                "acceptedAnswer": {"@type": "Answer", "text": a.strip()}
            })

    how_to_steps = []
    if "proceed" in md_text.lower():
        section_match = re.search(r'proceed\?*\n(.*?)(?=\n###|\Z)', md_text, re.DOTALL | re.IGNORECASE)
        if section_match:
            bullets = re.findall(r'\* (.*)', section_match.group(1))
            for step_text in bullets:
                how_to_steps.append({
                    "@type": "HowToStep",
                    "name": step_text.strip()[:100],
                    "text": step_text.strip()
                })
    return faqs, how_to_steps

def process_file(filepath, filename, metadata_row):
    with open(filepath, 'r', encoding='utf-8') as f:
        md_content = f.read()

    faqs, how_to_steps = parse_markdown_content(md_content)
    citations = build_citation_list(metadata_row.get('Legislation', ''))
    
    udid = metadata_row.get('UDID', 'Dxxxx')
    title = metadata_row.get('Main Title', filename.replace('.md', '').replace('_', ' '))
    desc = metadata_row.get('Description', '')
    provider = metadata_row.get('Provider', 'Australian Government')
    date_val = metadata_row.get('Date', datetime.now().strftime("%Y-%m-%d"))
    topic_name = metadata_row.get('Relevant IP right', 'Intellectual Property Right')
    
    about_obj = {"@type": "Thing", "name": topic_name}
    if topic_name in IP_TOPIC_MAP:
        about_obj["sameAs"] = IP_TOPIC_MAP[topic_name]

    main_entity = {
        "@id": "#the-service",
        "@type": "GovernmentService",
        "name": title,
        "description": desc,
        "serviceType": metadata_row.get('Service Type', 'Dispute Resolution'),
        "areaServed": {"@type": "Country", "name": "Australia"},
        "serviceOperator": {"@type": "GovernmentOrganization", "name": provider}
    }

    entities = [main_entity]
    if faqs:
        entities.append({"@type": "FAQPage", "about": {"@id": "#the-service"}, "mainEntity": faqs})
    if how_to_steps:
        entities.append({"@type": "HowTo", "name": f"How to proceed with {title}", "about": {"@id": "#the-service"}, "step": how_to_steps})

    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "headline": title,
        "alternativeHeadline": title,
        "description": desc,
        "url": metadata_row.get('canonical url', f"https://ipfirstresponse.ipaustralia.gov.au/options/{udid}"),
        "identifier": {"@type": "PropertyValue", "propertyID": "UDID", "value": udid},
        "inLanguage": "en-AU",
        "datePublished": date_val,
        "dateModified": date_val,
        "audience": AUDIENCE_BLOCK,
        "usageInfo": USAGE_INFO_BLOCK,
        "about": about_obj,
        "citation": citations,
        "publisher": PUBLISHER_BLOCK,
        "isPartOf": {
            "@type": "WebSite",
            "name": "IP First Response",
            "url": "https://ipfirstresponse.ipaustralia.gov.au",
            "description": "A first port of call for businesses to easily understand complex intellectual property issues."
        },
        "mainEntity": entities
    }
    
    if metadata_row.get('Related Links'):
        links = [l.strip() for l in metadata_row['Related Links'].split(';') if l.strip()]
        if links: json_ld["relatedLink"] = links

    return

import csv
import json
import os
import re
import sys
from bs4 import BeautifulSoup
import markdown

# --- CONFIGURATION ---
CSV_PATH = 'metatable-Content.csv'
MD_DIR = 'IPFR-Webpages'
HTML_DIR = 'IPFR-Webpages-html'
OUTPUT_DIR = 'json_output'

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- STATIC DEFINITIONS ---

IP_AUSTRALIA_NODE = {
    "@id": "https://www.ipaustralia.gov.au/#organization",
    "@type": "GovernmentOrganization",
    "name": "IP Australia",
    "url": "https://www.ipaustralia.gov.au",
    "sameAs": "https://www.wikidata.org/wiki/Q5973154",
    "knowsAbout": [
        "Intellectual Property", "Patents", "Trade Marks", 
        "Design Rights", "Plant Breeder's Rights", "Copyright", 
        "Dispute Resolution"
    ],
    "contactPoint": {
        "@type": "ContactPoint",
        "contactType": "Website content owner",
        "email": "IPFirstResponse@IPAustralia.gov.au",
        "description": "Feedback and enquiries regarding IP First Response"
    },
    "parentOrganization": {
        "@type": "GovernmentOrganization",
        "name": "Australian Government"
    }
}

USAGE_INFO_NODE = {
    "@type": "CreativeWork",
    "name": "Disclaimer and Feedback Policy",
    "text": "This IP First Response website has been designed to help IP rights holders navigate IP infringement and enforcement by making it visible, accessible, and to provide information about the factors involved in pursuing different options. It does not provide legal, business or other professional advice, and none of the content should be regarded as recommending a specific course of action. We welcome any feedback via our IP First Response feedback form and by emailing us.",
    "url": "mailto:IPFirstResponse@IPAustralia.gov.au?subject=Feedback on IP First Response"
}

# --- FILE INDEXING SYSTEM ---
# We preload all filenames to handle case-sensitivity and naming variations.

MD_FILES_INDEX = {}
HTML_FILES_INDEX = {}

def build_file_indices():
    """Scans directories and builds a lowercase map for robust lookup."""
    print(f"Indexing {MD_DIR}...")
    if os.path.exists(MD_DIR):
        for f in os.listdir(MD_DIR):
            MD_FILES_INDEX[f.lower()] = f
        print(f"  > Indexed {len(MD_FILES_INDEX)} Markdown files.")
    else:
        print(f"  > CRITICAL WARNING: Directory {MD_DIR} does not exist.")

    if os.path.exists(HTML_DIR):
        for f in os.listdir(HTML_DIR):
            HTML_FILES_INDEX[f.lower()] = f

def find_files_robust(udid, canonical_url):
    """
    Finds files by scanning the index for UDID or Slug matches.
    Case-insensitive.
    """
    # 1. Define Search Keys
    udid_key = udid.lower() if udid else "xxxxx"
    
    slug = ""
    if canonical_url and '/' in canonical_url:
        slug = canonical_url.rstrip('/').split('/')[-1].lower()
    
    match_md = None

    # 2. Search Strategy
    # Priority A: Exact Filename Match (e.g., "b1000.md")
    if f"{udid_key}.md" in MD_FILES_INDEX:
        match_md = MD_FILES_INDEX[f"{udid_key}.md"]
    elif f"{slug}.md" in MD_FILES_INDEX:
        match_md = MD_FILES_INDEX[f"{slug}.md"]
    
    # Priority B: Contains UDID (e.g., "B1000_Title.md")
    if not match_md:
        for lower_name, real_name in MD_FILES_INDEX.items():
            if udid_key in lower_name:
                match_md = real_name
                break
    
    # Priority C: Contains Slug
    if not match_md and slug:
        for lower_name, real_name in MD_FILES_INDEX.items():
            if slug in lower_name:
                match_md = real_name
                break

    # 3. Resolve HTML Pair
    path_md = None
    path_html = None

    if match_md:
        path_md = os.path.join(MD_DIR, match_md)
        # Try to find corresponding HTML (same basename)
        base_name = os.path.splitext(match_md)[0]
        html_candidate = f"{base_name}.html"
        
        if html_candidate.lower() in HTML_FILES_INDEX:
            real_html_name = HTML_FILES_INDEX[html_candidate.lower()]
            path_html = os.path.join(HTML_DIR, real_html_name)
    
    return path_md, path_html

# --- HELPER FUNCTIONS ---

def clean_key(key):
    return key.replace('\ufeff', '').strip()

def load_metatable(csv_path):
    data = []
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [clean_key(k) for k in reader.fieldnames]
            for row in reader:
                data.append(row)
    except Exception as e:
        print(f"Error loading CSV: {e}")
    return data

def extract_faqs_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    faqs = []
    candidates = soup.find_all(['h2', 'h3', 'strong'])
    
    for tag in candidates:
        text = tag.get_text().strip()
        if text.endswith('?'):
            answer_parts = []
            curr = tag.find_next_sibling()
            while curr and curr.name not in ['h2', 'h3', 'h1']:
                answer_parts.append(curr.get_text().strip())
                curr = curr.find_next_sibling()
            
            answer_text = " ".join(answer_parts).strip()
            if answer_text:
                faqs.append({
                    "@type": "Question",
                    "name": text,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": answer_text
                    }
                })
    return faqs

def extract_content_body(md_content):
    lines = md_content.split('\n')
    body_lines = []
    capturing = False
    for line in lines:
        if "What is it?" in line:
            capturing = True
            continue
        if capturing:
            body_lines.append(line)
            
    if not body_lines and len(lines) > 2:
        return "\n".join(lines[2:])
    return "\n".join(body_lines).strip()

def determine_archetype_logic(archetype_raw):
    arch = archetype_raw.lower()
    if "self-help" in arch:
        return ["Article", "HowTo"], True, False
    elif "government service" in arch:
        return "GovernmentService", False, True
    elif "commercial" in arch or "non-government" in arch:
        return "Service", False, False
    else:
        return "Service", False, False

# --- MAIN GENERATOR ---

def process_file(row):
    udid = row.get('UDID')
    title = row.get('Main-title')
    canonical_url = row.get('Canonical-url')
    description = row.get('Description')
    entry_point = row.get('Entry-point', '').strip()
    provider_name = row.get('Provider', 'IP Australia')
    archetype_raw = row.get('Archectype', 'Service').strip()
    
    # 1. Robust File Finding
    md_path, html_path = find_files_robust(udid, canonical_url)
    
    md_content = ""
    html_content = ""

    # 2. Content Extraction (With Failover)
    if md_path:
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
    else:
        print(f"Skipping {udid}: MD file not found in {MD_DIR} (Slug: {canonical_url.split('/')[-1] if canonical_url else 'None'})")
        return # Cannot proceed without at least MD or HTML

    if html_path:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

    # Determine Logic
    schema_type, is_self_help, is_gov_service = determine_archetype_logic(archetype_raw)
    
    faqs = extract_faqs_from_html(html_content) if html_content else []
    article_body = extract_content_body(md_content) if is_self_help else None

    # --- BUILD GRAPH ---
    graph = []

    webpage_node = {
        "@type": "WebPage",
        "@id": f"{canonical_url}#webpage",
        "headline": title,
        "alternativeHeadline": row.get('Overtitle'),
        "description": description,
        "url": canonical_url,
        "identifier": {
            "@type": "PropertyValue",
            "propertyID": "UDID",
            "value": udid
        },
        "inLanguage": "en-AU",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "copyrightYear": "2026",
        "copyrightHolder": {"@id": "https://www.ipaustralia.gov.au/#organization"},
        "datePublished": row.get('Publication-date'),
        "dateModified": row.get('Last-updated'),
        "usageInfo": USAGE_INFO_NODE,
        "publisher": {"@id": "https://www.ipaustralia.gov.au/#organization"},
        "isPartOf": {
            "@type": "WebSite",
            "name": "IP First Response",
            "url": "https://ipfirstresponse.ipaustralia.gov.au",
            "description": "A first port of call for businesses to easily understand complex intellectual property issues."
        },
        "audience": {
            "@type": "BusinessAudience",
            "audienceType": f"Australian Small Business Owners - {entry_point}",
            "alternateName": ["Startups", "Entrepreneurs", "SME", "Sole Trader"],
            "geographicArea": {"@type": "Country", "name": "Australia"}
        },
        "mainEntity": {"@id": "#the-service"}
    }

    if not is_self_help and faqs:
        webpage_node["hasPart"] = [{"@id": "#faq"}]

    graph.append(webpage_node)

    service_node = {
        "@id": "#the-service",
        "@type": schema_type,
        "name": title,
        "description": description,
        "about": {"@type": "Thing", "name": row.get('Relevant-ip-right')}
    }

    if is_gov_service:
        prov_type = "GovernmentOrganization"
    elif "self-help" in provider_name.lower():
        prov_type = "Person"
    else:
        prov_type = "Organization"

    if "IP Australia" in provider_name:
        service_node["provider"] = {"@id": "https://www.ipaustralia.gov.au/#organization"}
    else:
        service_node["provider"] = {"@type": prov_type, "name": provider_name}

    if is_self_help:
        service_node["articleBody"] = article_body
        service_node["step"] = "xXx_PLACEHOLDER_xXx" 
    else:
        service_node["areaServed"] = {"@type": "Country", "name": "Australia"}

    graph.append(service_node)

    if faqs:
        faq_node = {
            "@id": "#faq",
            "@type": "FAQPage",
            "mainEntity": faqs
        }
        graph.append(faq_node)

    graph.append(IP_AUSTRALIA_NODE)

    final_json = {
        "@context": "https://schema.org",
        "@graph": graph
    }

    out_filename = f"{udid}.json"
    with open(os.path.join(OUTPUT_DIR, out_filename), 'w', encoding='utf-8') as f:
        json.dump(final_json, f, indent=2)

# --- EXECUTION ---

if __name__ == "__main__":
    # 1. Build Index
    build_file_indices()
    
    # 2. Process
    print("Loading Metadata...")
    rows = load_metatable(CSV_PATH)
    print(f"Found {len(rows)} entries in CSV.")
    
    processed_count = 0
    for row in rows:
        if row.get('UDID'): 
            process_file(row)
            processed_count += 1
            
    print(f"Processing Complete. Attempted: {processed_count}")

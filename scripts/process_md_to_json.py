import csv
import json
import os
import re
import difflib
from datetime import datetime
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

# --- HELPER FUNCTIONS ---

def clean_key(key):
    """Normalize CSV headers (remove BOM, strip spaces)."""
    return key.replace('\ufeff', '').strip()

def load_metatable(csv_path):
    """Loads the CSV into a list of dictionaries with normalized keys."""
    data = []
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # Normalize headers
            reader.fieldnames = [clean_key(k) for k in reader.fieldnames]
            for row in reader:
                data.append(row)
    except Exception as e:
        print(f"Error loading CSV: {e}")
    return data

def find_files(udid, canonical_url):
    """
    Locates MD and HTML files based on UDID or URL slug.
    Returns (md_path, html_path) or (None, None).
    """
    # 1. Try finding by UDID (e.g., B1005.md)
    md_path = os.path.join(MD_DIR, f"{udid}.md")
    html_path = os.path.join(HTML_DIR, f"{udid}.html")

    if os.path.exists(md_path):
        return md_path, html_path

    # 2. Fallback: Try finding by URL slug
    slug = canonical_url.rstrip('/').split('/')[-1]
    md_path_slug = os.path.join(MD_DIR, f"{slug}.md")
    html_path_slug = os.path.join(HTML_DIR, f"{slug}.html")

    if os.path.exists(md_path_slug):
        return md_path_slug, html_path_slug

    return None, None

def extract_faqs_from_html(html_content):
    """
    Parses HTML to find Questions and Answers.
    Heuristic: Looks for headers ending in '?' and content immediately following.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    faqs = []
    
    # Find all headers (h2, h3, strong) that might be questions
    candidates = soup.find_all(['h2', 'h3', 'strong'])
    
    for tag in candidates:
        text = tag.get_text().strip()
        if text.endswith('?'):
            # It's likely a question. Find the answer (next sibling)
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
    """
    Extracts the main body content for Articles.
    Heuristic: Content after 'What is it?' or first header.
    """
    lines = md_content.split('\n')
    body_lines = []
    capturing = False
    
    for line in lines:
        if "What is it?" in line:
            capturing = True
            continue
        if capturing:
            body_lines.append(line)
            
    # Fallback: if 'What is it?' not found, use everything after title
    if not body_lines and len(lines) > 2:
        return "\n".join(lines[2:])
        
    return "\n".join(body_lines).strip()

def determine_archetype_logic(archetype_raw):
    """
    Maps CSV Archetype to Schema Types and Logic Flags.
    Returns (schema_type, is_self_help, is_gov_service)
    """
    arch = archetype_raw.lower()
    
    if "self-help" in arch:
        return ["Article", "HowTo"], True, False
    elif "government service" in arch:
        return "GovernmentService", False, True
    elif "commercial" in arch or "non-government" in arch:
        return "Service", False, False
    else:
        return "Service", False, False # Default

# --- MAIN GENERATOR ---

def process_file(row):
    udid = row.get('UDID')
    title = row.get('Main-title')
    canonical_url = row.get('Canonical-url')
    description = row.get('Description')
    entry_point = row.get('Entry-point', '').strip()
    provider_name = row.get('Provider', 'IP Australia')
    archetype_raw = row.get('Archectype', 'Service').strip() # Note CSV typo 'Archectype'
    
    # Locate files
    md_path, html_path = find_files(udid, canonical_url)
    
    if not md_path:
        print(f"Skipping {udid}: Source files not found.")
        return

    # Read Content
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    html_content = ""
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

    # Determine Logic
    schema_type, is_self_help, is_gov_service = determine_archetype_logic(archetype_raw)
    
    # Extract Sub-Components
    faqs = extract_faqs_from_html(html_content)
    article_body = extract_content_body(md_content) if is_self_help else None

    # --- BUILD GRAPH ---
    graph = []

    # NODE 1: WebPage
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
        # Audience: Dynamic construction
        "audience": {
            "@type": "BusinessAudience",
            "audienceType": f"Australian Small Business Owners - {entry_point}",
            "alternateName": [
                "Startups", "Entrepreneurs", "SME", "Startup", 
                "Small to Medium Enterprise", "Sole Trader"
            ],
            "geographicArea": {
                "@type": "Country",
                "name": "Australia"
            }
        },
        "mainEntity": {"@id": "#the-service"}
    }

    # Split Personality Logic:
    # If it is NOT self-help (i.e., it's a Service), the FAQ is part of the page.
    if not is_self_help and faqs:
        webpage_node["hasPart"] = [{"@id": "#faq"}]

    graph.append(webpage_node)

    # NODE 2: The Service / Article
    service_node = {
        "@id": "#the-service",
        "@type": schema_type,
        "name": title,
        "description": description,
        "about": {
            "@type": "Thing",
            "name": row.get('Relevant-ip-right')
        }
    }

    # Provider Logic
    if is_gov_service:
        prov_type = "GovernmentOrganization"
    elif "self-help" in provider_name.lower():
        prov_type = "Person"
    else:
        prov_type = "Organization"

    # For Self-Help, we might say the provider is the user, but usually 
    # we link to IP Australia as the publisher. 
    # Logic from requirements: Use CSV provider name.
    
    # Linking provider via ID if it's IP Australia, else inline
    if "IP Australia" in provider_name:
        service_node["provider"] = {"@id": "https://www.ipaustralia.gov.au/#organization"}
    else:
        service_node["provider"] = {
            "@type": prov_type,
            "name": provider_name
        }

    # Conditional Fields
    if is_self_help:
        service_node["articleBody"] = article_body
        # Placeholder for HowToSteps (to be enriched by AI script later)
        service_node["step"] = "xXx_PLACEHOLDER_xXx" 
    else:
        service_node["areaServed"] = {
            "@type": "Country",
            "name": "Australia"
        }
        # Services get the disclaimer via termsOfService? 
        # Template said usageInfo stays on WebPage. We can add specific Service terms if needed.

    graph.append(service_node)

    # NODE 3: FAQPage (Conditional)
    if faqs:
        faq_node = {
            "@id": "#faq",
            "@type": "FAQPage",
            "mainEntity": faqs
        }
        graph.append(faq_node)

    # NODE 4: Organization (Static)
    graph.append(IP_AUSTRALIA_NODE)

    # --- FINALIZE ---
    final_json = {
        "@context": "https://schema.org",
        "@graph": graph
    }

    # Write to File
    out_filename = f"{udid}.json"
    with open(os.path.join(OUTPUT_DIR, out_filename), 'w', encoding='utf-8') as f:
        json.dump(final_json, f, indent=2)
    
    print(f"Generated: {out_filename} (Type: {schema_type})")

# --- EXECUTION ---

if __name__ == "__main__":
    print("Loading Metadata...")
    rows = load_metatable(CSV_PATH)
    print(f"Found {len(rows)} entries.")
    
    for row in rows:
        if row.get('UDID'): # Ensure valid row
            process_file(row)
            
    print("Processing Complete.")

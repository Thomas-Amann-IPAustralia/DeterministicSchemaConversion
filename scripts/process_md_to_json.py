import csv
import json
import os
import re

# --- CONFIGURATION ---
CSV_PATH = 'metatable-Content.csv'
MD_DIR = 'IPFR-Webpages'
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
MD_FILES_INDEX = {}

def build_file_indices():
    """Scans MD directory and builds a lowercase map for robust lookup."""
    print(f"Indexing {MD_DIR}...")
    if os.path.exists(MD_DIR):
        for f in os.listdir(MD_DIR):
            if f.lower().endswith('.md'):
                MD_FILES_INDEX[f.lower()] = f
        print(f"  > Indexed {len(MD_FILES_INDEX)} Markdown files.")
    else:
        print(f"  > CRITICAL WARNING: Directory {MD_DIR} does not exist.")

def find_md_file_robust(udid, canonical_url):
    """Finds MD file by scanning the index for UDID or Slug matches (Case-Insensitive)."""
    udid_key = udid.lower() if udid else "xxxxx"
    
    slug = ""
    if canonical_url and '/' in canonical_url:
        slug = canonical_url.rstrip('/').split('/')[-1].lower()
    
    match_md = None

    # Priority A: Exact Filename Match
    if f"{udid_key}.md" in MD_FILES_INDEX:
        match_md = MD_FILES_INDEX[f"{udid_key}.md"]
    elif f"{slug}.md" in MD_FILES_INDEX:
        match_md = MD_FILES_INDEX[f"{slug}.md"]
    
    # Priority B: Contains UDID
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

    return os.path.join(MD_DIR, match_md) if match_md else None

# --- MARKDOWN PARSER ---

def parse_markdown_sections(md_text):
    """
    Parses markdown into a list of structured sections.
    Returns: [{'level': int, 'title': str, 'content': str, 'raw_lines': []}, ...]
    """
    sections = []
    lines = md_text.split('\n')
    
    # Header regex: # Title, ## Title, etc.
    header_pattern = re.compile(r'^(#+)\s+(.*)')
    
    # Initial buffer for content before the first header (Intro)
    current_section = {
        'level': 0, 
        'title': 'Intro', 
        'raw_lines': []
    }
    
    for line in lines:
        match = header_pattern.match(line)
        if match:
            # 1. Finalize the previous section
            if current_section['raw_lines'] or current_section['title'] != 'Intro':
                current_section['content'] = '\n'.join(current_section['raw_lines']).strip()
                sections.append(current_section)
            
            # 2. Start new section
            current_section = {
                'level': len(match.group(1)),
                'title': match.group(2).strip(),
                'raw_lines': []
            }
        else:
            current_section['raw_lines'].append(line)
            
    # Finalize the last section
    if current_section['raw_lines'] or current_section['title']:
        current_section['content'] = '\n'.join(current_section['raw_lines']).strip()
        sections.append(current_section)
        
    return sections

def extract_links(text):
    """Extracts [Text](URL) from markdown content."""
    # Regex for standard markdown links
    return re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text)

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

# --- MAIN LOGIC ---

def process_file(row):
    udid = row.get('UDID')
    title = row.get('Main-title')
    canonical_url = row.get('Canonical-url')
    description = row.get('Description')
    entry_point = row.get('Entry-point', '').strip()
    provider_name = row.get('Provider', 'IP Australia')
    archetype_raw = row.get('Archectype', 'Service').strip()
    
    # 1. Find MD File
    md_path = find_md_file_robust(udid, canonical_url)
    
    if not md_path:
        print(f"Skipping {udid}: MD file not found.")
        return

    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 2. Parse Markdown Structure
    sections = parse_markdown_sections(md_text)

    # 3. Extract Specific Components
    
    # A. FAQs: Any header ending in '?' (except 'What is it?')
    faqs = []
    for sec in sections:
        clean_title = sec['title'].strip()
        if clean_title.endswith('?') and "what is it" not in clean_title.lower():
            if sec['content']: # Only if there is an answer
                faqs.append({
                    "@type": "Question",
                    "name": clean_title,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": sec['content']
                    }
                })

    # B. Article Body: Content under "What is it?"
    article_body = None
    for sec in sections:
        if "what is it" in sec['title'].lower():
            article_body = sec['content']
            break
    # Fallback: if no "What is it?", use the Intro or first content section
    if not article_body and len(sections) > 0:
        # Use the first section that isn't the title itself or empty
        for sec in sections:
            if sec['content'] and sec['title'] != title:
                article_body = sec['content']
                break

    # C. Headline: Text with "##" in front (Level 2 header)
    extracted_headline = None
    for sec in sections:
        if sec['level'] == 2:
            extracted_headline = sec['title']
            break
    
    # D. Related Links (Extracted from all content)
    related_links = []
    seen_urls = set()
    all_content = "\n".join([s['content'] for s in sections])
    found_links = extract_links(all_content)
    
    for link_text, link_url in found_links:
        # Simple filter to avoid mailto, anchor links, or duplicates
        if link_url.startswith('http') and link_url not in seen_urls:
            related_links.append({
                "@type": "WebPage",
                "url": link_url,
                "name": link_text
            })
            seen_urls.add(link_url)

    # 4. Construct JSON Graph
    schema_type, is_self_help, is_gov_service = determine_archetype_logic(archetype_raw)
    
    graph = []

    # NODE 1: WebPage
    webpage_node = {
        "@type": "WebPage",
        "@id": f"{canonical_url}#webpage",
        "headline": extracted_headline if extracted_headline else title,
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

    if related_links:
        webpage_node["relatedLink"] = related_links

    # Split Personality Logic
    if not is_self_help and faqs:
        webpage_node["hasPart"] = [{"@id": "#faq"}]

    graph.append(webpage_node)

    # NODE 2: Service / Article
    service_node = {
        "@id": "#the-service",
        "@type": schema_type,
        "name": title,
        "headline": extracted_headline if extracted_headline else title, # Fallback to CSV title
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
        service_node["articleBody"] = article_body if article_body else "Content not found."
        service_node["step"] = "xXx_PLACEHOLDER_xXx" 
    else:
        service_node["areaServed"] = {"@type": "Country", "name": "Australia"}

    graph.append(service_node)

    # NODE 3: FAQPage
    if faqs:
        faq_node = {
            "@id": "#faq",
            "@type": "FAQPage",
            "mainEntity": faqs
        }
        graph.append(faq_node)

    # NODE 4: Organization
    graph.append(IP_AUSTRALIA_NODE)

    # Save
    final_json = {
        "@context": "https://schema.org",
        "@graph": graph
    }

    out_filename = f"{udid}.json"
    with open(os.path.join(OUTPUT_DIR, out_filename), 'w', encoding='utf-8') as f:
        json.dump(final_json, f, indent=2)

# --- EXECUTION ---

if __name__ == "__main__":
    build_file_indices()
    
    print("Loading Metadata...")
    rows = load_metatable(CSV_PATH)
    print(f"Found {len(rows)} entries in CSV.")
    
    processed_count = 0
    for row in rows:
        if row.get('UDID'): 
            process_file(row)
            processed_count += 1
            
    print(f"Processing Complete. Processed {processed_count} files.")

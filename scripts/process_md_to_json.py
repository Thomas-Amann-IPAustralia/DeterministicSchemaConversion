import os
import csv
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
INPUT_DIR = 'IPFR-Webpages' if os.path.exists('IPFR-Webpages') else '.'
OUTPUT_DIR = 'json_output'
CSV_FILE = '260203_IPFRMetaTable.csv'

# --- 1. KNOWLEDGE BASES ---
LEGISLATION_MAP = {
    "trade mark": [
        {"name": "Trade Marks Act 1995", "url": "https://www.legislation.gov.au/C2004A04969/latest/versions", "type": "Act"},
        {"name": "Trade Marks Regulations 1995", "url": "https://www.legislation.gov.au/F1996B00084/latest/versions", "type": "Regulations"}
    ],
    "patent": [
        {"name": "Patents Act 1990", "url": "https://www.legislation.gov.au/C2004A04014/latest/versions", "type": "Act"},
        {"name": "Patents Regulations 1991", "url": "https://www.legislation.gov.au/F1996B02697/latest/versions", "type": "Regulations"}
    ],
    "design": [
        {"name": "Designs Act 2003", "url": "https://www.legislation.gov.au/C2004A01232/latest/versions", "type": "Act"},
        {"name": "Designs Regulations 2004", "url": "https://www.legislation.gov.au/F2004B00136/latest/versions", "type": "Regulations"}
    ],
    "pbr": [ 
        {"name": "Plant Breeder’s Rights Act 1994", "url": "https://www.legislation.gov.au/C2004A04783/latest/versions", "type": "Act"},
        {"name": "Plant Breeder’s Rights Regulations 1994", "url": "https://www.legislation.gov.au/F1996B02512/latest/versions", "type": "Regulations"}
    ],
    "plant breeder": [ 
        {"name": "Plant Breeder’s Rights Act 1994", "url": "https://www.legislation.gov.au/C2004A04783/latest/versions", "type": "Act"},
        {"name": "Plant Breeder’s Rights Regulations 1994", "url": "https://www.legislation.gov.au/F1996B02512/latest/versions", "type": "Regulations"}
    ],
    "copyright": [
        {"name": "Copyright Act 1968", "url": "https://www.legislation.gov.au/C1968A00063/latest/text", "type": "Act"},
        {"name": "Copyright Regulations 2017", "url": "https://www.legislation.gov.au/F2017L01649/latest/text", "type": "Regulations"}
    ],
    "customs": [
        {"name": "Customs Act 1901", "url": "https://www.legislation.gov.au/C1901A00006/latest/text", "type": "Act"},
        {"name": "Customs Regulation 2015", "url": "https://www.legislation.gov.au/F2015L00373/latest/text", "type": "Regulations"}
    ]
}

PROVIDER_MAP = {
    "ASBFEO": {
        "@type": "GovernmentOrganization",
        "name": "Australian Small Business and Family Enterprise Ombudsman",
        "alternateName": "ASBFEO",
        "url": "https://www.asbfeo.gov.au"
    },
    "IP Australia": {
        "@type": "GovernmentOrganization",
        "name": "IP Australia",
        "alternateName": "Intellectual Property Australia",
        "url": "https://www.ipaustralia.gov.au"
    },
    "Australian Border Force": {
        "@type": "GovernmentOrganization",
        "name": "Australian Border Force",
        "alternateName": "ABF"
    },
    "WIPO": {
        "@type": "Organization",
        "name": "World Intellectual Property Organization",
        "alternateName": "WIPO"
    },
    "Federal Circuit Court": {
        "@type": "Organization",
        "name": "Federal Circuit and Family Court of Australia"
    }
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
    "parentOrganization": {"@type": "GovernmentOrganization", "name": "Australian Government"
    }
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
    "Unregistered-tm": "https://www.wikidata.org/wiki/Q165196", # Mapped to Trade Mark
    "Patent": "https://www.wikidata.org/wiki/Q253623",
    "Design": "https://www.wikidata.org/wiki/Q1240325",
    "Copyright": "https://www.wikidata.org/wiki/Q12978",
    "Plant Breeder's Rights": "https://www.wikidata.org/wiki/Q695112"
}

# --- 2. CORE LOGIC FUNCTIONS ---

def load_csv_metadata(csv_path):
    rows = []
    if not os.path.exists(csv_path):
        print(f"CRITICAL WARNING: CSV file '{csv_path}' not found.")
        return rows
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return rows

def find_metadata_row(md_content, filename, csv_rows):
    # 1. PageURL Match (Most Accurate)
    url_match = re.search(r'PageURL:\s*\"\[(.*?)\]', md_content)
    if url_match:
        page_url = url_match.group(1).strip()
        for row in csv_rows:
            csv_url = row.get('canonical url', '').strip()
            if csv_url == page_url or (csv_url and page_url.endswith(csv_url.split('/')[-1])):
                return row

    # 2. UDID Match
    udid_match = re.search(r'([A-Z]\d{4})', filename)
    if udid_match:
        target_udid = udid_match.group(1)
        row = next((r for r in csv_rows if r.get('UDID') == target_udid), None)
        if row: return row

    # 3. Fuzzy Title Match
    clean_name = filename.lower().replace('.json', '').replace('.md', '').replace('ipfr_', '').replace('_', ' ')
    clean_name = re.sub(r'\d+', '', clean_name).strip()

    for row in csv_rows:
        csv_title = row.get('Main Title', '').lower()
        if clean_name and clean_name in csv_title:
            return row
            
    return {}

def parse_markdown_blocks(md_text):
    blocks = {}
    lines = md_text.split('\n')
    current_header = "intro"
    current_content = []

    for line in lines:
        if line.strip().startswith('#'):
            if current_content:
                blocks[current_header] = "\n".join(current_content).strip()
            
            clean_header = line.lstrip('#').strip().lower()
            clean_header = clean_header.replace('’', "'").replace('“', '"').replace('”', '"')
            current_header = clean_header
            current_content = []
        else:
            current_content.append(line)
    
    if current_content:
        blocks[current_header] = "\n".join(current_content).strip()
        
    return blocks

def generate_citations_from_csv(metadata_row):
    citations = []
    raw_ip_rights = metadata_row.get('Relevant IP right', '')
    if not raw_ip_rights:
        return citations

    cleaned_rights = raw_ip_rights.replace('"', '').lower()
    rights_list = [r.strip() for r in cleaned_rights.split(',')]
    
    added_urls = set()

    for right in rights_list:
        if right in LEGISLATION_MAP:
            for leg in LEGISLATION_MAP[right]:
                if leg['url'] not in added_urls:
                    citations.append({
                        "@type": "Legislation",
                        "name": leg['name'],
                        "url": leg['url'],
                        "legislationType": leg['type']
                    })
                    added_urls.add(leg['url'])
                    
    return citations

def resolve_provider(provider_raw_string, archetype_hint=""):
    """
    Resolves provider and enforces types based on Archetype hint.
    """
    base_obj = {"@type": "Organization", "name": "Third-Party Provider"}

    # 1. Try to find detailed map match
    if provider_raw_string:
        for key, obj in PROVIDER_MAP.items():
            if key.lower() in provider_raw_string.lower():
                base_obj = obj.copy()
                break
        else:
            # If no detailed match, use the raw string
            base_obj["name"] = provider_raw_string.strip()

    # 2. Enforce Type based on Archetype
    if "Government Service" in archetype_hint:
        base_obj["@type"] = "GovernmentOrganization"
    elif "Non-Government" in archetype_hint:
        base_obj["@type"] = "NGO" # User requested NGO for Non-Gov
    elif "Commercial" in archetype_hint:
        base_obj["@type"] = "Organization"

    return base_obj

def clean_text_retain_formatting(text, strip_images=False):
    if not text: return ""
    text = text.strip()
    if strip_images:
        text = re.sub(r'\[\s*!\[.*?\]\(.*?\)\s*\]\(.*?\)', '', text)
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        text = re.sub(r'\[\s*\]\(.*?\)', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def extract_faqs(blocks):
    faq_keys = [
        "what are the benefits?", "what are the risks?", "what might the costs be?",
        "what might the cost be?", "how much time might be involved?",
        "how often is this used?", "what are the possible outcomes?",
        "who can use this?", "who's involved?", "who is involved?"
    ]
    
    faqs = []
    for key, content in blocks.items():
        if any(k in key for k in faq_keys) and content:
            display_name = key.capitalize().replace('?', '') + "?"
            faqs.append({
                "@type": "Question",
                "name": display_name,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": clean_text_retain_formatting(content)
                }
            })
    return faqs

def extract_howto_steps(blocks):
    steps = []
    target_key = next((k for k in blocks.keys() if "proceed" in k or "steps" in k), None)
    
    if target_key:
        raw_text = blocks[target_key]
        matches = re.findall(r'(?:^|\n)(?:\*|\d+\.)\s+(.*?)(?=\n(?:\*|\d+\.)|\Z)', raw_text, re.DOTALL)
        
        if matches:
            for step_text in matches:
                clean_text = clean_text_retain_formatting(step_text)
                if clean_text:
                    steps.append({
                        "@type": "HowToStep",
                        "name": clean_text[:50] + "..." if len(clean_text) > 50 else clean_text,
                        "text": clean_text
                    })
        else:
            paragraphs = [p.strip() for p in raw_text.split('\n\n') if p.strip()]
            for p in paragraphs:
                if "see also" in p.lower(): continue
                steps.append({
                    "@type": "HowToStep",
                    "name": p[:50] + "..." if len(p) > 50 else p,
                    "text": p
                })
    return steps

def resolve_about_topics(metadata_row):
    """
    Returns a list of Thing objects for the 'about' property.
    Maps Unregistered-tm to Trade Mark QID.
    """
    raw_ip_rights = metadata_row.get('Relevant IP right', '')
    cleaned_rights = raw_ip_rights.replace('"', '').lower()
    rights_list = [r.strip() for r in cleaned_rights.split(',')]
    
    about_entities = []
    
    # Dedup names if they map to the same Thing concept? 
    # User asked for "every IP right included".
    
    for right in rights_list:
        if not right: continue
        
        # Determine Name and URL
        name = right.title()
        url = None
        
        # Direct Key Lookup
        for map_key in IP_TOPIC_MAP:
            if map_key.lower() == right:
                url = IP_TOPIC_MAP[map_key]
                name = map_key # Use official capitalization
                break
        
        entity = {"@type": "Thing", "name": name}
        if url:
            entity["sameAs"] = url
            
        about_entities.append(entity)
        
    # If single entity, return object. If multiple, return array (Schema standard).
    # However, user's ideal json showed a single object. 
    # If multiple exist, we usually return an array.
    if len(about_entities) == 1:
        return about_entities[0]
    elif len(about_entities) > 1:
        return about_entities
    else:
        return {"@type": "Thing", "name": "Intellectual Property Right"}

# --- 3. MAIN BUILDER FUNCTION ---

def process_file(filepath, filename, metadata_row):
    with open(filepath, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # A. Parse Content
    blocks = parse_markdown_blocks(md_content)
    
    # B. Metadata Extraction
    udid = metadata_row.get('UDID', 'Dxxxx')
    title = metadata_row.get('Main Title', filename.replace('.md', '').replace('_', ' '))
    archetype = metadata_row.get('Archectype') or metadata_row.get('Archetype', 'Government Service')
    archetype = archetype.strip()
    date_val = datetime.now().strftime("%Y-%m-%d")
    
    # C. Description Extraction
    desc_keys = ["what is it?", "description", "intro"]
    description_raw = next((blocks[k] for k in desc_keys if k in blocks), metadata_row.get('Description', ''))
    description = clean_text_retain_formatting(description_raw, strip_images=True)
    
    # D. Build Main Entity
    main_entities = []
    service_id = "#the-service"
    
    # ARCHETYPE LOGIC TREE
    if "Self-Help" in archetype:
        # a) Self-Help Strategy -> HowTo (No Provider)
        howto_obj = {
            "@id": service_id,
            "@type": "HowTo",
            "name": title,
            "description": description,
            "areaServed": {"@type": "Country", "name": "Australia"},
            "step": extract_howto_steps(blocks)
        }
        main_entities.append(howto_obj)
        
    else:
        # Determine Service Type and Provider based on Archetype
        service_type = "Service" # Default
        provider_name_raw = metadata_row.get('Provider') or metadata_row.get('Overtitle')
        
        # c) Government Service
        if "Government Service" in archetype:
            service_type = "GovernmentService"
            
        # b) Non-Government Third-Party Authority
        elif "Non-Government" in archetype:
            service_type = "Service"
            
        # d) Commercial Third Party Service
        elif "Commercial" in archetype:
            service_type = "Service"
            
        # Resolve Provider with Archetype Hint
        provider_obj = resolve_provider(provider_name_raw, archetype_hint=archetype)
        
        service_obj = {
            "@id": service_id,
            "@type": service_type,
            "name": title,
            "description": description,
            "areaServed": {"@type": "Country", "name": "Australia"},
            "provider": provider_obj
        }
        
        # Swap provider key for GovernmentService schema compliance
        if service_type == "GovernmentService":
             service_obj["serviceOperator"] = service_obj.pop("provider")
             
        main_entities.append(service_obj)

        # D2. Sidecar HowTo
        steps = extract_howto_steps(blocks)
        if steps:
            main_entities.append({
                "@type": "HowTo",
                "name": f"How to proceed with {title}",
                "about": {"@id": service_id},
                "step": steps
            })

    # E. FAQ Page
    faqs = extract_faqs(blocks)
    if faqs:
        main_entities.append({
            "@type": "FAQPage",
            "about": {"@id": service_id},
            "mainEntity": faqs
        })

    # F. Citations
    citations = generate_citations_from_csv(metadata_row)
    
    # G. Topics
    about_obj = resolve_about_topics(metadata_row)

    # --- H. FINAL ASSEMBLY ---
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "headline": title,
        "alternativeHeadline": metadata_row.get('Overtitle', ''),
        "description": description[:160], 
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
        "mainEntity": main_entities
    }
    
    see_also_block = next((v for k,v in blocks.items() if "see also" in k), None)
    if see_also_block:
        links = re.findall(r'\((https?://[^\)]+)\)', see_also_block)
        if links:
            json_ld["relatedLink"] = links

    out_path = os.path.join(OUTPUT_DIR, filename.replace('.md', '.json'))
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(json_ld, f, indent=2)
    print(f"Generated: {out_path}")


# --- 4. EXECUTION LOOP ---

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    csv_rows = load_csv_metadata(CSV_FILE)
    md_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.md')]
    
    for filename in md_files:
        filepath = os.path.join(INPUT_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content_sample = f.read()
            
        matched_row = find_metadata_row(content_sample, filename, csv_rows)
        
        if not matched_row:
            matched_row = {"Main Title": filename.replace('.md', '').replace('IPFR_', '').replace('_', ' ')}

        process_file(filepath, filename, matched_row)

if __name__ == "__main__":
    main()

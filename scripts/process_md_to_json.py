import os
import csv
import json
import re
from datetime import datetime

# --- CONFIGURATION ---
INPUT_DIR = 'IPFR-Webpages'
OUTPUT_DIR = 'json_output'
CSV_FILE = '260203_IPFRMetaTable.csv'

# --- STATIC RICH DATA & LOOKUPS ---

# 1. Internal Database of Legislation URLs (Restores D1003 Richness)
# This allows the CSV to just say "Trade Marks Act 1995" and get the full rich object.
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

# 2. Rich Audience Definition
AUDIENCE_BLOCK = {
    "@type": "BusinessAudience",
    "audienceType": "Australian Small Business Owners",
    "alternateName": [
        "Startups", "Entrepreneurs", "SME", "Spinout Company", 
        "Startup", "Spinout", "Small to Medium Enterprise", "Sole Trader"
    ],
    "geographicArea": {
        "@type": "Country",
        "name": "Australia"
    }
}

# 3. Publisher Definition
PUBLISHER_BLOCK = {
    "@type": "GovernmentOrganization",
    "name": "IP Australia",
    "url": "https://www.ipaustralia.gov.au",
    "parentOrganization": {
        "@type": "GovernmentOrganization",
        "name": "Australian Government"
    }
}

# 4. Standard Disclaimer / Usage Info
USAGE_INFO_BLOCK = {
    "@type": "CreativeWork",
    "name": "Disclaimer and Feedback Policy",
    "text": "This IP First Response website has been designed to help IP rights holders navigate IP infringement and enforcement by making it visible, accessible, and to provide information about the factors involved in pursuing different options. It does not provide legal, business or other professional advice, and none of the content should be regarded as recommending a specific course of action. We welcome any feedback via our IP First Response feedback form and by emailing us.",
    "url": "mailto:IPFirstResponse@IPAustralia.gov.au?subject=Feedback on IP First Response"
}

# 5. Wikidata Mapping for "About"
IP_TOPIC_MAP = {
    "Intellectual Property Right": "https://www.wikidata.org/wiki/Q108855835",
    "Trade Mark": "https://www.wikidata.org/wiki/Q165196",
    "Patent": "https://www.wikidata.org/wiki/Q253623",
    "Design": "https://www.wikidata.org/wiki/Q1240325",
    "Copyright": "https://www.wikidata.org/wiki/Q12978"
}

def load_csv_metadata(csv_path):
    """Loads CSV metadata into a dictionary keyed by UDID."""
    metadata = {}
    if not os.path.exists(csv_path):
        print(f"Warning: CSV file {csv_path} not found.")
        return metadata
        
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Key by UDID if present, otherwise ignore
                if row.get('UDID'):
                    metadata[row['UDID']] = row
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return metadata

def build_citation_list(csv_legislation_str):
    """
    Parses the 'Legislation' column. 
    Matches standard names to LEGISLATION_DB for rich schema.
    """
    if not csv_legislation_str:
        return []

    citations = []
    # Split by semicolon, pipe, or newline
    raw_items = re.split(r'[;|\n]', csv_legislation_str)
    
    for item in raw_items:
        clean_name = item.strip()
        if not clean_name:
            continue
            
        # Lookup in DB
        url = LEGISLATION_DB.get(clean_name)
        
        # Determine Type (Act vs Regulation)
        leg_type = "Legislative Instrument" if "Regulation" in clean_name else "Act"
        
        citation_obj = {
            "@type": "Legislation",
            "name": clean_name,
            "legislationType": leg_type
        }
        
        if url:
            citation_obj["url"] = url
            
        citations.append(citation_obj)
        
    return citations

def parse_markdown_content(md_text):
    """
    Parses the Markdown to extract:
    1. FAQ Questions and Answers
    2. 'How To' Steps
    """
    
    # Extract FAQs: Looks for "### Question?" followed by answer text
    # Regex explanation:
    # ### (.*?) -> Capture the header (Question)
    # \n -> Newline
    # (.*?) -> Capture content (Answer)
    # (?=###|$) -> Stop at next header or end of string
    faq_matches = re.findall(r'### (.*?)\n(.*?)(?=\n###|\Z)', md_text, re.DOTALL)
    
    faqs = []
    for q, a in faq_matches:
        q_text = q.strip()
        a_text = a.strip()
        
        # Simple cleanup of Markdown links to text if preferred, 
        # or keep Markdown if the downstream system supports it.
        # D1003 kept plain text mostly, but some markdown is okay.
        
        if "?" in q_text: # heuristic to confirm it's a question
            faqs.append({
                "@type": "Question",
                "name": q_text,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": a_text
                }
            })

    # Extract 'How To' / 'What do you need to proceed'
    # Looks for the specific header and bullet points
    how_to_steps = []
    if "proceed" in md_text.lower():
        # Find the section
        section_match = re.search(r'proceed\?*\n(.*?)(?=\n###|\Z)', md_text, re.DOTALL | re.IGNORECASE)
        if section_match:
            bullets = re.findall(r'\* (.*)', section_match.group(1))
            for step_text in bullets:
                # Basic cleanup
                step_clean = step_text.strip()
                how_to_steps.append({
                    "@type": "HowToStep",
                    "name": step_clean[:100], # Short name
                    "text": step_clean
                })
                
    return faqs, how_to_steps

def process_file(filepath, metadata_row):
    with open(filepath, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # Data Parsing
    faqs, how_to_steps = parse_markdown_content(md_content)
    citations = build_citation_list(metadata_row.get('Legislation', ''))
    
    # Metadata Extraction
    udid = metadata_row.get('UDID', 'Unknown')
    title = metadata_row.get('Main Title', 'Draft Page')
    desc = metadata_row.get('Description', '')
    provider = metadata_row.get('Provider', 'Australian Government')
    
    # Date Handling
    date_val = metadata_row.get('Date', datetime.now().strftime("%Y-%m-%d"))
    
    # About / Topic
    topic_name = metadata_row.get('Relevant IP right', 'Intellectual Property Right')
    about_obj = {"@type": "Thing", "name": topic_name}
    if topic_name in IP_TOPIC_MAP:
        about_obj["sameAs"] = IP_TOPIC_MAP[topic_name]

    # --- MAIN ENTITY CONSTRUCTION (GovernmentService) ---
    main_entity = {
        "@id": "#the-service",
        "@type": "GovernmentService",
        "name": title,
        "description": desc, # You might want to pull the first paragraph of MD here if CSV desc is empty
        "serviceType": metadata_row.get('Service Type', 'Dispute Resolution'),
        "areaServed": {
            "@type": "Country",
            "name": "Australia"
        },
        "serviceOperator": {
            "@type": "GovernmentOrganization",
            "name": provider
        }
    }

    # Assemble the MainEntity List (Service + FAQ + HowTo)
    entities = [main_entity]
    
    if faqs:
        entities.append({
            "@type": "FAQPage",
            "about": {"@id": "#the-service"},
            "mainEntity": faqs
        })
        
    if how_to_steps:
        entities.append({
            "@type": "HowTo",
            "name": f"How to proceed with {title}",
            "about": {"@id": "#the-service"},
            "step": how_to_steps
        })

    # --- FINAL JSON ASSEMBLY ---
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "headline": title,
        "alternativeHeadline": title, # Or map from CSV if exists
        "description": desc,
        "url": metadata_row.get('canonical url', f"https://ipfirstresponse.ipaustralia.gov.au/options/{udid}"),
        "identifier": {
            "@type": "PropertyValue",
            "propertyID": "UDID",
            "value": udid
        },
        "inLanguage": "en-AU",
        "datePublished": date_val,
        "dateModified": date_val, # Or current date
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
    
    # Related Links (Simple list)
    if metadata_row.get('Related Links'):
        links = [l.strip() for l in metadata_row['Related Links'].split(';') if l.strip()]
        if links:
            json_ld["relatedLink"] = links

    return json_ld

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    meta_dict = load_csv_metadata(CSV_FILE)
    
    processed_count = 0
    for filename in os.listdir(INPUT_DIR):
        if filename.endswith(".md"):
            # Extract UDID from filename (e.g., D1003)
            udid_match = re.search(r'(D\d{4})', filename)
            udid = udid_match.group(1) if udid_match else None
            
            if udid and udid in meta_dict:
                row = meta_dict[udid]
                json_output = process_file(os.path.join(INPUT_DIR, filename), row)
                
                # Save
                out_name = filename.replace('.md', '.json')
                with open(os.path.join(OUTPUT_DIR, out_name), 'w', encoding='utf-8') as f:
                    json.dump(json_output, f, indent=2)
                processed_count += 1
            else:
                print(f"Skipping {filename}: No matching UDID found in CSV.")

    print(f"Done. Processed {processed_count} files.")

if __name__ == "__main__":
    main()

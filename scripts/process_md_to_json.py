import os
import csv
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup  # Requires: pip install beautifulsoup4

# --- CONFIGURATION ---
INPUT_DIR = 'IPFR-Webpages' if os.path.exists('IPFR-Webpages') else '.'
HTML_DIR = 'IPFR-Webpages-html'
OUTPUT_DIR = 'json_output'
CSV_FILE = 'metatable-Content.csv'

# --- 1. KNOWLEDGE BASES ---
LEGISLATION_MAP = {
    "trade mark": [
        {"name": "Trade Marks Act 1995", "url": "https://www.legislation.gov.au/C2004A04969/latest/text", "type": "Act"},
        {"name": "Trade Marks Regulations 1995", "url": "https://www.legislation.gov.au/F1996B00084/latest/text", "type": "Regulations"}
    ],
    "patent": [
        {"name": "Patents Act 1990", "url": "https://www.legislation.gov.au/C2004A04014/latest/text", "type": "Act"},
        {"name": "Patents Regulations 1991", "url": "https://www.legislation.gov.au/F1996B02697/latest/text", "type": "Regulations"}
    ],
    "design": [
        {"name": "Designs Act 2003", "url": "https://www.legislation.gov.au/C2004A01232/latest/text", "type": "Act"},
        {"name": "Designs Regulations 2004", "url": "https://www.legislation.gov.au/F2004B00136/latest/text", "type": "Regulations"}
    ],
    # PBR mapped explicitly to Plant Breeder's Rights Act as requested
    "pbr": [ 
        {"name": "Plant Breeder’s Rights Act 1994", "url": "https://www.legislation.gov.au/C2004A04783/latest/text", "type": "Act"},
        {"name": "Plant Breeder’s Rights Regulations 1994", "url": "https://www.legislation.gov.au/F1996B02512/latest/text", "type": "Regulations"}
    ],
    "plant breeder": [ 
        {"name": "Plant Breeder’s Rights Act 1994", "url": "https://www.legislation.gov.au/C2004A04783/latest/text", "type": "Act"},
        {"name": "Plant Breeder’s Rights Regulations 1994", "url": "https://www.legislation.gov.au/F1996B02512/latest/text", "type": "Regulations"}
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
        "alternateName": "ASBFEO",
        "url": "https://www.asbfeo.gov.au"
    },
    "IP Australia": {
        "@type": "GovernmentOrganization",
        "alternateName": "Intellectual Property Australia",
        "url": "https://www.ipaustralia.gov.au",
        "sameAs": [
            "https://en.wikipedia.org/wiki/IP_Australia",
            "https://www.wikidata.org/wiki/Q5973154"
        ]
    },
    "Australian Border Force": {
        "@type": "GovernmentOrganization",
        "alternateName": "ABF",
        "url": "https://www.abf.gov.au/"
    },
    "WIPO": {
        "@type": "Organization",
        "alternateName": "WIPO",
        "sameAs": "https://www.wikidata.org/wiki/Q178332"
    },
    "Federal Circuit Court": {
        "@type": "Organization"
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
    "parentOrganization": {
        "@type": "GovernmentOrganization", 
        "name": "Australian Government"
    },
    "sameAs": "https://www.wikidata.org/wiki/Q5973154"
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

# --- 2. HTML CLEANING & EXTRACTION FUNCTIONS ---

def clean_html_fragment(soup_element):
    """
    Cleans a BeautifulSoup element and converts it to Markdown.
    Removes HTML tags but preserves semantic structure via Markdown syntax.
    """
    if not soup_element:
        return ""
    
    # Create a new soup fragment to process
    fragment = BeautifulSoup(str(soup_element), 'html.parser')

    # 1. Remove noise tags completely
    for tag in fragment(['script', 'style', 'button', 'svg', 'figure', 'img', 'iframe']):
        tag.decompose()

    # 2. Convert Links to Markdown: [text](href)
    for a in fragment.find_all('a', href=True):
        text = a.get_text(strip=True)
        url = a['href']
        if text and url:
            a.replace_with(f"[{text}]({url})")

    # 3. Convert Bold/Strong to **text**
    for b in fragment.find_all(['strong', 'b']):
        text = b.get_text(strip=True)
        if text:
            b.replace_with(f"**{text}**")

    # 4. Convert Italic/Em to *text*
    for i in fragment.find_all(['em', 'i']):
        text = i.get_text(strip=True)
        if text:
            i.replace_with(f"*{text}*")

    # 5. Handle Lists (Simple Bullet Conversion)
    for li in fragment.find_all('li'):
        text = li.get_text(strip=True)
        if text:
            li.replace_with(f"\n* {text}")

    # 6. Extract Text (handling paragraphs via newlines)
    text = fragment.get_text(separator="\n\n")

    # --- Unicode Normalization ---
    replacements = {
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-",
        "\u00a0": " "
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def parse_html_to_blocks(html_content):
    """
    Parses HTML content into logical blocks based on H2/H3 headers.
    Returns a dictionary: {header_text: text_content}
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    blocks = {}
    
    main_content = soup.find('div', class_='ct-layout__inner') or soup
    
    current_header = "intro"
    current_elements = []
    
    container = main_content
    if main_content.find('article'):
        container = main_content.find('article')
        
    start_node = container.find(['h1', 'h2'])
    
    if start_node:
        iterator_parent = start_node.parent
        
        for child in iterator_parent.children:
            if child.name in ['h1', 'h2', 'h3']:
                # Save previous block
                if current_elements:
                    clean_text = ""
                    for el in current_elements:
                        clean_text += clean_html_fragment(el) + "\n"
                    if clean_text.strip():
                        blocks[current_header] = clean_text.strip()
                
                # Start new block
                current_header = child.get_text(strip=True).lower()
                current_header = re.sub(r'[^\w\s\?\']', '', current_header).strip()
                current_elements = []
            
            elif child.name and child.name not in ['script', 'style', 'button', 'svg', 'form']:
                 current_elements.append(child)
        
        # Flush last block
        if current_elements:
            clean_text = ""
            for el in current_elements:
                 clean_text += clean_html_fragment(el) + "\n"
            if clean_text.strip():
                blocks[current_header] = clean_text.strip()
    
    return blocks

# --- 3. CSV & UTIL FUNCTIONS ---

def load_csv_metadata(csv_path):
    rows = []
    if not os.path.exists(csv_path):
        print(f"CRITICAL WARNING: CSV file '{csv_path}' not found.")
        return rows
    try:
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            rows = list(reader)
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return rows

def find_metadata_row(md_content, filename, csv_rows):
    # 1. PageURL Match
    url_match = re.search(r'PageURL:\s*\"\[(.*?)\]', md_content)
    if url_match:
        page_url = url_match.group(1).strip()
        for row in csv_rows:
            csv_url = row.get('Canonical-url', '').strip()
            if csv_url == page_url or (csv_url and page_url.endswith(csv_url.split('/')[-1])):
                return row

    # 2. UDID Match
    udid_match = re.search(r'([A-Z]\d{4})', filename)
    if udid_match:
        target_udid = udid_match.group(1)
        for row in csv_rows:
            if row.get('UDID') == target_udid:
                return row

    # 3. Fuzzy Title Match
    clean_name = filename.lower().replace('.json', '').replace('.md', '').replace('ipfr_', '').replace('_', ' ')
    clean_name = re.sub(r'^[a-z]\d{4}\s*-\s*', '', clean_name).strip()
    
    for row in csv_rows:
        csv_title = row.get('Main-title', '').lower().strip()
        if clean_name == csv_title: return row
        if clean_name and clean_name in csv_title: return row
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

def clean_text_retain_formatting(text, strip_images=False):
    if not text: return ""
    
    replacements = {
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-",
        "\u2026": "...", "\u00a0": " ",
    }
    for src, target in replacements.items():
        text = text.replace(src, target)

    if strip_images:
        text = re.sub(r'\[\s*!\[.*?\]\(.*?\)\s*\]\(.*?\)', '', text)
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        text = re.sub(r'\[\s*\]\(.*?\)', '', text)
        
    text = text.replace('\r', '')
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in text.split('\n')]
    text = "\n".join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def extract_links_and_clean(text):
    if not text:
        return text, []

    found_links = []

    def replace_fn(match):
        name = match.group(1).strip()
        url = match.group(2).strip()
        
        if url:
            found_links.append({
                "@type": "WebPage",
                "url": url,
                "name": name if name else "Link"
            })
        
        return name 

    cleaned_text = re.sub(r'\[(.*?)\]\((https?://[^\)]+)\)', replace_fn, text)
    return cleaned_text, found_links

def generate_citations_from_csv(metadata_row):
    """
    Generates citations based on the 'Relevant-ip-right' field in the CSV.
    Logic:
    1. If text implies 'Any dispute related to intellectual property', it generates
       citations for ALL major IP rights (Trade Mark, Patent, Design, PBR, Copyright).
    2. 'pbr' is explicitly treated as 'Plant Breeder's Rights'.
    """
    citations = []
    raw_ip_rights = metadata_row.get('Relevant-ip-right', '')
    if not raw_ip_rights: return citations
    
    # Cleaning: Remove extra quotes and normalize to lower case
    cleaned_rights_str = raw_ip_rights.replace('"', '').replace("'", "").lower().strip()
    
    rights_to_process = []
    
    # --- UPDATED LOGIC: Handle "Any Dispute" Wildcard ---
    if "any dispute related to intellectual property" in cleaned_rights_str:
        # If "Any dispute" is found, we must include all 5 major IP types
        rights_to_process = ["trade mark", "patent", "design", "pbr", "copyright"]
    else:
        # Standard processing: split by comma
        rights_to_process = [r.strip() for r in cleaned_rights_str.split(',') if r.strip()]
    
    added_urls = set()
    for right in rights_to_process:
        # Look up legilsation. Note: 'pbr' is a key in LEGISLATION_MAP 
        # that points to Plant Breeder's Rights Act/Regs.
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
    base_obj = {"@type": "Organization"}
    if provider_raw_string:
        for key, obj in PROVIDER_MAP.items():
            if key.lower() in provider_raw_string.lower():
                base_obj = obj.copy()
                break
    if "Government Service" in archetype_hint: base_obj["@type"] = "GovernmentOrganization"
    elif "Non-Government" in archetype_hint: base_obj["@type"] = "NGO"
    elif "Commercial" in archetype_hint: base_obj["@type"] = "Organization"
    base_obj["name"] = "xXx_PLACEHOLDER_xXx"
    return base_obj

def resolve_about_topics(metadata_row):
    raw_ip_rights = metadata_row.get('Relevant-ip-right', '')
    cleaned_rights = raw_ip_rights.replace('"', '').replace("'", "").lower()
    rights_list = [r.strip() for r in cleaned_rights.split(',') if r.strip()]
    
    about_entities = []
    for right in rights_list:
        if not right: continue
        name = right.title()
        url = None
        for map_key in IP_TOPIC_MAP:
            if map_key.lower() == right:
                url = IP_TOPIC_MAP[map_key]
                name = map_key 
                break
        entity = {"@type": "Thing", "name": name}
        if url: entity["sameAs"] = url
        about_entities.append(entity)
    if len(about_entities) == 1: return about_entities[0]
    elif len(about_entities) > 1: return about_entities
    else: return {"@type": "Thing", "name": "Intellectual Property Right"}

# --- 4. EXTRACTORS ---

def extract_dynamic_content_html(blocks, main_description_key=None):
    IGNORED_HEADERS = {
        "intro", "description", "see also", "want to give us feedback?", 
        "references", "external links", "table of contents", "feedback", 
        "start here"
    }
    if main_description_key:
        IGNORED_HEADERS.add(main_description_key.lower())

    content_items = []
    collected_links = []

    for header, text_content in blocks.items():
        clean_header_key = header.lower().strip()
        
        if not text_content: continue
        if clean_header_key in IGNORED_HEADERS: continue
        if "step" in clean_header_key or "proceed" in clean_header_key: continue

        display_name = header.capitalize()
        if not display_name.endswith('?') and not display_name.endswith(':'):
             if "features" in clean_header_key: display_name = f"What are the {header.lower()}?"
             elif "watch out" in clean_header_key: display_name = f"What should I watch out for?"
             elif "outcomes" in clean_header_key: display_name = f"What are the possible outcomes?"
             elif "costs" in clean_header_key: display_name = f"What might the costs be?"
             elif "time" in clean_header_key: display_name = f"How much time might be involved?"
             elif "benefits" in clean_header_key: display_name = f"What are the benefits?"
             elif "risks" in clean_header_key: display_name = f"What are the risks?"
             else: display_name = f"{display_name}?"

        clean_md, links = extract_links_and_clean(text_content)
        collected_links.extend(links)

        content_items.append({
            "@type": "Question",
            "name": display_name,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": clean_md
            }
        })
    return content_items, collected_links

def extract_howto_steps_html(blocks):
    steps = []
    collected_links = []
    target_key = next((k for k in blocks.keys() if "proceed" in k or "steps" in k), None)
    
    if target_key:
        raw_text = blocks[target_key]
        
        if "\n* " in raw_text:
             matches = raw_text.split("\n* ")
             for m in matches:
                 if not m.strip(): continue
                 clean_step, links = extract_links_and_clean(m.strip())
                 collected_links.extend(links)
                 steps.append({
                    "@type": "HowToStep",
                    "name": "xXx_PLACEHOLDER_xXx", 
                    "text": clean_step
                })
        else:
             paragraphs = raw_text.split('\n\n')
             for p in paragraphs:
                 if not p.strip(): continue
                 clean_step, links = extract_links_and_clean(p.strip())
                 collected_links.extend(links)
                 steps.append({
                    "@type": "HowToStep",
                    "name": "xXx_PLACEHOLDER_xXx", 
                    "text": clean_step
                })

    return steps, collected_links

def extract_howto_steps_md(blocks):
    steps = []
    collected_links = []
    target_key = next((k for k in blocks.keys() if "proceed" in k or "steps" in k), None)
    if target_key:
        raw_text = blocks[target_key]
        matches = re.findall(r'(?:^|\n)(?:\*|\d+\.)\s+(.*?)(?=\n(?:\*|\d+\.)|\Z)', raw_text, re.DOTALL)
        if matches:
            for step_text in matches:
                formatted_text = clean_text_retain_formatting(step_text)
                clean_step, links = extract_links_and_clean(formatted_text)
                collected_links.extend(links)
                steps.append({"@type": "HowToStep", "name": "xXx_PLACEHOLDER_xXx", "text": clean_step})
        else:
            paragraphs = [p.strip() for p in raw_text.split('\n\n') if p.strip()]
            for p in paragraphs:
                if "see also" in p.lower(): continue
                formatted_text = clean_text_retain_formatting(p)
                clean_step, links = extract_links_and_clean(formatted_text)
                collected_links.extend(links)
                steps.append({"@type": "HowToStep", "name": "xXx_PLACEHOLDER_xXx", "text": clean_step})
    return steps, collected_links

# --- 5. MAIN PROCESSOR ---

def process_file_pair(md_filepath, html_filepath, filename, metadata_row):
    # Load MD
    with open(md_filepath, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # Load HTML if valid
    html_content = ""
    use_html = False
    if html_filepath and os.path.exists(html_filepath):
        try:
            with open(html_filepath, 'r', encoding='utf-8') as f:
                html_content = f.read()
            use_html = True
        except Exception:
            pass

    blocks = parse_html_to_blocks(html_content) if use_html else parse_markdown_blocks(md_content)
    if not blocks and use_html: 
        blocks = parse_markdown_blocks(md_content)
        use_html = False

    udid = metadata_row.get('UDID', 'Dxxxx')
    title = metadata_row.get('Main-title', filename.replace('.md', '').replace('_', ' '))
    archetype = metadata_row.get('Archectype', 'Government Service').strip()
    date_val = datetime.now().strftime("%Y-%m-%d")

    page_url = metadata_row.get('Canonical-url', f"https://ipfirstresponse.ipaustralia.gov.au/options/{udid}")

    master_links = [] 

    # --- DESCRIPTION ---
    description = clean_text_retain_formatting(metadata_row.get('Description', ''), strip_images=True)
    used_desc_key = None 
    if not description:
        desc_keys = ["what is it", "description", "intro"]
        for k in desc_keys:
            found_key = next((bk for bk in blocks.keys() if k in bk), None)
            if found_key:
                raw_desc = blocks[found_key]
                clean_desc, links = extract_links_and_clean(raw_desc)
                master_links.extend(links)
                
                description = clean_desc[:300] + "..."
                used_desc_key = found_key
                break

    # --- ENTITY CONSTRUCTION ---
    service_id = "#the-service"
    has_provider = True
    
    if "Self-Help" in archetype:
        service_type, has_provider = "HowTo", False 
    elif "Government Service" in archetype:
        service_type = "GovernmentService"
    elif "Commercial" in archetype:
        service_type = "Service"
    elif "Non-Government" in archetype:
        service_type = "Service" 
    else:
        service_type = "GovernmentService"

    main_obj = {
        "@id": service_id,
        "@type": service_type,
        "name": title,
        "description": description,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": page_url
        },
        "areaServed": {"@type": "Country", "name": "Australia"}
    }

    if use_html:
        steps, s_links = extract_howto_steps_html(blocks)
    else:
        steps, s_links = extract_howto_steps_md(blocks)
    master_links.extend(s_links)

    if service_type == "HowTo":
        main_obj["step"] = steps
    
    if has_provider:
        provider_name = metadata_row.get('Overtitle')
        provider_obj = resolve_provider(provider_name, archetype_hint=archetype)
        if service_type == "GovernmentService": main_obj["serviceOperator"] = provider_obj
        else: main_obj["provider"] = provider_obj

    main_entities = [main_obj]

    if service_type != "HowTo" and steps:
        main_entities.append({
            "@type": "HowTo",
            "name": f"How to proceed with {title}",
            "about": {"@id": service_id},
            "step": steps
        })

    # FAQs (Dynamic Content)
    faqs = []
    if use_html:
        faqs, f_links = extract_dynamic_content_html(blocks, main_description_key=used_desc_key)
        master_links.extend(f_links)
    else:
        for h, c in blocks.items():
            if h in ["intro", "description", "see also", "step"] or (used_desc_key and h == used_desc_key): continue
            q_name = h.capitalize() + ("?" if not h.endswith('?') else "")
            
            clean_ans, links = extract_links_and_clean(clean_text_retain_formatting(c))
            master_links.extend(links)
            
            faqs.append({"@type": "Question", "name": q_name, "acceptedAnswer": {"@type": "Answer", "text": clean_ans}})

    if faqs:
        main_entities.append({
            "@type": "FAQPage",
            "about": {"@id": service_id},
            "mainEntity": faqs
        })

    # Citations & Topics
    citations = generate_citations_from_csv(metadata_row)
    about_obj = resolve_about_topics(metadata_row)

    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "headline": title,
        "alternativeHeadline": metadata_row.get('Overtitle', ''),
        "description": description[:160] if description else "", 
        "url": page_url,
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
    
    see_also = next((k for k in blocks.keys() if "see also" in k), None)
    if see_also:
        content = blocks[see_also]
        _, sa_links = extract_links_and_clean(content)
        master_links.extend(sa_links)

    unique_links_map = {}
    for lnk in master_links:
        u = lnk['url']
        if u not in unique_links_map:
            unique_links_map[u] = lnk
        else:
            if unique_links_map[u]['name'] == "Link" and lnk['name'] != "Link":
                unique_links_map[u] = lnk

    if unique_links_map:
        json_ld["relatedLink"] = list(unique_links_map.values())

    out_path = os.path.join(OUTPUT_DIR, filename.replace('.md', '.json'))
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(json_ld, f, indent=2)
    print(f"Generated: {out_path} {'[HTML Enhanced]' if use_html else '[Markdown Fallback]'}")

# --- 6. EXECUTION ---

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    csv_rows = load_csv_metadata(CSV_FILE)
    md_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.md')]
    
    html_source_dir = HTML_DIR if os.path.exists(HTML_DIR) else INPUT_DIR
    
    print(f"Processing Markdown from: {INPUT_DIR}")
    print(f"Looking for HTML in:      {html_source_dir}")

    for filename in md_files:
        md_path = os.path.join(INPUT_DIR, filename)
        
        base = filename.replace('.md', '')
        html_cands = [
            f"{base}-html.html",
            f"{base}.html", 
            f"{base}_html.html"
        ]
        
        html_path = next(
            (os.path.join(html_source_dir, h) for h in html_cands if os.path.exists(os.path.join(html_source_dir, h))), 
            None
        )
        
        with open(md_path, 'r', encoding='utf-8') as f:
            content_sample = f.read()
            
        matched_row = find_metadata_row(content_sample, filename, csv_rows)
        if not matched_row:
            matched_row = {"Main-title": base.replace('IPFR_', '').replace('_', ' ')}

        process_file_pair(md_path, html_path, filename, matched_row)

if __name__ == "__main__":
    main()

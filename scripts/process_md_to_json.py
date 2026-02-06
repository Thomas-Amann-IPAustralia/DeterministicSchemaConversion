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
    "knowsAbout": [
        "Intellectual Property",
        "Patents",
        "Trade Marks",
        "Design Rights",
        "Plant Breeder's Rights",
        "Copyright",
        "Dispute Resolution"
    ],
    "contactPoint": {
        "@type": "ContactPoint",
        "contactType": "website content owner",
        "email": "IPFirstResponse@IPAustralia.gov.au",
        "description": "Feedback and enquiries regarding IP First Response"
    },
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

# --- IP TOPIC MAP ---
IP_TOPIC_MAP = {
    "trade mark": ("Trade Mark", "https://www.wikidata.org/wiki/Q167270"),
    "unregistered-tm": ("Trade Mark", "https://www.wikidata.org/wiki/Q167270"),
    "patent": ("Patent", "https://www.wikidata.org/wiki/Q253623"),
    "design": ("Design Right", "https://www.wikidata.org/wiki/Q252799"),
    "copyright": ("Copyright", "https://www.wikidata.org/wiki/Q1297822"),
    "pbr": ("Plant Breeders' Right", "https://www.wikidata.org/wiki/Q695112"),
    "plant breeder": ("Plant Breeders' Right", "https://www.wikidata.org/wiki/Q695112"),
    "plant breeder's rights": ("Plant Breeders' Right", "https://www.wikidata.org/wiki/Q695112"),
    "all intellectual property rights": ("All Intellectual Property Rights", "https://www.wikidata.org/wiki/Q108855835"),
    "any dispute related to intellectual property": ("All Intellectual Property Rights", "https://www.wikidata.org/wiki/Q108855835")
}

# --- 2. HTML CLEANING & EXTRACTION FUNCTIONS ---

def normalize_text_chars(text):
    """
    Normalizes smart quotes, dashes, and non-breaking spaces before processing.
    """
    if not text:
        return ""
    replacements = {
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-",
        "\u00a0": " "
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def clean_html_fragment(soup_element):
    """
    Converts an HTML soup element into plain text for the JSON fields.
    Fixed: Prevents concatenated words by ensuring spacing during tag replacement.
    """
    if not soup_element:
        return ""
    
    # 1. Pre-normalize text (smart quotes, etc) before parsing to avoid regex issues later
    raw_str = normalize_text_chars(str(soup_element))
    fragment = BeautifulSoup(raw_str, 'html.parser')

    # Remove non-content tags
    for tag in fragment(['script', 'style', 'button', 'svg', 'figure', 'img', 'iframe']):
        tag.decompose()

    # 2. Convert links with smart spacing
    # Issue #1 Fix: "see[Link]" -> "see [Link]"
    for a in fragment.find_all('a', href=True):
        text = a.get_text(strip=True)
        url = a['href']
        if text and url:
            # Check previous sibling for lack of whitespace
            prev = a.previous_sibling
            prefix = ""
            if prev and isinstance(prev, str) and prev.strip() and not prev.endswith(' '):
                prefix = " "
                
            a.replace_with(f"{prefix}[{text}]({url})")

    # 3. Flatten bold/strong/em/i with smart spacing
    for b in fragment.find_all(['strong', 'b', 'em', 'i']):
        text = b.get_text(strip=True)
        if text:
            # Check previous sibling for lack of whitespace
            prev = b.previous_sibling
            prefix = ""
            if prev and isinstance(prev, str) and prev.strip() and not prev.endswith(' '):
                prefix = " "
            b.replace_with(f"{prefix}{text}")

    # Convert list items to bulleted text
    for li in fragment.find_all('li'):
        text = li.get_text(strip=True)
        if text:
            li.replace_with(f"\n* {text}")

    # Get text and clean up whitespace
    # Using separator=" " helps prevent run-ons between block elements if not handled above
    text = fragment.get_text(separator="\n\n")

    # 4. Post-processing cleanup for punctuation spacing
    # Fix: "and,for" -> "and, for"
    text = re.sub(r',([a-zA-Z])', r', \1', text) 
    # Fix: "word.Next" -> "word. Next" (conservative)
    text = re.sub(r'\.([A-Z])', r'. \1', text)

    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def parse_html_to_blocks(html_content):
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
                if current_elements:
                    clean_text = ""
                    for el in current_elements:
                        clean_text += clean_html_fragment(el) + "\n"
                    if clean_text.strip():
                        blocks[current_header] = clean_text.strip()
                
                # Issue #2 Fix: "Whos involved?" -> "Who's involved?"
                # 1. Get raw text
                raw_header = child.get_text(strip=True)
                # 2. Normalize smart quotes FIRST (e.g. ’ -> ')
                norm_header = normalize_text_chars(raw_header)
                # 3. Lowercase
                clean_header_key = norm_header.lower()
                # 4. Regex allows word chars, whitespace, question mark, AND apostrophe
                clean_header_key = re.sub(r'[^\w\s\?\'\-]', '', clean_header_key).strip()
                
                current_header = clean_header_key
                current_elements = []
            
            elif child.name and child.name not in ['script', 'style', 'button', 'svg', 'form']:
                 current_elements.append(child)
        
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
    url_match = re.search(r'PageURL:\s*\"\[(.*?)\]', md_content)
    if url_match:
        page_url = url_match.group(1).strip()
        for row in csv_rows:
            csv_url = row.get('Canonical-url', '').strip()
            if csv_url == page_url or (csv_url and page_url.endswith(csv_url.split('/')[-1])):
                return row

    udid_match = re.search(r'([A-Z]\d{4})', filename)
    if udid_match:
        target_udid = udid_match.group(1)
        for row in csv_rows:
            if row.get('UDID') == target_udid:
                return row

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

def clean_markdown_artifacts(text):
    """
    Strictly cleans Markdown syntax artifacts (*, **, _, __).
    Preserves list bullets if they appear at the start of a line.
    """
    if not text: return ""
    
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        is_list_item = stripped_line.startswith('* ') or stripped_line.startswith('- ')
        
        # 1. Remove bold/italic markers (**, __)
        line = re.sub(r'\*\*|__', '', line)
        
        # 2. Remove single * or _
        # If it's a list item, protect the first character
        if is_list_item:
            # Separate the bullet from content
            if stripped_line.startswith('* '):
                content = line[line.find('*')+1:]
                # Clean content, add bullet back
                content = content.replace('*', '').replace('_', '')
                line = "* " + content
            else:
                # Starts with -, clean internal * and _
                line = line.replace('*', '').replace('_', '')
        else:
            # Not a list, remove all * and _
            line = line.replace('*', '').replace('_', '')
            
        cleaned_lines.append(line)
        
    text = "\n".join(cleaned_lines)
    
    # Final cleanup of double spaces created by deletions
    text = re.sub(r' +', ' ', text)
    
    return text

def clean_text_retain_formatting(text, strip_images=False):
    if not text: return ""
    
    # Use global normalize function
    text = normalize_text_chars(text)
    
    text = text.replace("...", "...") # standardize ellipsis if needed

    # Aggressively remove Markdown images [!alt](url) or ![]()
    if strip_images:
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        
    text = text.replace('\r', '')
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in text.split('\n')]
    text = "\n".join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def extract_links_and_clean(text):
    """
    Extracts Markdown links [text](url), returns the plain text 'text'
    (where the link is replaced by just its text), and returns a list of link objects.
    Also handles relative URLs which were previously breaking the regex.
    """
    if not text:
        return text, []

    # First, strip any Markdown images to prevent "broken" image code in text
    # Matches ![alt](url)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)

    found_links = []

    def replace_fn(match):
        name = match.group(1).strip()
        url = match.group(2).strip()
        
        if url and name:
            # Construct full URL for relative paths if needed, though strictly we just store what's there
            # If valid URL or path
            found_links.append({
                "@type": "WebPage",
                "url": url,
                "name": name
            })
        
        # Return JUST the name (Plain Text)
        return name 

    # Robust regex for links: [text](url)
    # Allows for relative URLs (does not enforce http) and loose whitespace
    # Non-greedy match for content inside brackets
    cleaned_text = re.sub(r'\[\s*([^\]]+?)\s*\]\s*\(\s*([^\)]+?)\s*\)', replace_fn, text, flags=re.DOTALL)
    
    # Final pass to strip bold/italic markdown artifacts from the text
    cleaned_text = clean_markdown_artifacts(cleaned_text)
    
    return cleaned_text.strip(), found_links

def convert_csv_date(date_str):
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return datetime.now().strftime("%Y-%m-%d")

def generate_citations_from_csv(metadata_row):
    citations = []
    raw_ip_rights = metadata_row.get('Relevant-ip-right', '')
    if not raw_ip_rights: return citations
    
    cleaned_rights_str = raw_ip_rights.replace('"', '').replace("'", "").lower().strip()
    rights_to_process = []
    
    if "any dispute related to intellectual property" in cleaned_rights_str or "all intellectual property rights" in cleaned_rights_str:
        rights_to_process = ["trade mark", "patent", "design", "pbr", "copyright"]
    else:
        rights_to_process = [r.strip() for r in cleaned_rights_str.split(',') if r.strip()]
    
    added_urls = set()
    for right in rights_to_process:
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
    
    if base_obj.get("@type") == "Organization":
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
    seen_urls = set()
    
    for right in rights_list:
        match_data = None
        if right in IP_TOPIC_MAP:
            match_data = IP_TOPIC_MAP[right]
        else:
            if "design" in right:
                match_data = IP_TOPIC_MAP["design"]
            elif "plant breeder" in right or "pbr" in right:
                match_data = IP_TOPIC_MAP["pbr"]
        
        if match_data:
            name, url = match_data
            if url not in seen_urls:
                about_entities.append({
                    "@type": "Thing",
                    "name": name,
                    "sameAs": url
                })
                seen_urls.add(url)
    
    if len(about_entities) == 1: 
        return about_entities[0]
    elif len(about_entities) > 1: 
        return about_entities
    else: 
        return {
            "@type": "Thing", 
            "name": "All Intellectual Property Rights",
            "sameAs": "https://www.wikidata.org/wiki/Q108855835"
        }

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
        raw_text = blocks[target_key].strip()
        parts = re.split(r'(?:^|\n)\* ', raw_text)
        
        if parts[0].strip():
            clean_step, links = extract_links_and_clean(parts[0].strip())
            collected_links.extend(links)
            steps.append({
                 "@type": "HowToStep",
                 "name": "xXx_PLACEHOLDER_xXx", 
                 "text": clean_step
            })
        
        for part in parts[1:]:
            if not part.strip(): continue
            sub_segments = re.split(r'\n{2,}', part)
            for segment in sub_segments:
                if not segment.strip(): continue
                clean_step, links = extract_links_and_clean(segment.strip())
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
                formatted_text = clean_text_retain_formatting(step_text, strip_images=True)
                clean_step, links = extract_links_and_clean(formatted_text)
                collected_links.extend(links)
                steps.append({"@type": "HowToStep", "name": "xXx_PLACEHOLDER_xXx", "text": clean_step})
        else:
            paragraphs = [p.strip() for p in raw_text.split('\n\n') if p.strip()]
            for p in paragraphs:
                if "see also" in p.lower(): continue
                formatted_text = clean_text_retain_formatting(p, strip_images=True)
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
    
    pub_date_val = convert_csv_date(metadata_row.get('Publication-date'))
    last_updated_val = convert_csv_date(metadata_row.get('Last-updated'))

    page_url = metadata_row.get('Canonical-url', f"https://ipfirstresponse.ipaustralia.gov.au/options/{udid}")

    master_links = [] 

    # --- UPDATED: WEBPAGE DESCRIPTION (STRICTLY FROM CSV) ---
    csv_desc_raw = metadata_row.get('Description', '').strip()
    
    if not csv_desc_raw or csv_desc_raw.lower() == 'null':
        webpage_description = "xXx_Err-PLACEHOLDER_xXx"
    else:
        # Clean the CSV description too
        webpage_description, d_links = extract_links_and_clean(
            clean_text_retain_formatting(csv_desc_raw, strip_images=True)
        )
        master_links.extend(d_links)
        if not webpage_description:
            webpage_description = "xXx_Err-PLACEHOLDER_xXx"

    # --- UPDATED: SERVICE DESCRIPTION (STRICTLY FROM "WHAT IS IT?") ---
    service_description = ""
    # Find key containing "what is it"
    what_is_it_key = next((k for k in blocks.keys() if "what is it" in k.lower()), None)
    
    if what_is_it_key:
        raw_service_desc = blocks[what_is_it_key]
        # Extract content and links
        clean_service_desc, desc_links = extract_links_and_clean(raw_service_desc)
        master_links.extend(desc_links)
        service_description = clean_service_desc
    else:
        service_description = ""

    # --- ENTITY CONSTRUCTION ---
    service_id = "#the-service"
    has_provider = True
    
    archetype = metadata_row.get('Archectype') 
    
    if not archetype:
        service_type = "xXx_Err-PLACEHOLDER_xXx"
        has_provider = True 
    else:
        if "Self-Help" in archetype:
            # OLD: service_type, has_provider = "HowTo", False 
            # NEW: Change to Article, but keep provider False
            service_type, has_provider = "Article", False 
        elif "Government Service" in archetype:
            service_type = "GovernmentService"
        elif "Commercial" in archetype:
            service_type = "Service"
        elif "Non-Government" in archetype:
            service_type = "Service" 
        else:
            service_type = "xXx_Err-PLACEHOLDER_xXx"

    main_obj = {
        "@id": service_id,
        "@type": service_type,
        "name": title,
        "description": service_description, 
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
        provider_name_csv = metadata_row.get('Provider')
        if not provider_name_csv:
            provider_name_csv = "xXx_Err-PLACEHOLDER_xXx"
            
        provider_obj = resolve_provider(provider_name_csv, archetype_hint=(archetype if archetype else ""))
        provider_obj["name"] = provider_name_csv

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
        faqs, f_links = extract_dynamic_content_html(blocks, main_description_key=what_is_it_key)
        master_links.extend(f_links)
    else:
        for h, c in blocks.items():
            if h in ["intro", "description", "see also", "step"]: continue
            if what_is_it_key and h == what_is_it_key: continue

            q_name = h.capitalize() + ("?" if not h.endswith('?') else "")
            
            clean_ans, links = extract_links_and_clean(clean_text_retain_formatting(c, strip_images=True))
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
        "@id": f"{page_url}#webpage",
        "headline": title,
        "alternativeHeadline": metadata_row.get('Overtitle', ''),
        "description": webpage_description,
        "url": page_url,
        "identifier": {"@type": "PropertyValue", "propertyID": "UDID", "value": udid},
        "inLanguage": "en-AU",
        # --- PROVENANCE DATA ---
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "copyrightYear": datetime.now().strftime("%Y"), # Or hardcode "2025"
        "copyrightHolder": {
            "@id": "https://www.ipaustralia.gov.au"
        },
        "creditText": "Source: IP Australia - IP First Response",
        # --- METADATA PROVENANCE ---
        "sdPublisher": {
            "@type": "GovernmentOrganization",
            "name": "IP Australia"
        },
        "sdDatePublished": pub_date_val, # Reusing the pub date, or use datetime.now().strftime("%Y-%m-%d") for generation date
        "sdLicense": "https://creativecommons.org/licenses/by/4.0/",
        "datePublished": pub_date_val,
        "dateModified": last_updated_val,
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

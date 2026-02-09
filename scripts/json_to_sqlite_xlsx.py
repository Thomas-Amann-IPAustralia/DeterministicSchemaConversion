import json
import os
import glob
import pandas as pd
import tiktoken
import re
from datetime import datetime

# Configuration
# Get the directory where this script resides (e.g., /repo/scripts)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Define Repo Root (Go up one level from /scripts)
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

# Define Input/Output paths relative to the Repo Root
INPUT_FOLDER = os.path.join(REPO_ROOT, "JSON_output-enriched")
OUTPUT_FILE = os.path.join(REPO_ROOT, "SQLite_Structure.xlsx")
ENCODING_MODEL = "cl100k_base"  # Standard GPT-4 encoding

# Initialize Tokenizer
tokenizer = tiktoken.get_encoding(ENCODING_MODEL)

def count_tokens(text):
    if not text or text == "Null":
        return 0
    return len(tokenizer.encode(str(text)))

def clean_text(text):
    if text is None:
        return "Null"
    # Remove excessive whitespace
    return " ".join(str(text).split())

def get_nested(data, path, default="Null"):
    """Safely get nested dictionary values."""
    keys = path.split('.')
    val = data
    for key in keys:
        if isinstance(val, dict) and key in val:
            val = val[key]
        elif isinstance(val, list) and key.isdigit():
             # Handle list index if needed
             idx = int(key)
             if idx < len(val):
                 val = val[idx]
             else:
                 return default
        else:
            return default
    return val if val is not None else default

def normalize_url(url):
    """Normalize URL for comparison."""
    if not url or url == "Null":
        return ""
    return url.strip().rstrip('/').lower()

def extract_hyperlinks(text):
    """Extract Markdown and HTML links from text."""
    if not text or text == "Null":
        return []
    # Markdown links [text](url)
    md_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text)
    # HTML links <a href="url">text</a>
    html_links = re.findall(r'<a\s+(?:[^>]*?\s+)?href="([^"]*)"[^>]*>(.*?)</a>', text)
    
    results = []
    for txt, url in md_links:
        results.append((txt, url))
    for url, txt in html_links:
        results.append((txt, url))
    return results

def process_json_files():
    # Data containers
    data_primary = []
    data_influences = []
    data_linksto = []
    data_howto = []
    data_faq = []
    data_semantic = []

    # Map for internal linking: Normalized URL -> (UDID, Headline_Alt)
    url_map = {}

    json_files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
    print(f"Found {len(json_files)} JSON files.")

    # --- PASS 1: Build URL Map for Internal Links ---
    raw_json_cache = {} # Cache content to avoid re-reading
    
    for filepath in json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = json.load(f)
                raw_json_cache[filepath] = content
                
                # Extract identifiers for mapping
                udid = get_nested(content, "identifier.value")
                headline_alt = get_nested(content, "alternativeHeadline")
                url = get_nested(content, "url")
                
                if udid != "Null" and url != "Null":
                    url_map[normalize_url(url)] = (udid, headline_alt)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")

    # --- PASS 2: Process Data ---
    for filepath, data in raw_json_cache.items():
        udid = get_nested(data, "identifier.value")
        headline_alt = get_nested(data, "alternativeHeadline")
        headline = get_nested(data, "headline")
        
        # 1. PRIMARY SHEET
        primary_row = {
            "UDID": udid,
            "Headline": headline,
            "Headline_Alt": headline_alt,
            "Description": clean_text(get_nested(data, "description")),
            "Stable_URL": get_nested(data, "url"),
            "Date_Published": get_nested(data, "datePublished"),
            "Date_Modified": get_nested(data, "dateModified"),
            "Geographic_Area": get_nested(data, "audience.geographicArea.name"),
            "IP_Right_Name": get_nested(data, "about.name"),
            "IP_Right_Wikidata_URL": get_nested(data, "about.sameAs"),
            "Service_Type": "Null",
            "Service_Name": "Null",
            "HowTo_Name": "Null",
            "Service_Provider": get_nested(data, "publisher.name"),
            "JSON_Raw": json.dumps(data),
            "Json_Raw_Token_Count": count_tokens(json.dumps(data))
        }

        # Extract Service/HowTo names from mainEntity
        main_entities = data.get("mainEntity", [])
        if isinstance(main_entities, dict): main_entities = [main_entities]
        
        for entity in main_entities:
            e_type = entity.get("@type")
            if e_type == "Service" or e_type == "Article":
                primary_row["Service_Type"] = e_type
                primary_row["Service_Name"] = entity.get("name", "Null")
            if e_type == "HowTo":
                primary_row["HowTo_Name"] = entity.get("name", "Null")

        data_primary.append(primary_row)

        # 2. INFLUENCES SHEET (Citations & Related Links)
        # Priority 1: Citation, Priority 2: RelatedLink
        citations = data.get("citation", [])
        if isinstance(citations, dict): citations = [citations]
        
        related = data.get("relatedLink", [])
        if isinstance(related, dict): related = [related]

        # Process Citations
        for item in citations:
            data_influences.append({
                "UDID": udid,
                "Headline_Alt": headline_alt,
                "Influence_Priority": 1,
                "Influence_ID": "Null", # Not specified in source, leaving Null or could use index
                "Influence_URL": item.get("url", "Null")
            })
            
        # Process Related Links
        for item in related:
            data_influences.append({
                "UDID": udid,
                "Headline_Alt": headline_alt,
                "Influence_Priority": 2,
                "Influence_ID": "Null",
                "Influence_URL": item.get("url", "Null")
            })

        # 3. LINKS TO SHEET (Scan descriptions/text for links)
        # Scan 'description' and mainEntity texts
        text_to_scan = [get_nested(data, "description")]
        for entity in main_entities:
            text_to_scan.append(entity.get("description", ""))
            text_to_scan.append(entity.get("text", ""))
            # Also scan HowTo steps
            if entity.get("@type") == "HowTo":
                steps = entity.get("step", [])
                for s in steps:
                    text_to_scan.append(s.get("text", ""))
        
        full_scan_text = " ".join([str(t) for t in text_to_scan if t])
        found_links = extract_hyperlinks(full_scan_text)

        # Deduplicate links by URL
        seen_links = set()
        
        for txt, url in found_links:
            norm_url = normalize_url(url)
            if norm_url in seen_links: continue
            seen_links.add(norm_url)

            is_internal = "Null"
            dest_headline = "Null"
            dest_udid = "Null"

            # Check if internal
            if norm_url in url_map:
                is_internal = "TRUE"
                dest_udid, dest_headline = url_map[norm_url]
            elif "ipfirstresponse.ipaustralia.gov.au" in norm_url:
                 is_internal = "TRUE" # Internal domain but maybe not in this dataset
            else:
                is_internal = "FALSE"

            data_linksto.append({
                "UDID": udid,
                "Headline_Alt": headline_alt,
                "Destination_URL": url,
                "Destination_Headline_alt": dest_headline,
                "Internal_Destination": is_internal,
                "Internal_Destination_UDID": dest_udid
            })

        # 4. HOWTO SHEET
        for entity in main_entities:
            if entity.get("@type") == "HowTo":
                steps = entity.get("step", [])
                for idx, step in enumerate(steps, 1):
                    data_howto.append({
                        "UDID": udid,
                        "Headline_Alt": headline_alt,
                        "Step_Number": idx,
                        "Step_Name": step.get("name", "Null"),
                        "Step_Description": clean_text(step.get("text", "Null"))
                    })

        # 5. FAQ SHEET
        faq_mapping = {
            "benefits": "What_are_the_benefits",
            "risks": "What_are_the_risks",
            "cost": "What_might_the_cost_be",
            "time": "How_much_time_might_be_involved",
            "who can use": "Who_can_use_this",
            "involved": "Whos_involved",
            "how much is this used": "How_much_is_this_used",
            "outcomes": "What_are_the_possible_outcomes"
        }
        
        for entity in main_entities:
            if entity.get("@type") == "FAQPage":
                row = {
                    "UDID": udid,
                    "Headline_Alt": headline_alt,
                    "What_are_the_benefits": "Null",
                    "What_are_the_risks": "Null",
                    "What_might_the_cost_be": "Null",
                    "How_much_time_might_be_involved": "Null",
                    "Who_can_use_this": "Null",
                    "Whos_involved": "Null",
                    "How_much_is_this_used": "Null",
                    "What_are_the_possible_outcomes": "Null"
                }
                
                questions = entity.get("mainEntity", [])
                for q in questions:
                    q_name = q.get("name", "").lower()
                    ans = q.get("acceptedAnswer", {}).get("text", "Null")
                    
                    # Fuzzy match question to column
                    matched = False
                    for key, col in faq_mapping.items():
                        if key in q_name:
                            row[col] = clean_text(ans)
                            matched = True
                            break
                    
                    # Fallback for exact matches if simple substring fails or to be specific
                    # (Logic above covers most based on standard schema patterns seen in samples)
                
                data_faq.append(row)

        # 6. SEMANTIC SHEET (Chunking)
        # Aggregate all relevant text
        semantic_text = [
            headline, 
            headline_alt, 
            get_nested(data, "description")
        ]
        
        # Add HowTo and FAQ text
        for entity in main_entities:
            if entity.get("@type") == "HowTo":
                for s in entity.get("step", []):
                    semantic_text.append(s.get("name", ""))
                    semantic_text.append(s.get("text", ""))
            elif entity.get("@type") == "FAQPage":
                for q in entity.get("mainEntity", []):
                    semantic_text.append(q.get("name", ""))
                    semantic_text.append(q.get("acceptedAnswer", {}).get("text", ""))
            elif entity.get("@type") == "Article" or entity.get("@type") == "Service":
                 semantic_text.append(entity.get("description", ""))

        full_text = " ".join([str(x) for x in semantic_text if x and x != "Null"])
        
        # Simple chunking logic (approx 300 words / 400-500 tokens)
        # For robustness, we stick to a character limit that approximates this if logic is simple,
        # but here is a simple word grouper.
        words = full_text.split()
        chunk_size = 300
        chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            data_semantic.append({
                "UDID": udid,
                "Headline_Alt": headline_alt,
                "Chunk_ID": f"{udid}_{i}",
                "Chunk_Token_Count": count_tokens(chunk),
                "Chunk_Text": chunk,
                "Chunk_Embedding": "Null" # Placeholder as requested
            })

    # --- WRITE TO EXCEL ---
    # Helper to enforce "Null" on empty cells
    def fill_defaults(df_list, columns):
        if not df_list:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(df_list)
        # Ensure all expected columns exist
        for col in columns:
            if col not in df.columns:
                df[col] = "Null"
        # Fill NaN/None with "Null"
        df = df.fillna("Null")
        # Ensure string "Null" is used, not empty string
        df = df.replace(r'^\s*$', 'Null', regex=True)
        return df[columns]

    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        
        # 1. Primary
        cols_primary = ["UDID", "Headline", "Headline_Alt", "Description", "Stable_URL", "Date_Published", 
                        "Date_Modified", "Geographic_Area", "IP_Right_Name", "IP_Right_Wikidata_URL", 
                        "Service_Type", "Service_Name", "HowTo_Name", "Service_Provider", "JSON_Raw", "Json_Raw_Token_Count"]
        df_p = fill_defaults(data_primary, cols_primary)
        df_p.to_excel(writer, sheet_name='Primary', index=False)

        # 2. Influences
        cols_inf = ["UDID", "Headline_Alt", "Influence_Priority", "Influence_ID", "Influence_URL"]
        df_i = fill_defaults(data_influences, cols_inf)
        df_i.to_excel(writer, sheet_name='Influences', index=False)

        # 3. LinksTo
        cols_link = ["UDID", "Headline_Alt", "Destination_URL", "Destination_Headline_alt", 
                     "Internal_Destination", "Internal_Destination_UDID"]
        df_l = fill_defaults(data_linksto, cols_link)
        df_l.to_excel(writer, sheet_name='LinksTo', index=False)

        # 4. HowTo
        cols_how = ["UDID", "Headline_Alt", "Step_Number", "Step_Name", "Step_Description"]
        df_h = fill_defaults(data_howto, cols_how)
        df_h.to_excel(writer, sheet_name='HowTo', index=False)

        # 5. FAQ
        cols_faq = ["UDID", "Headline_Alt", "What_are_the_benefits", "What_are_the_risks", 
                    "What_might_the_cost_be", "How_much_time_might_be_involved", "Who_can_use_this", 
                    "Whos_involved", "How_much_is_this_used", "What_are_the_possible_outcomes"]
        df_f = fill_defaults(data_faq, cols_faq)
        df_f.to_excel(writer, sheet_name='FAQ', index=False)

        # 6. Semantic
        cols_sem = ["UDID", "Headline_Alt", "Chunk_ID", "Chunk_Token_Count", "Chunk_Text", "Chunk_Embedding"]
        df_s = fill_defaults(data_semantic, cols_sem)
        df_s.to_excel(writer, sheet_name='Semantic', index=False)

    print(f"Successfully created {OUTPUT_FILE}")

if __name__ == "__main__":
    process_json_files()

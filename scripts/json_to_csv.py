import json
import yaml
import glob
import os
import argparse
import pandas as pd
import tiktoken
import re
from jsonpath_ng.ext import parse
from typing import Any, List, Dict

# --- Global Cache & Registry ---
FILE_CACHE = {
    "md": {},   # Map: {'B1020': 'full_path_to_file.md'}
    "html": {}  # Map: {'B1020': 'full_path_to_file.html'}
}
URL_REGISTRY = {} # Map: {'https://ipfirstresponse...': 'B1020'}
JSONPATH_CACHE = {}
TOKENIZER = None

# --- Setup & Helpers ---

def setup_tokenizer():
    global TOKENIZER
    try:
        TOKENIZER = tiktoken.get_encoding("cl100k_base")
    except Exception as e:
        print(f"⚠️ Warning: Tiktoken failed to load ({e}). Token counts will be 0.")

def count_tokens(text):
    if not text or not TOKENIZER: return 0
    return len(TOKENIZER.encode(str(text)))

def pre_scan_files(source_dir, md_dir, html_dir):
    """
    1. Maps UDIDs to their specific MD/HTML filenames.
    2. Builds a URL -> UDID registry from all JSONs for internal linking.
    """
    print("⏳ Pre-scanning files to build registries...")
    
    # Scan MD/HTML
    for f_type, path in [("md", md_dir), ("html", html_dir)]:
        if path and os.path.exists(path):
            for file_path in glob.glob(os.path.join(path, "*")):
                # Assuming filename starts with UDID (e.g., "B1020 - Name.md")
                filename = os.path.basename(file_path)
                # Extract UDID (first sequence of chars before space or dash)
                udid = filename.split()[0].strip() 
                FILE_CACHE[f_type][udid] = file_path

    # Scan JSONs for URL Registry
    json_files = glob.glob(os.path.join(source_dir, "*.json"))
    for jf in json_files:
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Extract UDID and URL
                udid_match = parse("identifier.value").find(data)
                url_match = parse("url").find(data)
                
                if udid_match and url_match:
                    udid = udid_match[0].value
                    url = url_match[0].value
                    URL_REGISTRY[url] = udid
        except:
            continue
            
    print(f"   - Mapped {len(FILE_CACHE['md'])} MD files.")
    print(f"   - Mapped {len(URL_REGISTRY)} internal URLs.")

# --- Logic Functions ---

def logic_derive_service_provider(value, row_context, root_data):
    """Implements: IF Service_Type = Article THEN Self-service ELSE serviceOperator.name"""
    try:
        entities = root_data.get("mainEntity", [])
        if not entities: return "Unknown"
        
        service_type = entities[0].get("@type", "")
        if service_type == "Article":
            return "Self-service"
        else:
            return entities[0].get("serviceOperator", {}).get("name", "Unknown")
    except:
        return "Unknown"

def logic_check_is_internal_link(url, row_context, root_data):
    if not url: return "No"
    return "Yes" if "ipfirstresponse" in str(url) else "No"

def logic_lookup_internal_udid(url, row_context, root_data):
    if not url: return "Null"
    clean_url = str(url).rstrip('/')
    return URL_REGISTRY.get(clean_url, URL_REGISTRY.get(clean_url + '/', "Null"))

def logic_read_file_content(udid, file_type):
    path = FILE_CACHE[file_type].get(udid)
    if not path: return "FILE_NOT_FOUND"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {str(e)}"

# Wrappers
def logic_read_html_file(udid, *args): return logic_read_file_content(udid, "html")
def logic_read_md_file(udid, *args): return logic_read_file_content(udid, "md")
def logic_count_html_tokens(udid, *args): return count_tokens(logic_read_file_content(udid, "html"))
def logic_count_md_tokens(udid, *args): return count_tokens(logic_read_file_content(udid, "md"))
def logic_dump_json_string(root_data, *args): return json.dumps(root_data)
def logic_count_json_tokens(root_data, *args): return count_tokens(json.dumps(root_data))

# --- Row Generator Functions (One Input -> Multiple Rows) ---

def logic_generate_semantic_rows(root_data, *args):
    """
    Generates multiple chunk rows from the associated Markdown file.
    Splits by '###' headers.
    """
    rows = []
    
    # 1. Get Basic Info
    udid = root_data.get("identifier", {}).get("value", "UNKNOWN")
    headline = root_data.get("headline", "")
    alt_headline = root_data.get("alternativeHeadline", "")
    description = root_data.get("description", "")
    
    # 2. Construct Context Prepend
    context_prepend = f"{headline}\n{alt_headline}\n{description}"
    
    # 3. Read Markdown
    md_content = logic_read_file_content(udid, "md")
    if not md_content or md_content.startswith("FILE_NOT_FOUND") or md_content.startswith("ERROR"):
        # Fallback if no MD found
        return [{
            "UDID": udid,
            "Headline_Alt": alt_headline,
            "Chunk_ID": f"{udid}_ERROR",
            "Chunk_Token_Count": 0,
            "Chunk_Text": "Markdown file not found.",
            "Chunk_Embedding": None,
            "Chunk_Context_Prepend": context_prepend
        }]

    # 4. Clean Markdown Metadata & Split
    parts = re.split(r'(?=^### )', md_content, flags=re.MULTILINE)
    
    chunks = []
    for i, part in enumerate(parts):
        text = part.strip()
        if not text: continue
        
        # Skip top metadata block if present
        if i == 0:
            lines = text.split('\n')
            clean_lines = [l for l in lines if not l.startswith("PageURL:") and not l.startswith("## ") and not l.startswith("# ")]
            text = "\n".join(clean_lines).strip()
            if not text: continue

        full_chunk_text = f"{context_prepend}\n{text}"
        chunk_id = f"{udid}_{len(chunks)+1:02d}"
        
        rows.append({
            "UDID": udid,
            "Headline_Alt": alt_headline,
            "Chunk_ID": chunk_id,
            "Chunk_Token_Count": count_tokens(full_chunk_text),
            "Chunk_Text": full_chunk_text,
            "Chunk_Embedding": None,
            "Chunk_Context_Prepend": context_prepend
        })
        chunks.append(chunk_id) # Track count
        
    return rows


LOGIC_FUNCTIONS = {
    "derive_service_provider": logic_derive_service_provider,
    "check_is_internal_link": logic_check_is_internal_link,
    "lookup_internal_udid": logic_lookup_internal_udid,
    "read_html_file": logic_read_html_file,
    "count_html_tokens": logic_count_html_tokens,
    "read_md_file": logic_read_md_file,
    "count_md_tokens": logic_count_md_tokens,
    "dump_json_string": logic_dump_json_string,
    "count_json_tokens": logic_count_json_tokens
}

ROW_GENERATORS = {
    "generate_semantic_rows": logic_generate_semantic_rows
}

# --- Core Processing ---

def get_value(datum, selector, logic_name=None, row_context=None, root_data=None):
    """Extracts value using JSONPath or Custom Logic"""
    val = None
    
    # 1. CONST Handling
    if selector and str(selector).startswith("const:"):
        return selector.replace("const:", "")

    # 2. Path Extraction
    if selector:
        try:
            if selector.startswith("parent:"):
                clean_path = selector.replace("parent:", "")
                target = root_data
            else:
                target = datum
                clean_path = selector

            if clean_path not in JSONPATH_CACHE:
                JSONPATH_CACHE[clean_path] = parse(clean_path)
            
            matches = JSONPATH_CACHE[clean_path].find(target)
            if matches:
                val = matches[0].value
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
        except Exception as e:
            pass

    # 3. Logic Application
    if logic_name and logic_name in LOGIC_FUNCTIONS:
        input_val = val if val is not None else datum
        val = LOGIC_FUNCTIONS[logic_name](input_val, row_context, root_data)

    return val

def process_file(filepath, config):
    with open(filepath, 'r', encoding='utf-8') as f:
        root_data = json.load(f)
    
    file_results = {}
    
    for table_name, settings in config['tables'].items():
        rows = []
        
        # Check for Row Generator
        if "row_generator" in settings:
            generator_name = settings["row_generator"]
            if generator_name in ROW_GENERATORS:
                generated_rows = ROW_GENERATORS[generator_name](root_data)
                rows.extend(generated_rows)
            else:
                print(f"❌ Unknown generator: {generator_name}")
        
        else:
            # Standard Processing
            root_path = settings['root_path']
            
            if root_path == "$":
                items = [root_data]
            else:
                if root_path not in JSONPATH_CACHE:
                    JSONPATH_CACHE[root_path] = parse(root_path)
                items = [m.value for m in JSONPATH_CACHE[root_path].find(root_data)]
                
            for item in items:
                row = {}
                for col, rules in settings['columns'].items():
                    path = rules if isinstance(rules, str) else rules.get('path')
                    logic = rules.get('logic') if isinstance(rules, dict) else None
                    
                    row[col] = get_value(item, path, logic, item, root_data)
                rows.append(row)
            
        file_results[table_name] = rows
        
    return file_results

# --- Main Execution ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--md-source", default="")
    parser.add_argument("--html-source", default="")
    args = parser.parse_args()

    setup_tokenizer()
    pre_scan_files(args.source, args.md_source, args.html_source)
    
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    if not os.path.exists(args.output):
        os.makedirs(args.output)
        
    all_data = {t: [] for t in config['tables']}
    json_files = glob.glob(os.path.join(args.source, "*.json"))
    
    print(f"🚀 Processing {len(json_files)} files...")
    
    for jf in json_files:
        try:
            res = process_file(jf, config)
            for t, rows in res.items():
                all_data[t].extend(rows)
        except Exception as e:
            print(f"❌ Error in {jf}: {e}")
            import traceback
            traceback.print_exc()
            
    print("💾 Saving data...")
    for t, data in all_data.items():
        if data:
            df = pd.DataFrame(data)
            
            # Ensure columns and order
            if "columns" in config['tables'][t]:
                cols = list(config['tables'][t]['columns'].keys())
                for c in cols:
                    if c not in df.columns: df[c] = None
                df = df[cols]
            
            # 1. Save as Excel (Added per request)
            xlsx_path = os.path.join(args.output, config['tables'][t]['filename'].replace('.csv', '.xlsx'))
            print(f"   - Saving {xlsx_path}...")
            # Requires 'openpyxl' installed
            try:
                df.to_excel(xlsx_path, index=False)
            except Exception as e:
                 print(f"   ⚠️ Failed to save Excel (check if openpyxl is installed): {e}")

            # 2. Save as CSV
            csv_path = os.path.join(args.output, config['tables'][t]['filename'])
            print(f"   - Saving {csv_path}...")
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')

import json
import yaml
import glob
import os
import argparse
import pandas as pd
import tiktoken
from jsonpath_ng.ext import parse
from typing import Any, List, Dict
import time

# --- Global Cache ---
# We store directory listings here so we don't scan the hard drive 1000s of times
FILE_CACHE = {
    "md": [],
    "html": []
}

# We store compiled JSON paths here to save CPU
JSONPATH_CACHE = {}

TOKENIZER = None

# --- Setup & Optimization ---

def setup_tokenizer():
    global TOKENIZER
    print("⏳ Initializing Tiktoken (this may download model data)...")
    try:
        TOKENIZER = tiktoken.get_encoding("cl100k_base")
        print("✅ Tiktoken initialized.")
    except Exception as e:
        print(f"⚠️ Warning: Tiktoken failed to load ({e}). Token counts will be 0.")

def pre_scan_directories(md_path, html_path):
    """Scans directories ONCE and stores filenames in memory."""
    print("⏳ Pre-scanning source directories...")
    
    if md_path and os.path.exists(md_path):
        FILE_CACHE["md"] = os.listdir(md_path)
        print(f"   - Found {len(FILE_CACHE['md'])} Markdown files.")
    
    if html_path and os.path.exists(html_path):
        FILE_CACHE["html"] = os.listdir(html_path)
        print(f"   - Found {len(FILE_CACHE['html'])} HTML files.")

def get_jsonpath(path_str):
    """Returns a compiled JSONPath expression from cache."""
    if path_str not in JSONPATH_CACHE:
        try:
            JSONPATH_CACHE[path_str] = parse(path_str)
        except Exception as e:
            print(f"❌ Invalid JSONPath: {path_str}")
            return None
    return JSONPATH_CACHE[path_str]

# --- Helper: Fast File Lookup ---

def find_file_by_udid_fast(udid, cache_key, folder, extension):
    """
    Looks up file in the memory cache instead of the disk.
    """
    if not udid or not folder:
        return ""
    
    # Access the cached list of files
    file_list = FILE_CACHE.get(cache_key, [])
    
    # Fast filtering in memory
    # We assume the file STARTS with the UDID (e.g., "B1000 - ...")
    for fname in file_list:
        if fname.startswith(udid) and fname.endswith(extension):
            full_path = os.path.join(folder, fname)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except:
                return ""
    return ""

def count_tokens(text):
    if not text or TOKENIZER is None:
        return 0
    try:
        return len(TOKENIZER.encode(text))
    except:
        return 0

# --- Logic Functions ---

def get_udid(root_data):
    return root_data.get('identifier', {}).get('value')

def logic_get_raw_md(value, row_context, root_data):
    udid = get_udid(root_data)
    # Use the global FILE_PATHS stored in main context if needed, 
    # but here we pass the folder path dynamically? 
    # To keep it clean, we rely on the args passed to main being available or passed down.
    # For simplicity in this architecture, we will access the global ARGS_PATHS set in main.
    return find_file_by_udid_fast(udid, "md", ARGS_PATHS['md'], '.md')

def logic_get_raw_html(value, row_context, root_data):
    udid = get_udid(root_data)
    return find_file_by_udid_fast(udid, "html", ARGS_PATHS['html'], '.html')

def logic_count_raw_md(value, row_context, root_data):
    content = logic_get_raw_md(value, row_context, root_data)
    return count_tokens(content)

def logic_count_raw_html(value, row_context, root_data):
    content = logic_get_raw_html(value, row_context, root_data)
    return count_tokens(content)

def logic_count_json_tokens(value, row_context, root_data):
    json_str = json.dumps(root_data, default=str)
    return count_tokens(json_str)

def logic_if_article_then_self_service(value, row_context, root_data):
    main_entities = root_data.get('mainEntity', [])
    if isinstance(main_entities, list) and main_entities:
        if main_entities[0].get('@type') == 'Article':
            return 'Self-service'
    return value if value else "IP Australia"

def logic_check_internal_link(value, row_context, root_data):
    if value and "ipfirstresponse" in str(value):
        return "Yes"
    return "No"

def logic_extract_udid_from_url(value, row_context, root_data):
    return "Null"

def logic_categorize_faq(value, row_context, root_data):
    val_lower = str(value).lower()
    if "benefit" in val_lower: return "Benefits"
    if "risk" in val_lower: return "Risks"
    if "cost" in val_lower: return "Costs"
    if "time" in val_lower: return "Time"
    return "General"

def logic_append_headline(value, row_context, root_data):
    headline = root_data.get('headline', '')
    return f"{headline}\n{value}"

LOGIC_MAP = {
    "get_raw_md": logic_get_raw_md,
    "get_raw_html": logic_get_raw_html,
    "count_raw_md": logic_count_raw_md,
    "count_raw_html": logic_count_raw_html,
    "count_json_tokens": logic_count_json_tokens,
    "if_article_then_self_service": logic_if_article_then_self_service,
    "check_internal_link": logic_check_internal_link,
    "extract_udid_from_url": logic_extract_udid_from_url,
    "categorize_faq": logic_categorize_faq,
    "append_headline": logic_append_headline
}

# Global container for paths
ARGS_PATHS = {"md": None, "html": None}

# --- Core Processing ---

def extract_value(path_str: str, data: Any) -> Any:
    # Use cached parser
    expr = get_jsonpath(path_str)
    if not expr: return None
    
    try:
        match = expr.find(data)
        if match:
            return match[0].value
    except:
        return None
    return None

def process_file(file_path: str, config: Dict) -> Dict[str, List[Dict]]:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    results = {}
    for table_name, table_config in config['tables'].items():
        rows = []
        root_path = table_config.get('root_path', '$')
        
        # Determine Context
        if root_path == '$':
            context_items = [data]
        else:
            try:
                expr = get_jsonpath(root_path) # Use Cache
                context_items = [m.value for m in expr.find(data)]
                if context_items and isinstance(context_items[0], list):
                     context_items = [item for sublist in context_items for item in sublist]
            except:
                context_items = []

        # Build Rows
        for item in context_items:
            row = {}
            for col_name, col_def in table_config['columns'].items():
                
                # ... (Same Extraction Logic as before) ...
                if isinstance(col_def, str):
                    if col_def.startswith("const:"):
                        row[col_name] = col_def.replace("const:", "")
                    elif col_def.startswith("parent:"):
                        row[col_name] = extract_value(col_def.replace("parent:", ""), data)
                    elif col_def == "whole_json":
                        row[col_name] = json.dumps(data)
                    else:
                        row[col_name] = extract_value(col_def, item)
                
                elif isinstance(col_def, dict):
                    path = col_def.get('path')
                    logic = col_def.get('logic')
                    val = None
                    
                    if not path and logic:
                        val = None 
                    elif path:
                        if path == "whole_json":
                            val = json.dumps(data)
                        elif path.startswith("parent:"):
                             val = extract_value(path.replace("parent:", ""), data)
                        else:
                             val = extract_value(path, item)
                    
                    if logic and logic in LOGIC_MAP:
                        val = LOGIC_MAP[logic](val, item, data)
                    
                    if val is None and 'default' in col_def:
                        val = col_def['default']

                    row[col_name] = val
            rows.append(row)
        results[table_name] = rows
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--md-source", required=False)
    parser.add_argument("--html-source", required=False)
    args = parser.parse_args()

    # 1. Setup Globals
    ARGS_PATHS['md'] = args.md_source
    ARGS_PATHS['html'] = args.html_source
    
    setup_tokenizer()
    pre_scan_directories(args.md_source, args.html_source)

    # 2. Load Config
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    if not os.path.exists(args.output):
        os.makedirs(args.output)

    # 3. Gather Files
    all_tables_data = {t: [] for t in config['tables']}
    json_files = glob.glob(os.path.join(args.source, "*.json"))
    total_files = len(json_files)
    
    print(f"🚀 Starting processing of {total_files} JSON files...")

    # 4. Processing Loop with Heartbeat
    start_time = time.time()
    
    for i, json_file in enumerate(json_files):
        # HEARTBEAT LOG: Print every 10 files
        if i % 10 == 0:
            elapsed = time.time() - start_time
            print(f"   [{i}/{total_files}] Processing {os.path.basename(json_file)} (Time: {elapsed:.1f}s)")

        try:
            file_data = process_file(json_file, config)
            for table, rows in file_data.items():
                all_tables_data[table].extend(rows)
        except Exception as e:
            print(f"❌ Error processing {json_file}: {e}")

    print("✅ Processing complete. Saving CSVs...")

    # 5. Save Results
    for table_name, data in all_tables_data.items():
        if not data: continue
        df = pd.DataFrame(data)
        filename = config['tables'][table_name]['filename']
        output_path = os.path.join(args.output, filename)
        df.to_csv(output_path, index=False)
        print(f"   Saved {filename} ({len(df)} rows)")

if __name__ == "__main__":
    main()

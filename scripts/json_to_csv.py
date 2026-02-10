import json
import yaml
import glob
import os
import argparse
import pandas as pd
import tiktoken
from jsonpath_ng.ext import parse
from typing import Any, List, Dict

# --- Global Settings ---
TOKENIZER = None
try:
    TOKENIZER = tiktoken.get_encoding("cl100k_base")
except:
    print("⚠️ Warning: tiktoken not found. Token counts will be 0.")

FILE_PATHS = {
    "md": None,
    "html": None
}

# --- Helper: File Lookup & Token Counting ---

def find_file_by_udid(udid, folder, extension):
    """
    Scans the folder for a file that STARTS with the UDID.
    Example: UDID 'B1000' will match 'B1000 - Title.md' and 'B1000 - Title-html.html'
    """
    if not folder or not os.path.exists(folder) or not udid:
        return ""
    
    # List all files in the directory
    try:
        files = os.listdir(folder)
        # Filter for files starting with UDID and ending with extension
        # We assume the UDID is the first part of the filename
        matches = [f for f in files if f.startswith(udid) and f.endswith(extension)]
        
        if matches:
            # Use the first match found
            full_path = os.path.join(folder, matches[0])
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        print(f"Error searching for {udid} in {folder}: {e}")
    
    return ""

def count_tokens(text):
    if not text or TOKENIZER is None:
        return 0
    try:
        return len(TOKENIZER.encode(text))
    except Exception:
        return 0

# --- Logic Functions ---

def get_udid(root_data):
    # Helper to safely extract UDID from the loaded JSON
    try:
        return root_data.get('identifier', {}).get('value')
    except:
        return None

def logic_get_raw_md(value, row_context, root_data):
    udid = get_udid(root_data)
    return find_file_by_udid(udid, FILE_PATHS['md'], '.md')

def logic_get_raw_html(value, row_context, root_data):
    udid = get_udid(root_data)
    return find_file_by_udid(udid, FILE_PATHS['html'], '.html')

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
    return "Null" # Placeholder

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

# --- Core Processing ---

def extract_value(path_str: str, data: Any) -> Any:
    try:
        jsonpath_expr = parse(path_str)
        match = jsonpath_expr.find(data)
        if match:
            return match[0].value
    except Exception:
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
                expr = parse(root_path)
                context_items = [m.value for m in expr.find(data)]
                # Flatten list of lists if necessary
                if context_items and isinstance(context_items[0], list):
                     context_items = [item for sublist in context_items for item in sublist]
            except Exception:
                context_items = []

        # Build Rows
        for item in context_items:
            row = {}
            for col_name, col_def in table_config['columns'].items():
                
                # Simple String Definition
                if isinstance(col_def, str):
                    if col_def.startswith("const:"):
                        row[col_name] = col_def.replace("const:", "")
                    elif col_def.startswith("parent:"):
                        row[col_name] = extract_value(col_def.replace("parent:", ""), data)
                    elif col_def == "whole_json":
                        row[col_name] = json.dumps(data)
                    else:
                        row[col_name] = extract_value(col_def, item)
                
                # Complex Dict Definition
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

    # Set Global Paths for Logic Functions
    FILE_PATHS['md'] = args.md_source
    FILE_PATHS['html'] = args.html_source

    # Load Config
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Ensure Output Directory Exists
    if not os.path.exists(args.output):
        os.makedirs(args.output)

    # Initialize Table Data Containers
    all_tables_data = {t: [] for t in config['tables']}
    
    # Get JSON Files
    json_files = glob.glob(os.path.join(args.source, "*.json"))
    
    print(f"🚀 Processing {len(json_files)} JSON files...")
    if FILE_PATHS['md']: print(f"   Using Markdown source: {FILE_PATHS['md']}")
    if FILE_PATHS['html']: print(f"   Using HTML source: {FILE_PATHS['html']}")

    # Process Files
    for json_file in json_files:
        try:
            file_data = process_file(json_file, config)
            for table, rows in file_data.items():
                all_tables_data[table].extend(rows)
        except Exception as e:
            print(f"❌ Error processing {json_file}: {e}")

    # Write Results to CSV
    for table_name, data in all_tables_data.items():
        if not data:
            continue
            
        df = pd.DataFrame(data)
        filename = config['tables'][table_name]['filename']
        output_path = os.path.join(args.output, filename)
        df.to_csv(output_path, index=False)
        print(f"✅ Saved {filename} ({len(df)} rows)")

if __name__ == "__main__":
    main()

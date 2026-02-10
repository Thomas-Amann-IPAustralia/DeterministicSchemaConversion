import json
import yaml
import glob
import os
import argparse
import pandas as pd
import tiktoken
from jsonpath_ng.ext import parse
from typing import Any, List, Dict

# Initialize Tokenizer (Global to avoid reloading)
try:
    TOKENIZER = tiktoken.get_encoding("cl100k_base")
except:
    TOKENIZER = None

# Global Context for File Paths (Populated in main)
FILE_PATHS = {
    "md": None,
    "html": None
}

# --- Helper: File Reader ---
def get_sibling_content(json_filename, source_dir, extension):
    """
    Finds a file with the same name in the source_dir with the new extension.
    """
    if not source_dir or not json_filename:
        return ""
    
    # Replace .json with the target extension
    base_name = os.path.splitext(json_filename)[0]
    target_path = os.path.join(source_dir, f"{base_name}{extension}")
    
    if os.path.exists(target_path):
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading {target_path}: {e}")
            return ""
    return ""

def count_tokens(text):
    if not text or TOKENIZER is None:
        return 0
    return len(TOKENIZER.encode(text))

# --- Logic Functions ---

def logic_get_raw_md(value, row_context, root_data):
    filename = root_data.get('__filename__')
    return get_sibling_content(filename, FILE_PATHS['md'], '.md')

def logic_get_raw_html(value, row_context, root_data):
    filename = root_data.get('__filename__')
    return get_sibling_content(filename, FILE_PATHS['html'], '.html')

def logic_count_raw_md(value, row_context, root_data):
    content = logic_get_raw_md(value, row_context, root_data)
    return count_tokens(content)

def logic_count_raw_html(value, row_context, root_data):
    content = logic_get_raw_html(value, row_context, root_data)
    return count_tokens(content)

def logic_count_json_tokens(value, row_context, root_data):
    # Dump JSON to string to count tokens
    json_str = json.dumps(root_data, default=str)
    return count_tokens(json_str)

# ... (Include previous logic functions here: if_article_then_self_service, etc.) ...
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

# Registry
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
    
    # Inject filename into root data for the logic functions to access
    data['__filename__'] = os.path.basename(file_path)

    results = {}
    for table_name, table_config in config['tables'].items():
        rows = []
        root_path = table_config.get('root_path', '$')
        
        if root_path == '$':
            context_items = [data]
        else:
            try:
                expr = parse(root_path)
                context_items = [m.value for m in expr.find(data)]
                if context_items and isinstance(context_items[0], list):
                     context_items = [item for sublist in context_items for item in sublist]
            except Exception:
                context_items = []

        for item in context_items:
            row = {}
            for col_name, col_def in table_config['columns'].items():
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
                    
                    # Special case: logic without path (e.g. looking up external file)
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
    # New Arguments
    parser.add_argument("--md-source", required=False, help="Folder with Raw Markdown")
    parser.add_argument("--html-source", required=False, help="Folder with Raw HTML")
    args = parser.parse_args()

    # Set Global Paths
    FILE_PATHS['md'] = args.md_source
    FILE_PATHS['html'] = args.html_source

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    if not os.path.exists(args.output):
        os.makedirs(args.output)

    all_tables_data = {t: [] for t in config['tables']}
    json_files = glob.glob(os.path.join(args.source, "*.json"))
    
    print(f"🚀 Processing {len(json_files)} files...")
    if FILE_PATHS['md']: print(f"   Using Markdown source: {FILE_PATHS['md']}")
    if FILE_PATHS['html']: print(f"   Using HTML source: {FILE_PATHS['html']}")

    for json_file in json_files:
        try:
            file_data = process_file(json_file, config)
            for table, rows in file_data.items():
                all_tables_data[table].extend(rows)
        except Exception as e:
            print(f"❌ Error processing {json_file}: {e}")

    for table_name, data in all_tables_data.items():
        if not data: continue
        df = pd.DataFrame(data)
        filename = config['tables'][table_name]['filename']
        df.to_csv(os.path.join(args.output, filename), index=False)
        print(f"✅ Saved {filename} ({len(df)} rows)")

if __name__ == "__main__":
    main()

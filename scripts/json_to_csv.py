import json
import yaml
import glob
import os
import argparse
import pandas as pd
from jsonpath_ng.ext import parse
from typing import Any, List, Dict

# --- Logic Functions ---

def logic_if_article_then_self_service(value, row_context, root_data):
    """If Service_Type is 'Article', default to 'Self-service'."""
    main_entities = root_data.get('mainEntity', [])
    if isinstance(main_entities, list) and main_entities:
        if main_entities[0].get('@type') == 'Article':
            return 'Self-service'
    return value if value else "IP Australia"

def logic_check_internal_link(value, row_context, root_data):
    """Checks if a URL belongs to the internal domain."""
    if value and "ipfirstresponse" in str(value):
        return "Yes"
    return "No"

def logic_extract_udid_from_url(value, row_context, root_data):
    """Placeholder for extracting UDID from internal URLs."""
    return "Null"

def logic_categorize_faq(value, row_context, root_data):
    """Categorizes FAQ questions based on keywords."""
    val_lower = str(value).lower()
    if "benefit" in val_lower: return "Benefits"
    if "risk" in val_lower: return "Risks"
    if "cost" in val_lower: return "Costs"
    if "time" in val_lower: return "Time"
    return "General"

def logic_count_json_tokens(value, row_context, root_data):
    """Counts tokens in the JSON dump."""
    json_str = json.dumps(root_data)
    return len(json_str.split())

def logic_append_headline(value, row_context, root_data):
    """Appends headline to description for semantic chunks."""
    headline = root_data.get('headline', '')
    return f"{headline}\n{value}"

LOGIC_MAP = {
    "if_article_then_self_service": logic_if_article_then_self_service,
    "check_internal_link": logic_check_internal_link,
    "extract_udid_from_url": logic_extract_udid_from_url,
    "categorize_faq": logic_categorize_faq,
    "count_json_tokens": logic_count_json_tokens,
    "append_headline": logic_append_headline
}

# --- Core Extraction Logic ---

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
            except Exception as e:
                print(f"Warning: Could not parse root path {root_path} for table {table_name}")
                context_items = []

        # Iterate Context
        for item in context_items:
            row = {}
            for col_name, col_def in table_config['columns'].items():
                
                # Simple String Definition
                if isinstance(col_def, str):
                    if col_def.startswith("const:"):
                        row[col_name] = col_def.replace("const:", "")
                    elif col_def.startswith("parent:"):
                        clean_path = col_def.replace("parent:", "")
                        row[col_name] = extract_value(clean_path, data)
                    elif col_def == "whole_json":
                        row[col_name] = json.dumps(data)
                    else:
                        row[col_name] = extract_value(col_def, item)
                
                # Complex Dict Definition
                elif isinstance(col_def, dict):
                    path = col_def.get('path')
                    logic = col_def.get('logic')
                    val = None
                    
                    if path:
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
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument("--source", required=True, help="Folder containing JSON files")
    parser.add_argument("--output", required=True, help="Folder to save CSV files")
    args = parser.parse_args()

    # Load Configuration
    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"❌ Error: Config file not found at {args.config}")
        return

    # Create Output Directory if it doesn't exist
    if not os.path.exists(args.output):
        os.makedirs(args.output)

    # Gather JSON Files
    all_tables_data = {t: [] for t in config['tables']}
    json_files = glob.glob(os.path.join(args.source, "*.json"))
    
    if not json_files:
        print(f"⚠️ No JSON files found in {args.source}")
        return

    print(f"🚀 Processing {len(json_files)} files from '{args.source}'...")

    # Process Files
    for json_file in json_files:
        try:
            file_data = process_file(json_file, config)
            for table, rows in file_data.items():
                all_tables_data[table].extend(rows)
        except Exception as e:
            print(f"❌ Error processing {json_file}: {e}")

    # Write CSVs
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

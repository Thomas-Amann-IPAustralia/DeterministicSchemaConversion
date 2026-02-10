import json
import yaml
import glob
import os
import pandas as pd
from jsonpath_ng.ext import parse
from typing import Any, List, Dict

# ---------------------------------------------------------
# Helper Functions for Business Logic
# ---------------------------------------------------------

def logic_if_article_then_self_service(value, row_context, root_data):
    """
    IF Service_Type = 'Article' then = 'Self-service'
    ELSE use the provided value (serviceOperator name).
    """
    # Find service type in root data
    # Note: This is a specific hack for the specific structure provided
    main_entities = root_data.get('mainEntity', [])
    if isinstance(main_entities, list) and main_entities:
        # Check if the first entity is an Article
        if main_entities[0].get('@type') == 'Article':
            return 'Self-service'
    
    return value if value else "IP Australia" # Default fallback

def logic_check_internal_link(value, row_context, root_data):
    """If URL contains 'ipfirstresponse' = Yes, ELSE = No"""
    if value and "ipfirstresponse" in str(value):
        return "Yes"
    return "No"

def logic_extract_udid_from_url(value, row_context, root_data):
    """
    Placeholder: In a real scenario, you might regex the UDID from the URL
    or look it up in a database. Returning Null for now as per requirements.
    """
    return "Null" # As per your sample data for most links

def logic_categorize_faq(value, row_context, root_data):
    """Helps identify if a question belongs to specific columns like 'Risks' or 'Costs'"""
    val_lower = str(value).lower()
    if "benefit" in val_lower: return "Benefits"
    if "risk" in val_lower: return "Risks"
    if "cost" in val_lower: return "Costs"
    if "time" in val_lower: return "Time"
    return "General"

def logic_count_json_tokens(value, row_context, root_data):
    """Rough estimation of token count for the JSON dump"""
    json_str = json.dumps(root_data)
    return len(json_str.split())

def logic_append_headline(value, row_context, root_data):
    """Combines Headline + Description for the Chunk text"""
    headline = root_data.get('headline', '')
    return f"{headline}\n{value}"

# Registry of logic functions
LOGIC_MAP = {
    "if_article_then_self_service": logic_if_article_then_self_service,
    "check_internal_link": logic_check_internal_link,
    "extract_udid_from_url": logic_extract_udid_from_url,
    "categorize_faq": logic_categorize_faq,
    "count_json_tokens": logic_count_json_tokens,
    "append_headline": logic_append_headline
}

# ---------------------------------------------------------
# Extraction Engine
# ---------------------------------------------------------

def extract_value(path_str: str, data: Any) -> Any:
    """Extracts a value using JSONPath."""
    jsonpath_expr = parse(path_str)
    match = jsonpath_expr.find(data)
    if match:
        # Return the value of the first match
        return match[0].value
    return None

def process_file(file_path: str, config: Dict) -> Dict[str, List[Dict]]:
    """
    Process a single JSON file and return rows for all tables defined in config.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    results = {}

    for table_name, table_config in config['tables'].items():
        rows = []
        root_path = table_config.get('root_path', '$')
        
        # 1. Determine the objects to iterate over (the "Context")
        if root_path == '$':
            context_items = [data]
        else:
            # Extract list of items based on root_path
            # e.g., relatedLink[*] or mainEntity[?(@type=='HowTo')].step[*]
            expr = parse(root_path)
            context_items = [m.value for m in expr.find(data)]

            # Flatten list of lists if necessary (rare, but happens with wildcards)
            if context_items and isinstance(context_items[0], list):
                 context_items = [item for sublist in context_items for item in sublist]

        # 2. Iterate over context items to build rows
        for item in context_items:
            row = {}
            for col_name, col_def in table_config['columns'].items():
                
                # Handle simplified key-value definition
                if isinstance(col_def, str):
                    if col_def.startswith("const:"):
                        row[col_name] = col_def.replace("const:", "")
                    elif col_def.startswith("parent:"):
                        # Extract from Root Data (data) instead of current item
                        clean_path = col_def.replace("parent:", "")
                        row[col_name] = extract_value(clean_path, data)
                    elif col_def == "whole_json":
                        row[col_name] = json.dumps(data)
                    else:
                        # Extract from current item
                        row[col_name] = extract_value(col_def, item)
                
                # Handle complex definition (with logic)
                elif isinstance(col_def, dict):
                    path = col_def.get('path')
                    logic = col_def.get('logic')
                    
                    # Extract initial value
                    val = None
                    if path:
                        if path == "whole_json":
                            val = json.dumps(data)
                        elif path.startswith("parent:"):
                             val = extract_value(path.replace("parent:", ""), data)
                        else:
                             val = extract_value(path, item)
                    
                    # Apply logic if defined
                    if logic and logic in LOGIC_MAP:
                        val = LOGIC_MAP[logic](val, item, data)
                    
                    # Use default if null
                    if val is None and 'default' in col_def:
                        val = col_def['default']

                    row[col_name] = val
            
            rows.append(row)
        
        results[table_name] = rows

    return results

# ---------------------------------------------------------
# Main Execution
# ---------------------------------------------------------

def main():
    # Load Config
    with open("schema_mapping.yaml", 'r') as f:
        config = yaml.safe_load(f)
    
    source_dir = config['settings']['source_folder']
    output_dir = config['settings']['output_folder']
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Accumulate data for all files
    all_tables_data = {t: [] for t in config['tables']}
    
    json_files = glob.glob(os.path.join(source_dir, "*.json"))
    print(f"Found {len(json_files)} JSON files...")

    for json_file in json_files:
        print(f"Processing {json_file}...")
        file_data = process_file(json_file, config)
        
        for table, rows in file_data.items():
            all_tables_data[table].extend(rows)

    # Save to CSV
    for table_name, data in all_tables_data.items():
        if not data:
            continue
            
        df = pd.DataFrame(data)
        
        # Determine filename
        filename = config['tables'][table_name]['filename']
        output_path = os.path.join(output_dir, filename)
        
        # Save
        df.to_csv(output_path, index=False)
        print(f"Saved {table_name} to {output_path} ({len(df)} rows)")

if __name__ == "__main__":
    main()

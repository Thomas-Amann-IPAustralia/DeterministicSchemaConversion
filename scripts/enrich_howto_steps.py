import os
import json
import csv
import difflib
import math
import sys
from openai import OpenAI

# Configuration
INPUT_DIR = 'json_output'
OUTPUT_DIR = 'json_output-enriched'
REPORT_FILE = 'after_action_report.csv'
BATCH_SIZE = 5

# Define target placeholders
TARGET_PLACEHOLDERS = [
    "xXx_PLACEHOLDER_xXx",
    "xXx_Err-PLACEHOLDER_xXx"
]

def get_service_details(data):
    """Extracts Service Name and UDID from the JSON."""
    service_name = data.get('headline', 'Unknown Service')
    udid = "Unknown"
    
    identifier = data.get('identifier', {})
    if isinstance(identifier, dict) and identifier.get('propertyID') == 'UDID':
        udid = identifier.get('value', 'Unknown')
    
    return service_name, udid

def generate_replacement_value(key, parent_obj, full_doc_context, client):
    """
    Determines the context based on the key and parent object, 
    then asks the LLM for a specific replacement.
    """
    try:
        model = "gpt-4o"
        system_prompt = "You are a JSON metadata enrichment bot. You return ONLY the requested string value without markdown or quotes."
        user_prompt = ""
        context_str = ""

        # --- Scenario 1: HowToStep Name ---
        if key == 'name' and '@type' in parent_obj and parent_obj['@type'] == 'HowToStep':
            text = parent_obj.get('text', '')
            context_str = text[:1000] # Limit context size
            user_prompt = (
                f"Read this instructional step text: '{context_str}'. "
                "Generate a short, imperative name (title) for this step (e.g., 'Fill out the form')."
            )

        # --- Scenario 2: WebPage Description ---
        elif key == 'description':
            headline = full_doc_context.get('headline', '')
            # Gather headers/questions to give context
            sub_entities = full_doc_context.get('mainEntity', [])
            if isinstance(sub_entities, dict): sub_entities = [sub_entities]
            
            summary_points = []
            for e in sub_entities:
                if e.get('name'): summary_points.append(e.get('name'))
            
            context_str = f"Headline: {headline}. Sections: {', '.join(summary_points[:10])}"
            user_prompt = (
                f"Context: {context_str}. "
                "Generate a concise (max 160 chars) SEO description for this web page. "
                "Do not use 'This page contains...' just describe the value proposition."
            )

        # --- Scenario 3: Organization/Provider Name ---
        elif key == 'name' and ('url' in parent_obj or 'alternateName' in parent_obj):
            url = parent_obj.get('url', '')
            alt = parent_obj.get('alternateName', '')
            context_str = f"URL: {url}, Alt Name: {alt}"
            user_prompt = (
                f"Context: {context_str}. "
                "Infer the official name of the Organization or Provider. "
                "If it looks like a government body, use the full proper name."
            )

        # --- Scenario 4: Service Type ---
        elif key == 'serviceType' or key == '@type':
            headline = full_doc_context.get('headline', '')
            context_str = headline
            user_prompt = (
                f"Service Headline: {headline}. "
                "Classify this service into one of these schema.org types: "
                "'GovernmentService', 'Service', 'HowTo'. Return ONLY the type name."
            )

        # --- Fallback ---
        else:
            context_str = str(parent_obj)[:500]
            user_prompt = (
                f"The field '{key}' is missing. Based on this JSON context: {context_str}, "
                "generate a suitable value."
            )

        # Call LLM
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip(), context_str

    except Exception as e:
        print(f"   ❌ Error calling LLM: {e}")
        return "ERROR_GENERATING_CONTENT", "Error"

def recursive_enrich(data, full_doc, client, report_list, file_name, service_name, udid, path="root"):
    """
    Recursively walks the JSON tree. If a placeholder is found, 
    triggers LLM enrichment and updates the object in place.
    """
    modified = False

    if isinstance(data, dict):
        for key, value in data.items():
            # Check if the value is a string and matches our placeholders
            if isinstance(value, str) and value in TARGET_PLACEHOLDERS:
                print(f"     🤖 Fix found at {path}.{key}...")
                
                new_value, context_used = generate_replacement_value(key, data, full_doc, client)
                print(f"     ✨ {key}: '{new_value}'")
                
                # Update In-Place
                data[key] = new_value
                modified = True
                
                report_list.append({
                    'file_name': file_name,
                    'service_name': service_name,
                    'udid': udid,
                    'field_path': f"{path}.{key}",
                    'original_placeholder': value,
                    'context_snippet': context_used[:100], # Truncate for CSV readability
                    'generated_value': new_value,
                    'diff_status': 'Pending'
                })

            # Recurse deeper
            elif isinstance(value, (dict, list)):
                if recursive_enrich(value, full_doc, client, report_list, file_name, service_name, udid, f"{path}.{key}"):
                    modified = True

    elif isinstance(data, list):
        for index, item in enumerate(data):
            if recursive_enrich(item, full_doc, client, report_list, file_name, service_name, udid, f"{path}[{index}]"):
                modified = True
    
    return modified

def perform_diff_check(original_path, new_path):
    """
    Compares files semantically.
    Allows changes ONLY if the original was in TARGET_PLACEHOLDERS.
    """
    try:
        with open(original_path, 'r', encoding='utf-8') as f:
            orig_data = json.load(f)
        with open(new_path, 'r', encoding='utf-8') as f:
            new_data = json.load(f)
    except json.JSONDecodeError as e:
        return f"JSON Decode Error: {e}"

    unexpected_changes = []

    def recursive_compare(path, obj1, obj2):
        # 1. Check for type mismatch
        if type(obj1) != type(obj2):
            unexpected_changes.append(f"Type mismatch at {path}: {type(obj1)} vs {type(obj2)}")
            return

        # 2. Compare Dictionaries
        if isinstance(obj1, dict):
            all_keys = set(obj1.keys()) | set(obj2.keys())
            for key in all_keys:
                if key not in obj1:
                    unexpected_changes.append(f"New key added at {path}.{key}")
                elif key not in obj2:
                    unexpected_changes.append(f"Key removed at {path}.{key}")
                else:
                    recursive_compare(f"{path}.{key}", obj1[key], obj2[key])

        # 3. Compare Lists
        elif isinstance(obj1, list):
            if len(obj1) != len(obj2):
                unexpected_changes.append(f"List length changed at {path}: {len(obj1)} vs {len(obj2)}")
            else:
                for i, (item1, item2) in enumerate(zip(obj1, obj2)):
                    recursive_compare(f"{path}[{i}]", item1, item2)

        # 4. Compare Primitive Values
        else:
            if obj1 != obj2:
                # ALLOWED EXCEPTION:
                # If the original was one of our placeholders, we accept the change.
                if obj1 in TARGET_PLACEHOLDERS:
                    return 
                
                # Otherwise, it's a genuine unexpected change
                unexpected_changes.append(f"Value mismatch at {path}: '{obj1}' -> '{obj2}'")

    recursive_compare("root", orig_data, new_data)

    if not unexpected_changes:
        return "Pass"
    else:
        return f"Changes detected: {'; '.join(unexpected_changes)}"

def process_files():
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]
    files.sort()
    
    if not files:
        print("No JSON files found in input directory.")
        return

    report_rows = []
    
    stats = {
        'total_files': len(files),
        'files_modified': 0,
        'llm_calls': 0, # Note: Actual calls tracked loosely via rows for now
        'diff_failures': 0
    }

    print(f"🚀 Starting Enrichment Process for {len(files)} files...")
    
    total_batches = math.ceil(len(files) / BATCH_SIZE)
    
    for i in range(total_batches):
        batch_files = files[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        
        print(f"::group::📦 Processing Batch {i+1}/{total_batches} ({len(batch_files)} files)")
        
        for file_name in batch_files:
            print(f"  📄 Processing: {file_name}")
            input_path = os.path.join(INPUT_DIR, file_name)
            output_path = os.path.join(OUTPUT_DIR, file_name)
            
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            service_name, udid = get_service_details(data)
            
            # RECURSIVE ENRICHMENT
            # We pass 'data' twice: once as the mutable object, once as full context
            file_modified = recursive_enrich(
                data, data, client, report_rows, file_name, service_name, udid
            )

            # Save enriched file
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n')

            # Perform Diff Check
            if file_modified:
                stats['files_modified'] += 1
                diff_result = perform_diff_check(input_path, output_path)
                
                # Update rows for this file
                for row in report_rows:
                    if row['file_name'] == file_name and row['diff_status'] == 'Pending':
                        row['diff_status'] = diff_result
                
                if diff_result == "Pass":
                    print(f"     ✅ Diff Check: PASS")
                else:
                    print(f"     ⚠️ Diff Check: FAIL - {diff_result}")
                    stats['diff_failures'] += 1
            else:
                print(f"     ℹ️ No placeholders found.")

        print("::endgroup::")
        sys.stdout.flush()

    # Write CSV Report
    with open(REPORT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'Service Name', 'UDID', 'Diff Check Results', 
            'Field Path', 'Original Placeholder', 'Context Snippet', 'Generated Value'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for row in report_rows:
            writer.writerow({
                'Service Name': row['service_name'],
                'UDID': row['udid'],
                'Diff Check Results': row['diff_status'],
                'Field Path': row['field_path'],
                'Original Placeholder': row['original_placeholder'],
                'Context Snippet': row['context_snippet'],
                'Generated Value': row['generated_value']
            })
            
    # Final Summary Log
    print("\n" + "="*40)
    print("📊 ENRICHMENT SUMMARY")
    print("="*40)
    print(f"Total Files Processed: {stats['total_files']}")
    print(f"Files Modified:        {stats['files_modified']}")
    print(f"Total Updates:         {len(report_rows)}")
    print(f"Diff Failures:         {stats['diff_failures']}")
    print(f"Report Location:       {REPORT_FILE}")
    print("="*40 + "\n")

if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable not set.")
        exit(1)
    process_files()

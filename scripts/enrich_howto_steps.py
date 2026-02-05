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

def get_service_details(data):
    """Extracts Service Name and UDID from the JSON."""
    service_name = data.get('headline', 'Unknown Service')
    udid = "Unknown"
    
    identifier = data.get('identifier', {})
    if isinstance(identifier, dict) and identifier.get('propertyID') == 'UDID':
        udid = identifier.get('value', 'Unknown')
    
    return service_name, udid

def get_llm_name(text, client):
    """Sends text to LLM to generate a short name."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an editor helper. Read the text provided. It is a step in a 'How-To' guide. Look for the string 'xXx_PLACEHOLDER_xXx' and replace it with a short and accurate name for the text that follows it. You must ONLY return the content required for the HowToStep 'name'. Do not include quotes or extra markup."},
                {"role": "user", "content": f"Text: {text}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"   ❌ Error calling LLM: {e}")
        return "ERROR_GENERATING_NAME"

def perform_diff_check(original_path, new_path):
    """
    Compares files semantically as JSON objects.
    Ignores formatting/encoding differences.
    Only allows changes where the original value was 'xXx_PLACEHOLDER_xXx'.
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
            # Check keys present in both
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

        # 4. Compare Primitive Values (Strings, Ints, etc.)
        else:
            if obj1 != obj2:
                # ALLOWED EXCEPTION:
                # If the original was the placeholder, we accept the change.
                if obj1 == "xXx_PLACEHOLDER_xXx":
                    return 
                
                # Otherwise, it's a genuine unexpected change
                unexpected_changes.append(f"Value mismatch at {path}: '{obj1}' -> '{obj2}'")

    # Start the recursive comparison
    recursive_compare("root", orig_data, new_data)

    if not unexpected_changes:
        return "Pass"
    else:
        return f"Changes detected: {'; '.join(unexpected_changes)}"

def process_files():
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Initialize OpenAI client
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    
    # Gather files
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]
    files.sort()
    
    if not files:
        print("No JSON files found in input directory.")
        return

    report_rows = []
    
    # Statistics
    stats = {
        'total_files': len(files),
        'files_modified': 0,
        'llm_calls': 0,
        'diff_failures': 0
    }

    print(f"🚀 Starting Enrichment Process for {len(files)} files...")
    
    # Process in batches
    total_batches = math.ceil(len(files) / BATCH_SIZE)
    
    for i in range(total_batches):
        batch_files = files[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        
        # GitHub Action Group Start
        print(f"::group::📦 Processing Batch {i+1}/{total_batches} ({len(batch_files)} files)")
        
        for file_name in batch_files:
            print(f"  📄 Processing: {file_name}")
            input_path = os.path.join(INPUT_DIR, file_name)
            output_path = os.path.join(OUTPUT_DIR, file_name)
            
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            service_name, udid = get_service_details(data)
            
            entities = data.get('mainEntity', [])
            if isinstance(entities, dict):
                entities = [entities]
                
            file_modified = False
            
            for entity in entities:
                if entity.get('@type') == 'HowTo':
                    steps = entity.get('step', [])
                    for step in steps:
                        if step.get('name') == 'xXx_PLACEHOLDER_xXx':
                            text = step.get('text', '')
                            
                            # Log the attempt
                            print(f"     🤖 Generating name for step...")
                            
                            # Call LLM
                            new_name = get_llm_name(text, client)
                            stats['llm_calls'] += 1
                            
                            print(f"     ✨ Result: '{new_name}'")

                            # Update JSON
                            step['name'] = new_name
                            file_modified = True
                            
                            report_rows.append({
                                'file_name': file_name,
                                'service_name': service_name,
                                'udid': udid,
                                'original_text': text,
                                'generated_name': new_name,
                                'diff_status': 'Pending' 
                            })

            # Save enriched file
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n') 

            # Perform Diff Check
            if file_modified:
                stats['files_modified'] += 1
                diff_result = perform_diff_check(input_path, output_path)
                
                # Update rows
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

        # GitHub Action Group End
        print("::endgroup::")
        # Flush stdout to ensure logs appear in real-time in GHA
        sys.stdout.flush()

    # Write CSV Report
    with open(REPORT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Service Name', 'UDID', 'Diff Check Results', 'Original HowToStep Text', 'Generated Name']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for row in report_rows:
            writer.writerow({
                'Service Name': row['service_name'],
                'UDID': row['udid'],
                'Diff Check Results': row['diff_status'],
                'Original HowToStep Text': row['original_text'],
                'Generated Name': row['generated_name']
            })
            
    # Final Summary Log
    print("\n" + "="*40)
    print("📊 ENRICHMENT SUMMARY")
    print("="*40)
    print(f"Total Files Processed: {stats['total_files']}")
    print(f"Files Modified:        {stats['files_modified']}")
    print(f"Total LLM Calls:       {stats['llm_calls']}")
    print(f"Diff Failures:         {stats['diff_failures']}")
    print(f"Report Location:       {REPORT_FILE}")
    print("="*40 + "\n")

if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable not set.")
        exit(1)
    process_files()

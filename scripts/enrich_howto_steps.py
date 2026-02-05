import os
import json
import csv
import difflib
import math
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
            model="gpt-4o", # Using a capable model for accurate naming
            messages=[
                {"role": "system", "content": "You are an editor helper. Read the text provided. It is a step in a 'How-To' guide. Look for the string 'xXx_PLACEHOLDER_xXx' and replace it with a short and accurate name for the text that follows it. You must ONLY return the content required for the HowToStep 'name'. Do not include quotes or extra markup."},
                {"role": "user", "content": f"Text: {text}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling LLM: {e}")
        return "ERROR_GENERATING_NAME"

def perform_diff_check(original_path, new_path):
    """
    Compares files line by line. 
    Returns "Pass" if only placeholder lines changed.
    Otherwise returns specific line numbers of unexpected changes.
    """
    with open(original_path, 'r', encoding='utf-8') as f:
        orig_lines = f.readlines()
    with open(new_path, 'r', encoding='utf-8') as f:
        new_lines = f.readlines()

    diff = difflib.unified_diff(orig_lines, new_lines, n=0)
    
    unexpected_changes = []
    
    # Simple state machine to track diff blocks
    # We expect pairs of:
    # - "name": "xXx_PLACEHOLDER_xXx"
    # + "name": "Generated Name"
    
    for line in diff:
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
            
        clean_line = line[1:].strip()
        
        # Allow removal of placeholder lines
        if line.startswith('-'):
            if '"name": "xXx_PLACEHOLDER_xXx"' in clean_line:
                continue
            else:
                # We can't easily get the exact line number from unified_diff without parsing @@ headers
                # For simplicity in this script, we flag the content that changed unexpectedly
                unexpected_changes.append(f"Unexpected removal: {clean_line}")
        
        # Allow addition of lines that look like name fields (assuming they replaced the placeholder)
        elif line.startswith('+'):
            if '"name":' in clean_line:
                continue
            else:
                unexpected_changes.append(f"Unexpected addition: {clean_line}")
    
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
    
    report_rows = []
    
    # Process in batches
    total_batches = math.ceil(len(files) / BATCH_SIZE)
    
    for i in range(total_batches):
        batch_files = files[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        print(f"Processing batch {i+1}/{total_batches}: {batch_files}")
        
        for file_name in batch_files:
            input_path = os.path.join(INPUT_DIR, file_name)
            output_path = os.path.join(OUTPUT_DIR, file_name)
            
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            service_name, udid = get_service_details(data)
            
            # Find mainEntity of type HowTo
            # mainEntity can be a list or dict
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
                            
                            # Call LLM
                            new_name = get_llm_name(text, client)
                            
                            # Update JSON
                            step['name'] = new_name
                            file_modified = True
                            
                            # Prepare report entry (temporarily, diff check comes after save)
                            report_rows.append({
                                'file_name': file_name,
                                'service_name': service_name,
                                'udid': udid,
                                'original_text': text,
                                'generated_name': new_name,
                                'diff_status': 'Pending' 
                            })

            # Save enriched file
            # Using indent=2 to match the likely source format and minimize diff noise
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                # Add a newline at end of file if source had it, standard for many editors
                f.write('\n') 

            # Perform Diff Check
            if file_modified:
                diff_result = perform_diff_check(input_path, output_path)
                
                # Update rows for this file with the diff result
                for row in report_rows:
                    if row['file_name'] == file_name and row['diff_status'] == 'Pending':
                        row['diff_status'] = diff_result

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
            
    print(f"Processing complete. Report saved to {REPORT_FILE}")

if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        exit(1)
    process_files()

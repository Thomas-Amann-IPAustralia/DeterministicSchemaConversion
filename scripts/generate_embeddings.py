import os
import sys
import pandas as pd
import logging
from openai import OpenAI

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def generate_embeddings():
    # --- Configuration ---
    input_file = 'sqlite_data/Semantic.xlsx'
    output_file_csv = 'sqlite_data/Semantic_Embeddings_Output.csv'
    output_file_xlsx = 'sqlite_data/Semantic_Embeddings_Output.xlsx'
    output_file_json = 'sqlite_data/Semantic_Embeddings_Output.json'
    
    logger.info("--- Starting Embedding Generation Workflow ---")
    logger.info(f"Target Input File: {input_file}")
    logger.info(f"Target Output CSV: {output_file_csv}")
    logger.info(f"Target Output XLSX: {output_file_xlsx}")
    logger.info(f"Target Output JSON: {output_file_json}")

    # --- Credential Check ---
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("CRITICAL: OPENAI_API_KEY environment variable is missing.")
        sys.exit(1)
    logger.info("Credential Check: API Key found.")

    client = OpenAI(api_key=api_key)

    # --- Load Data ---
    if not os.path.exists(input_file):
        logger.error(f"CRITICAL: Input file '{input_file}' not found.")
        sys.exit(1)

    try:
        df = pd.read_excel(input_file, engine='openpyxl')
        logger.info(f"Loaded data. Total rows: {len(df)}")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to read input file. Error: {e}")
        sys.exit(1)

    # --- Identify Missing Embeddings ---
    if 'Chunk_Embedding' not in df.columns:
        df['Chunk_Embedding'] = None
    
    # Filter for rows where embedding is missing (NaN or empty)
    rows_to_process = df[df['Chunk_Embedding'].isna() | (df['Chunk_Embedding'] == "")]
    
    logger.info(f"Rows requiring embeddings: {len(rows_to_process)}")

    if rows_to_process.empty:
        logger.info("No new embeddings needed. Exiting.")
        return

    # --- Processing Loop ---
    logger.info("--- Beginning API Calls ---")
    success_count = 0
    error_count = 0

    for index, row in rows_to_process.iterrows():
        chunk_id = row.get('Chunk_ID', f"Row_{index}")
        text_content = row['Chunk_Text']

        if pd.isna(text_content) or str(text_content).strip() == "":
            continue

        try:
            logger.info(f"Processing ID: {chunk_id} | Length: {len(str(text_content))}")
            
            response = client.embeddings.create(
                input=str(text_content),
                model="text-embedding-3-small"
            )

            # Save as stringified list
            df.at[index, 'Chunk_Embedding'] = str(response.data[0].embedding)
            success_count += 1
            logger.info(f"Success ID: {chunk_id}")

        except Exception as e:
            error_count += 1
            logger.error(f"FAILURE ID: {chunk_id} | Error: {e}")

    logger.info("--- Processing Complete ---")
    
    # --- Save Outputs ---
    try:
        # Save CSV
        df.to_csv(output_file_csv, index=False)
        logger.info(f"Saved CSV: {output_file_csv}")
        
        # Save Excel
        df.to_excel(output_file_xlsx, index=False, engine='openpyxl')
        logger.info(f"Saved Excel: {output_file_xlsx}")

        # Save JSON (List of objects structure)
        # orient='records' creates the [{col:val}, {col:val}] structure
        df.to_json(output_file_json, orient='records', indent=4, force_ascii=False)
        logger.info(f"Saved JSON: {output_file_json}")

    except Exception as e:
        logger.error(f"CRITICAL: Failed to save output files. Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_embeddings()

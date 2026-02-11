import os
import sys
import pandas as pd
import logging
from openai import OpenAI

# 1. Setup Logging
# This configures the logs to show Time - Level - Message
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def generate_embeddings():
    # --- Configuration ---
    input_file = 'Semantic.xlsx - Sheet1.csv'
    output_file = 'Semantic_Embeddings_Output.csv'
    
    logger.info("--- Starting Embedding Generation Workflow ---")
    logger.info(f"Target Input File: {input_file}")
    logger.info(f"Target Output File: {output_file}")

    # --- Credential Check ---
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("CRITICAL: OPENAI_API_KEY environment variable is missing.")
        sys.exit(1) # Exit with error code to fail the GitHub Action
    logger.info("Credential Check: API Key found.")

    client = OpenAI(api_key=api_key)

    # --- Load Data ---
    if not os.path.exists(input_file):
        logger.error(f"CRITICAL: Input file '{input_file}' not found.")
        sys.exit(1)

    df = pd.read_csv(input_file)
    logger.info(f"Data Loaded: {len(df)} total rows found in CSV.")

    # Validate Columns
    required_cols = ['Chunk_Text', 'Chunk_ID']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        logger.error(f"CRITICAL: Missing columns in CSV: {missing}")
        sys.exit(1)

    # Ensure output column exists
    if 'Chunk_Embedding' not in df.columns:
        df['Chunk_Embedding'] = None
        logger.info("Schema Update: Added missing 'Chunk_Embedding' column.")

    # --- Filter Workload ---
    # We define 'work' as rows where Chunk_Embedding is NaN or empty string
    # We force string conversion to handle potential float/NaN issues safely
    mask = df['Chunk_Embedding'].isna() | (df['Chunk_Embedding'].astype(str).str.strip() == '')
    rows_to_process = df[mask]
    
    total_work = len(rows_to_process)
    skipped_count = len(df) - total_work
    
    logger.info(f"Workload Assessment: {skipped_count} rows already have embeddings (SKIPPING).")
    logger.info(f"Workload Assessment: {total_work} rows require embeddings.")

    if total_work == 0:
        logger.info("Nothing to do. Exiting.")
        return

    # --- Processing Loop ---
    logger.info("--- Beginning API Calls ---")
    
    success_count = 0
    error_count = 0

    for index, row in rows_to_process.iterrows():
        chunk_id = row.get('Chunk_ID', f"Row_{index}")
        text_content = row['Chunk_Text']

        # Sanity check on text
        if pd.isna(text_content) or str(text_content).strip() == "":
            logger.warning(f"Row {index} (ID: {chunk_id}): Text is empty. Skipping.")
            continue

        try:
            # Log before call
            logger.info(f"Sending ID: {chunk_id} | Length: {len(str(text_content))} chars")

            response = client.embeddings.create(
                input=str(text_content),
                model="text-embedding-3-small"
            )

            # Extract data
            embedding_vector = response.data[0].embedding
            prompt_tokens = response.usage.prompt_tokens
            
            # Update DataFrame
            df.at[index, 'Chunk_Embedding'] = embedding_vector
            
            success_count += 1
            logger.info(f"Success ID: {chunk_id} | Tokens used: {prompt_tokens}")

        except Exception as e:
            error_count += 1
            logger.error(f"FAILURE ID: {chunk_id} | Error: {str(e)}")

    # --- Finalize ---
    logger.info("--- Processing Complete ---")
    logger.info(f"Summary: {success_count} succeeded, {error_count} failed.")
    
    try:
        df.to_csv(output_file, index=False)
        logger.info(f"File Saved: Successfully wrote to {output_file}")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to save output file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_embeddings()

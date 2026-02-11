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
    output_file = 'sqlite_data/Semantic_Embeddings_Output.csv'
    
    logger.info("--- Starting Embedding Generation Workflow ---")
    logger.info(f"Target Input File: {input_file}")
    logger.info(f"Target Output File: {output_file}")

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
        # Load Excel file
        df = pd.read_excel(input_file, engine='openpyxl')
        logger.info(f"Data Loaded: {len(df)} total rows found in Excel file.")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to read Excel file. Error: {e}")
        sys.exit(1)

    # --- Validation & Schema Update ---
    if 'Chunk_Text' not in df.columns:
        logger.error(f"CRITICAL: Column 'Chunk_Text' not found. Columns are: {list(df.columns)}")
        sys.exit(1)

    # Ensure output column exists
    if 'Chunk_Embedding' not in df.columns:
        df['Chunk_Embedding'] = None

    # CRITICAL FIX: Force the column to be of type 'object' to allow storing lists/strings
    # Without this, pandas treats empty columns as floats (NaN) and fails when assigning a list
    df['Chunk_Embedding'] = df['Chunk_Embedding'].astype('object')
    logger.info("Schema Update: 'Chunk_Embedding' column ready for vector data.")

    # --- Filter Workload ---
    # Work = rows where Chunk_Embedding is NaN or empty
    mask = df['Chunk_Embedding'].isna() | (df['Chunk_Embedding'].astype(str).str.strip() == '')
    rows_to_process = df[mask]
    
    total_work = len(rows_to_process)
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

        if pd.isna(text_content) or str(text_content).strip() == "":
            logger.warning(f"Row {index} (ID: {chunk_id}): Text is empty. Skipping.")
            continue

        try:
            logger.info(f"Processing ID: {chunk_id} | Length: {len(str(text_content))} chars")

            response = client.embeddings.create(
                input=str(text_content),
                model="text-embedding-3-small"
            )

            embedding_vector = response.data[0].embedding
            tokens = response.usage.prompt_tokens
            
            # CRITICAL FIX: Convert list to string before assignment
            # This prevents the "Must have equal len keys and value" error
            df.at[index, 'Chunk_Embedding'] = str(embedding_vector)
            
            success_count += 1
            logger.info(f"Success ID: {chunk_id} | Tokens: {tokens}")

        except Exception as e:
            error_count += 1
            logger.error(f"FAILURE ID: {chunk_id} | Error: {e}")

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

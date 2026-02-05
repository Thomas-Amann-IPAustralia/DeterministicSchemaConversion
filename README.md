# DeterministicSchemaConversion

**A robust pipeline for scraping government content and converting it into high-fidelity, structured Schema.org JSON-LD.**

## Overview

This repository hosts a Python-based toolchain designed to digitize and structure content from the **IP First Response** website. It transforms unstructured web HTML into machine-readable data structures—specifically `GovernmentService`, `HowTo`, and `FAQPage`—optimized for Large Language Models (LLMs), search engine discovery, and voice assistants.

Unlike standard scrapers, this pipeline employs a **hybrid parsing approach**: it captures both raw HTML (for precise DOM structure analysis) and converts content to clean Markdown (for semantic clarity). It then optionally uses **AI enrichment** to refine the data.

## Key Features

* **🕵️ Stealth Scraping:** Utilizes `selenium-stealth` with Headless Chrome to bypass bot detection, ensuring reliable access to GovCMS-hosted content.
* **📄 Hybrid Content Extraction:**
* **HTML Capture:** Preserves raw DOM structures (specifically `region-content`) to accurately identify nested lists and complex formatting.
* **Markdown Conversion:** Simultaneously converts content to "ATX" style Markdown, stripping noise (navigation, footers) while keeping semantic headers.


* **🧩 Deterministic Schema Generation:**
* Maps content to `GovernmentService`, `HowTo`, or `Organization` based on archetypes.
* Extracts `FAQPage` items from headers phrased as questions.
* Generates `HowToStep`s from ordered lists and process-oriented headers.


* **🤖 AI Metadata Enrichment:** An optional post-processing step uses **OpenAI (GPT-4o)** to intelligently name logical steps in "How-to" guides that lack explicit headers, ensuring high-quality `name` properties for Schema.org compliance.
* **🛡️ Safety & Diffing:** The enrichment process includes a strict "semantic diff" check to ensure the AI *only* modifies placeholder fields and does not hallucinate or alter factual content.

## Project Structure

```text
DeterministicSchemaConversion/
├── IPFR-Webpages/              # Output: Cleaned Markdown files
├── IPFR-Webpages-html/         # Output: Raw HTML content files
├── json_output/                # Output: Initial Schema.org JSON-LD
├── json_output-enriched/       # Output: Final AI-enriched JSON-LD
├── scripts/
│   ├── process_md_to_json.py   # Logic: Converts MD/HTML + CSV to JSON-LD
│   └── enrich_howto_steps.py   # Logic: AI enrichment for step naming
├── 260203_IPFRMetaTable.csv    # (Required) Metadata mapping table
├── scraper.py                  # Logic: Selenium scraper (HTML + MD)
├── sources.json                # Configuration: List of URLs to scrape
├── requirements.txt            # Python dependencies
└── README.md                   # Documentation

```

## Prerequisites

* **Python 3.8+**
* **Google Chrome** (Installed on the host machine).
* **OpenAI API Key** (Required only for the optional enrichment step).

## Installation

1. **Clone the repository:**
```bash
git clone https://github.com/your-username/DeterministicSchemaConversion.git
cd DeterministicSchemaConversion

```


2. **Install dependencies:**
```bash
pip install -r requirements.txt

```


*Note: If you plan to use the enrichment script, ensure `openai` is installed:*
```bash
pip install openai

```



## Configuration

### 1. Source Definition (`sources.json`)

Define the pages to scrape in `sources.json`. This file expects a JSON array of objects:

```json
[
  {
    "url": "https://ipfirstresponse.ipaustralia.gov.au/options/mediation",
    "filename": "D1006 - Mediation.md"
  }
]

```

### 2. Metadata Table (`260203_IPFRMetaTable.csv`)

This CSV acts as the "control plane" for the schema generation. It must contain:

* `UDID`: Unique Identifier for the service.
* `Main Title`: Canonical title.
* `Archetype`: `Government Service`, `Self-Help`, or `Organization`.
* `Relevant IP right`: Triggers automatic `Legislation` citations (e.g., "Trade Mark" maps to *Trade Marks Act 1995*).

---

## Usage Workflow

### Step 1: Scrape Content

Run the scraper to fetch pages. It will generate matched pairs of Markdown and HTML files in `IPFR-Webpages/` and `IPFR-Webpages-html/`.

```bash
python scraper.py

```

* **Output:** `IPFR-Webpages/*.md`, `IPFR-Webpages-html/*.html`
* *Note: The scraper runs in headless mode but mimics a real user agent.*

### Step 2: Generate Base JSON-LD

Convert the scraped content into structured data. This script prioritizes the HTML files for structure (finding steps/lists) but uses Markdown for clean text text extraction.

```bash
python scripts/process_md_to_json.py

```

* **Output:** `json_output/*.json`
* *Details: Steps without clear headers are assigned the placeholder name `xXx_PLACEHOLDER_xXx`.*

### Step 3: AI Enrichment (Optional but Recommended)

Use GPT-4o to read the content of steps named `xXx_PLACEHOLDER_xXx` and generate concise, descriptive names.

1. Set your OpenAI API key:
```bash
# Linux/Mac
export OPENAI_API_KEY="sk-..."
# Windows (Powershell)
$env:OPENAI_API_KEY="sk-..."

```


2. Run the enrichment script:
```bash
python scripts/enrich_howto_steps.py

```



* **Output:** `json_output-enriched/*.json`
* **Report:** Generates `after_action_report.csv` detailed all changes made.
* *Safety:* The script performs a JSON diff. If any value matches a non-placeholder change, the file is flagged as **FAIL** and changes are discarded to prevent data corruption.

## Script Details

### `scraper.py`

* Initializes a stealthy Chrome driver.
* Extracts metadata (Title, Overtitle) from the DOM.
* Saves a "cleaned" Markdown version (using `markdownify` with ATX headers).
* Saves the raw `innerHTML` of the main content region for precise parsing later.

### `scripts/process_md_to_json.py`

* **Hybrid Parser:** Tries to parse the HTML file first to find complex lists (`<ol>`, `<ul>`) which are often lost in Markdown conversion.
* **Schema Mapping:**
* Headers ending in `?` -> `FAQPage` > `Question`.
* Headers containing "Steps" or "Proceed" -> `HowTo` > `HowToStep`.
* Keywords in CSV -> `Legislation` citations.


* **Enrichment:** Injects `Audience`, `ServiceOperator`, and `UsageInfo` blocks defined in constants.

### `scripts/enrich_howto_steps.py`

* Iterates through `json_output/`.
* Identifies `HowToStep` items with the specific placeholder name.
* Sends the `text` of the step to OpenAI API with a system prompt designed to generate a short 3-5 word summary name.
* Validates the result using a recursive JSON comparison function.

## License

[Insert License Information Here]

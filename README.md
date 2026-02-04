# DeterministicSchemaConversion

**A pipeline for scraping government content and converting it into structured Schema.org JSON-LD.**

## Overview

This repository contains a Python-based toolset designed to scrape web pages from the **IP First Response** website, convert the content into clean Markdown, and deterministically map that content into structured JSON-LD (Schema.org) files.

The primary goal is to transform unstructured web HTML into machine-readable data structures (such as `GovernmentService`, `HowTo`, and `FAQPage`) suitable for Large Language Models (LLMs), search engine optimization, and structured data indexing.

## Features

* **Stealth Scraping:** Uses `selenium-stealth` with Headless Chrome to bypass bot detection and scrape content effectively.
* **Markdown Conversion:** Converts HTML to "ATX" style Markdown, stripping unnecessary noise (navigation, footers, scripts) while preserving semantic structure.
* **GovCMS Compatibility:** Specifically targeted to handle `region-content` classes and GovCMS DOM structures.
* **Deterministic Schema Generation:** Parses Markdown headers and lists to generate valid JSON-LD for:
* `GovernmentService` (or `Service` / `HowTo` based on archetype).
* `HowTo` steps derived from content bodies.
* `FAQPage` generated from specific question-phrased headers.


* **Metadata Enrichment:** Merges scraped content with a static CSV metadata table to inject high-quality properties like `audience`, `legislation` links, and `provider` details.

## Project Structure

```text
DeterministicSchemaConversion/
├── IPFR-Webpages/           # Output directory for scraped Markdown files
├── json_output/             # Output directory for final JSON-LD files
├── scripts/
│   └── process_md_to_json.py # Logic to convert Markdown + CSV to JSON-LD
├── 260203_IPFRMetaTable.csv  # (Required) Metadata mapping table
├── scraper.py               # Selenium script to scrape URLs to Markdown
├── sources.json             # List of URLs to scrape
├── requirements.txt         # Python dependencies
└── README.md                # Project documentation

```

## Prerequisites

* **Python 3.8+**
* **Google Chrome** (The script uses `webdriver_manager` to handle the driver, but the browser must be installed).

## Installation

1. Clone the repository:
```bash
git clone https://github.com/your-username/DeterministicSchemaConversion.git
cd DeterministicSchemaConversion

```


2. Install the required Python packages:
```bash
pip install -r requirements.txt

```



## Usage

### Step 1: Define Sources

Ensure `sources.json` contains the list of URLs you wish to process. The format is a JSON array of objects containing the target `url` and the desired output `filename`.

**Example `sources.json`:**

```json
[
  {
    "url": "https://ipfirstresponse.ipaustralia.gov.au/options/mediation",
    "filename": "D1006 - Mediation.md"
  }
]

```

**

### Step 2: Scrape Content

Run the scraper to fetch the pages and convert them to Markdown. This will populate the `IPFR-Webpages/` directory.

```bash
python scraper.py

```

*Note: The scraper runs in headless mode but mimics a real user agent to ensure content loads correctly.*

### Step 3: Generate JSON-LD

Run the processing script to convert the Markdown files into structured JSON.

```bash
python scripts/process_md_to_json.py

```

This script will:

1. Read the Markdown files from `IPFR-Webpages/`.
2. Match the file against metadata in `260203_IPFRMetaTable.csv` (using URL, UDID, or Title matching).
3. Output the final JSON files into the `json_output/` directory.

## Configuration & Logic

### Metadata CSV

The script `process_md_to_json.py` relies on a CSV file (referenced internally as `260203_IPFRMetaTable.csv`) to enrich the structured data. This CSV should contain columns for:

* `UDID`: Unique Identifier.
* `Main Title`: The canonical title of the service.
* `Archetype`: Determines if the output is a `GovernmentService`, `HowTo` (Self-Help), or `Organization`.
* `Relevant IP right`: Used to generate `Legislation` citations and `about` topics.

### Schema Mapping

The generator uses specific heuristics to map Markdown content to Schema.org types:

* **Headers containing "steps" or "proceed":** Converted to `HowToStep`.
* **Headers starting with "What", "How", "Who":** Converted to `Question` / `Answer` pairs for `FAQPage`.
* **Legislation Keywords:** Automatically maps terms like "Trade Mark Act" or "Copyright Act" to their specific legislation URLs.

## Dependencies

* `selenium`: Browser automation.
* `selenium-stealth`: Anti-detection for Selenium.
* `webdriver-manager`: Automatic Chrome driver management.
* `markdownify`: HTML to Markdown conversion.
* `requests`: HTTP library (backup/utility).

## License

[Insert License Information Here]

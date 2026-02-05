# Deterministic Schema Conversion Pipeline

**A robust, hybrid-parsing toolchain for transforming unstructured government content into high-fidelity, Large Language Model (LLM) optimized Schema.org JSON-LD.**

---

## 📖 Overview

The **DeterministicSchemaConversion** pipeline is designed to solve a specific problem: bridging the gap between legacy government Content Management Systems (GovCMS/Drupal) and modern AI agents.

While standard web scrapers capture text, they often lose the semantic *intent* of the data (e.g., distinguishing a legal obligation from a general tip). This repository hosts a Python-based pipeline that digitizes **IP First Response** content, transforming it into structured data graphs including `GovernmentService`, `HowTo`, `FAQPage`, and `Legislation`.

### Why "Deterministic"?

Unlike purely generative AI scrapers that may "hallucinate" or alter facts, this pipeline uses a **deterministic rule set** for the core data extraction. It prioritizes:

1. **Structure Authority:** Using raw DOM traversal to identify process steps.
2. **Legal Accuracy:** Hardcoded mapping of IP rights (e.g., Trade Marks) to their specific Legislation Acts (e.g., *Trade Marks Act 1995*).
3. **Safety:** AI is strictly limited to an enrichment role (naming steps) and is gated by a rigorous semantic diff validator.

---

## 🏗️ Architecture

The pipeline operates in three distinct stages:

### 1. The Stealth Scraper (`scraper.py`)

Extracts content from the target domain using a "Stealth" Selenium driver to bypass bot detection.

* **Hybrid Output:** Saves two versions of every page:
* **Raw HTML (`.html`):** Preserves the exact DOM structure (lists, nested divs) for precise logic parsing.
* **Clean Markdown (`.md`):** Uses `markdownify` with custom regex cleaning to strip "noise" (feedback forms, footers, navigation) for clean text extraction.


* **Metadata Injection:** Automatically prepends YAML-like headers (URL, Title, Overtitle) to the Markdown files for downstream tracking.

### 2. The Semantic Processor (`process_md_to_json.py`)

This is the core logic engine. It ingests the scraped files + a Control Plane CSV to generate JSON-LD.

* **Archetype Mapping:** Converts business logic into Schema.org types:
* `Government Service` → `schema:GovernmentService`
* `Self-Help` → `schema:HowTo`
* `Organization` → `schema:Organization`


* **Dynamic FAQ Extraction:** Identifies headers ending in `?` or specific keywords (e.g., "Costs", "Risks", "Time") to build `FAQPage` schemas automatically.
* **Knowledge Base Injection:** Enriches data using internal dictionaries:
* **Legislation Map:** Automatically cites relevant Acts/Regulations based on the topic.
* **Provider Map:** Resolves entity names (e.g., "ASBFEO") to full Organization schemas.



### 3. The Safety-Gated Enrichment (`enrich_howto_steps.py`)

An optional step that uses **OpenAI (GPT-4o)** to improve data quality *without* risking data integrity.

* **The Problem:** `HowToStep` items often lack names in raw HTML (e.g., just a bullet point).
* **The Solution:** The LLM reads the step text and generates a short, 3-5 word summary name.
* **The Guardrail (Semantic Diff):** A recursive JSON comparator ensures the LLM *only* modified the designated `xXx_PLACEHOLDER_xXx` fields. If the LLM altered any factual text, dates, or logic, the file is flagged as **FAIL** and changes are discarded.

---

## 📂 Project Structure

```text
DeterministicSchemaConversion/
├── IPFR-Webpages/              # [Output] Cleaned Markdown (Human-readable text source)
├── IPFR-Webpages-html/         # [Output] Raw HTML (Structure source)
├── json_output/                # [Output] Initial Schema.org JSON-LD (Pre-enrichment)
├── json_output-enriched/       # [Output] Final AI-enriched JSON-LD (Production Ready)
├── scripts/
│   ├── process_md_to_json.py   # Core Logic: Hybrid parsing, schema mapping, and serialization
│   └── enrich_howto_steps.py   # AI Logic: GPT-4o step naming & Diff Validator
├── metatable-Content.csv       # [Config] The "Control Plane" metadata for all pages
├── scraper.py                  # [Script] Selenium-stealth scraper
├── sources.json                # [Config] List of target URLs to scrape
├── requirements.txt            # Python dependencies
└── README.md                   # Project Documentation

```

---

## 🛠️ Installation & Prerequisites

### Prerequisites

* **Python 3.8+**
* **Google Chrome** (Must be installed on the host machine for Selenium).
* **OpenAI API Key** (Required only if running the enrichment step).

### Setup

1. **Clone the repository:**
```bash
git clone https://github.com/your-org/DeterministicSchemaConversion.git
cd DeterministicSchemaConversion

```


2. **Install Python Dependencies:**
```bash
pip install -r requirements.txt

```



---

## ⚙️ Configuration

### 1. Source Definition (`sources.json`)

Define the URLs you wish to scrape.

```json
[
  {
    "url": "https://ipfirstresponse.ipaustralia.gov.au/options/mediation",
    "filename": "D1006 - Mediation.md"
  }
]

```

### 2. The Control Plane (`metatable-Content.csv`)

This CSV is **critical**. The processor uses it to enrich the scraped content with official metadata. It must contain the following headers:

| Header | Description | Example |
| --- | --- | --- |
| `UDID` | Unique Document ID | `D1006` |
| `Main-title` | Canonical Title for the schema | `Mediation for IP Disputes` |
| `Archectype` | Determines the Schema `@type` | `Government Service` or `Self-Help` |
| `Relevant-ip-right` | Triggers legislation citations | `Trade Mark, Copyright` |
| `Provider` | Entity providing the service | `ASBFEO` or `IP Australia` |
| `Description` | High-level summary | `A guide on mediating disputes...` |
| `Canonical-url` | The official URL | `https://...` |

---

## 🚀 Usage Workflow

### Step 1: Scrape Content

Run the scraper to fetch pages in "Stealth Mode".

```bash
python scraper.py

```

* **Result:** Populates `IPFR-Webpages/` (MD) and `IPFR-Webpages-html/` (HTML).

### Step 2: Generate Structured Data

Run the processor to convert content into JSON-LD.

```bash
python scripts/process_md_to_json.py

```

* **Result:** Populates `json_output/`.
* *Note:* At this stage, `HowToStep` names will be `xXx_PLACEHOLDER_xXx`.

### Step 3: AI Enrichment (Optional)

Use GPT-4o to intelligently name the steps.

```bash
# Set API Key (Linux/Mac)
export OPENAI_API_KEY="sk-..."

# Run Enrichment
python scripts/enrich_howto_steps.py

```

* **Result:** Populates `json_output-enriched/`.
* **Audit:** Check `after_action_report.csv` to see exactly what the AI changed.

---

## 🧩 Schema Details

The pipeline generates complex, nested JSON-LD objects.

### Supported Types

* **`GovernmentService`:** For official services (e.g., "Apply for a Trade Mark").
* **`HowTo`:** For guides and self-help wizards.
* **`FAQPage`:** Aggregates questions found within the page content.
* **`Legislation`:** Automatically linked based on the "Relevant IP right" in the CSV.

### The "Knowledge Base" Maps

The system contains hardcoded dictionaries in `process_md_to_json.py` to ensure consistency:

* **Legislation:** Maps "patent" to *Patents Act 1990* and *Patents Regulations 1991*.
* **Providers:** Maps "ASBFEO" to their specific `GovernmentOrganization` schema.
* **Audience:** Defaults to `Australian Small Business Owners` (`BusinessAudience`).

---

## 🛡️ Safety Protocols

This project implements a **Strict Semantic Diff** in `scripts/enrich_howto_steps.py`.

When the LLM returns a response, the script performs a recursive comparison between the input JSON and the output JSON:

1. **Topology Check:** Did the LLM add or remove any keys? (Fail if yes)
2. **Type Check:** Did a list become a string? (Fail if yes)
3. **Value Check:** Did a value change?
* If the original value was `xXx_PLACEHOLDER_xXx`, the change is **ALLOWED**.
* If the original value was anything else (e.g., the step description text), the change is **DENIED**.



This ensures that the AI **cannot** hallucinate new steps, alter legal text, or change URLs. It can *only* fill in the specific blanks we explicitly left for it.

## 📝 License

[Insert License Information Here]

# 🕸️ Deterministic Schema Conversion Pipeline

> **A robust, hybrid-parsing toolchain for transforming unstructured government content into high-fidelity, Large Language Model (LLM) optimized Schema.org JSON-LD.**

---

## 📖 Overview

In the age of AI agents and RAG (Retrieval-Augmented Generation), unstructured HTML is a bottleneck. The **Deterministic Schema Conversion** pipeline bridges the gap between legacy Government Content Management Systems (GovCMS/Drupal) and modern AI consumers.

Unlike generic scrapers that "guess" the content structure, this pipeline uses a **deterministic, rule-based engine** to extract legal obligations, government services, and self-help guides with 100% factual integrity. It reserves Generative AI (GPT-4o) strictly for "cosmetic enrichment"—naming steps or summarizing descriptions—while enforcing a rigorous **Semantic Diff Guardrail** to prevent hallucinations.

### 🌟 Key Features

* **🕵️ Stealth Scraping:** Bypasses WAFs and bot detection using a headless "Stealth" Selenium driver.
* **🧠 Hybrid Parsing:** Synthesizes raw DOM structure (HTML) with clean text extraction (Markdown) for maximum precision.
* **🛡️ Safety-First AI:** Uses LLMs *only* to fill specific placeholders. A recursive JSON comparator ensures no facts, dates, or laws are altered.
* **⚖️ Legal Accuracy:** Hardcoded "Knowledge Bases" automatically map keywords to specific Legislation Acts (e.g., *Trade Marks Act 1995*).
* **✅ Automated QA:** A built-in validation layer compares the final JSON against the source HTML to detect data drift.

---

## 🏗️ System Architecture

The pipeline operates in four distinct stages, moving from raw web content to validated structured data.

### Stage 1: The Stealth Scraper (`scraper.py`)

*See [docs/scraper-architecture.md](https://www.google.com/search?q=docs/scraper-architecture.md) for details.*

We employ a "Headless Browser" approach to render dynamic content before extraction.

* **Bot Evasion:** Uses `selenium-stealth` to mock user behaviors, user-agents, and WebGL vendors, appearing as a legitimate Windows 10 user.
* **Dual Output:** Saves two versions of every page:
* **`.html` (The Structure):** Preserves the exact DOM (lists, nested divs) for logic parsing.
* **`.md` (The Content):** Uses `markdownify` with custom regex to strip UI noise (feedback forms, footers) for clean RAG ingestion.



### Stage 2: The Semantic Processor (`process_md_to_json.py`)

*See [docs/json_generation_logic.md](https://www.google.com/search?q=docs/json_generation_logic.md) for details.*

The core logic engine converts content into Schema.org entities (`GovernmentService`, `HowTo`, `FAQPage`) using a "Control Plane" CSV.

* **Archetype Mapping:** Automatically casts content types based on metadata (e.g., "Self-Help" → `schema:HowTo`).
* **Dynamic FAQ Extraction:** Identifies headers ending in `?` to build `FAQPage` schemas automatically.
* **Legislation Injection:** Scans content for IP rights (e.g., "Patent") and injects precise legal citations from an internal dictionary.

### Stage 3: Safety-Gated Enrichment (`enrich_howto_steps.py`)

*See [docs/json_enrichment.md](https://www.google.com/search?q=docs/json_enrichment.md) for details.*

An optional step that uses **GPT-4o** to polish the data without risking integrity.

* **The Task:** LLMs replace specific `xXx_PLACEHOLDER_xXx` values (e.g., naming a generic bullet point).
* **The Guardrail:** A **Semantic Diff Check** compares input vs. output.
* Did the LLM change a date? ❌ **FAIL**
* Did the LLM add a new step? ❌ **FAIL**
* Did the LLM only rename the placeholder? ✅ **PASS**



### Stage 4: Quality Validation (`validate_quality.py`)

*See [docs/validation_architecture.md](https://www.google.com/search?q=docs/validation_architecture.md) for details.*

The final gatekeeper. It compares the generated JSON-LD back against the source HTML.

* **ID Consistency:** Ensures the file ID (e.g., `B1000`) matches the JSON identifier.
* **Semantic Text Matching:** Uses fuzzy logic to ensure the `description` in JSON actually exists on the webpage (>85% similarity required).
* **Link Integrity:** Verifies that every `relatedLink` in the schema is a valid anchor tag in the source DOM.

---

## 📂 Project Structure

```text
DeterministicSchemaConversion/
├── IPFR-Webpages/              # [Output] Cleaned Markdown (Human-readable source)
├── IPFR-Webpages-html/         # [Output] Raw HTML (Structure source)
├── json_output/                # [Output] Initial Schema.org JSON-LD (Pre-enrichment)
├── json_output-enriched/       # [Output] Final AI-enriched JSON-LD (Production Ready)
├── reports/
│   ├── validation_reports/     # [Audit] CSV reports of Quality Checks
│   └── after_action_report.csv # [Audit] Log of AI modifications
├── scripts/
│   ├── scraper.py              # Stage 1: Selenium-stealth scraper
│   ├── process_md_to_json.py   # Stage 2: Hybrid parsing & mapping logic
│   ├── enrich_howto_steps.py   # Stage 3: AI Enrichment & Diff Validator
│   └── validate_quality.py     # Stage 4: Structural & Semantic QA
├── docs/                       # Detailed Architecture Documentation
├── metatable-Content.csv       # [Config] The "Control Plane" metadata
├── sources.json                # [Config] List of target URLs
└── requirements.txt            # Python dependencies

```

---

## 🛠️ Installation & Setup

### Prerequisites

* **Python 3.8+**
* **Google Chrome** (Must be installed on the host machine for Selenium).
* **OpenAI API Key** (Required only for Stage 3).

### Quick Start

1. **Clone the repository:**
```bash
git clone https://github.com/your-org/DeterministicSchemaConversion.git
cd DeterministicSchemaConversion

```


2. **Install Dependencies:**
```bash
pip install -r requirements.txt

```


3. **Configure Environment (Optional):**
```bash
export OPENAI_API_KEY="sk-..."  # Only needed for enrichment

```



---

## 🚀 Usage Workflow

### 1. Define Your Sources

Edit `sources.json` to add URLs and `metatable-Content.csv` to define the metadata (Title, UDID, Provider) for those URLs.

### 2. Run the Scraper (Stage 1)

Fetches content in "Stealth Mode" to avoid detection.

```bash
python scripts/scraper.py

```

* **Output:** Populates `IPFR-Webpages/` and `IPFR-Webpages-html/`.

### 3. Generate Structured Data (Stage 2)

Converts the scraped content into raw JSON-LD.

```bash
python scripts/process_md_to_json.py

```

* **Output:** Populates `json_output/`. Steps will have `xXx_PLACEHOLDER_xXx` names.

### 4. Enrich with AI (Stage 3 - Optional)

Uses GPT-4o to intelligently name steps and write descriptions, guarded by the Diff Checker.

```bash
python scripts/enrich_howto_steps.py

```

* **Output:** Populates `json_output-enriched/`.
* **Audit:** Check `after_action_report.csv` to see exactly what changed.

### 5. Validate Quality (Stage 4)

Runs the full suite of integrity checks.

```bash
python scripts/validate_quality.py

```

* **Output:** Generates `reports/validation_reports/Validation_Report.csv` with Pass/Fail statuses.

---

## 🧩 The "Control Plane" Configuration

The `metatable-Content.csv` is the brain of the operation. It dictates how the raw content is interpreted.

| Header | Description | Example |
| --- | --- | --- |
| **UDID** | Unique Document ID | `D1006` |
| **Main-title** | Canonical Title for the schema | `Mediation for IP Disputes` |
| **Archectype** | Determines the Schema `@type` | `Government Service` or `Self-Help` |
| **Relevant-ip-right** | Triggers legislation citations | `Trade Mark, Copyright` |
| **Provider** | Entity providing the service | `ASBFEO` or `IP Australia` |

---

## 🛡️ Safety & Compliance

We prioritize data integrity over AI creativity.

1. **Topology Check:** The AI cannot add or remove keys.
2. **Type Check:** The AI cannot change a list to a string.
3. **Value Check:** The AI can **only** change values that were explicitly marked as `xXx_PLACEHOLDER_xXx`.

*If the AI attempts to "fix" a typo in a legal citation or change a date, the Diff Checker will **reject the entire file** and flag it for human review.*

---

## 📝 License

[Insert License Information Here]

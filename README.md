# Deterministic Schema Conversion: System Architecture & Logic

## 1. System Ontology & Objective

**System Goal:** To deterministically transform unstructured government web content (HTML/GovCMS) into high-fidelity, validated Schema.org JSON-LD, optimized for consumption by Large Language Models (LLMs) and RAG agents.

**Core Philosophy:**

* **Deterministic Ingestion:** Content extraction is rule-based, not probabilistic.
* **Hybrid Parsing:** Utilization of both raw DOM (HTML) for structure and Markdown (MD) for clean text.
* **Safety-Gated AI:** Generative AI is restricted to "cosmetic" enrichment (naming, summarization) and is sandboxed by a Semantic Diff Guardrail.
* **Immutable Truth:** The `metatable-Content.csv` acts as the single source of truth for metadata.

---

## 2. The Control Plane (`metatable-Content.csv`)

The entire pipeline is orchestrated by a central configuration file. The system does not crawl; it iterates through this manifest.

| Field | Function | System Behavior |
| --- | --- | --- |
| **UDID** | Unique Document ID (e.g., `B1005`) | Used as the immutable primary key for file naming, validation, and traceability. |
| **Main-title** | Canonical Title | Overrides the scraping title to ensure consistency in the Schema `name` field. |
| **Canonical-url** | Target URL | The specific endpoint targeted by the Selenium scraper. |
| **Archetype** | Schema Classification | Determines the root `@type` of the generated JSON (e.g., `GovernmentService` vs `Article`). |
| **Relevant-ip-right** | Legislation Trigger | Keywords (e.g., "Patent") trigger the injection of specific `citation` objects linking to the *Patents Act 1990*. |
| **Provider** | Service Owner | Maps to specific `Organization` objects (e.g., `IP Australia`) in the output JSON. |

---

## 3. Data Pipeline Architecture

The system operates in a linear, five-stage pipeline.

### Stage 1: Ingestion (Stealth Scraper)

**Script:** `scripts/scraper.py`
**Input:** `metatable-Content.csv`
**Output:** `IPFR-Webpages-html/` (Raw HTML) & `IPFR-Webpages/` (Clean Markdown)

**Operational Logic:**

1. **Bot Evasion:** Utilizing `selenium-stealth`, the scraper mocks a Windows 10/Chrome environment, overriding `navigator.webdriver`, User-Agent, and WebGL vendor flags to bypass Government WAFs.
2. **DOM Isolation:** Content is extracted via a priority cascade:
* *Priority 1:* `<main>` tag (Semantic standard).
* *Priority 2:* `.region-content` (GovCMS specific wrapper).
* *Fallback:* `<body>`.


3. **Dual-State Serialization:**
* **HTML Preservation:** The raw DOM of the isolated region is saved as `.html` to preserve nested `<div>` and `<ul>` structures for logic parsing.
* **Markdown Normalization:** The content is passed through `markdownify` with custom Regex filters to strip UI noise (feedback widgets, "back to top" links) and normalize headers, producing a clean `.md` file for RAG ingestion.



### Stage 2: Transformation (Semantic Processor)

**Script:** `scripts/process_md_to_json.py`
**Input:** `IPFR-Webpages/*.md`, `IPFR-Webpages-html/*.html`, `metatable-Content.csv`
**Output:** `json_output/*.json`

**Operational Logic:**

1. **Metadata Association:** The script iterates `.md` files and matches them to the CSV Control Plane via URL, UDID, or Fuzzy Title Match.
2. **Block Parsing:** The content is segmented into Key/Value blocks.
* *HTML Parser:* Uses BeautifulSoup to extract text between `<h>` tags, preserving semantic structure.
* *Markdown Fallback:* Splits content by `#` headers if HTML is invalid.


3. **Schema Construction:**
* **Root Type:** Mapped from CSV Archetype (e.g., "Self-Help" → `schema:Article`).
* **HowTo Extraction:** Detects headers containing "step" or "proceed" and parses child list items into `HowToStep` objects.
* **FAQ Extraction:** Headers ending in `?` are automatically converted to `Question`/`Answer` objects.
* **Placeholder Injection:** Specific fields (Step Names, Descriptions) are populated with explicit tokens: `xXx_PLACEHOLDER_xXx`.


4. **Legislation Injection:** The `citation` array is populated by cross-referencing the `Relevant-ip-right` CSV column against an internal `LEGISLATION_MAP` (e.g., mapping "Trade Mark" to the *Trade Marks Act 1995*).

### Stage 3: Enrichment (Safety-Gated AI)

**Script:** `scripts/enrich_howto_steps.py`
**Input:** `json_output/*.json`
**Output:** `json_output-enriched/*.json`, `reports/after_action_report.csv`

**Operational Logic:**

1. **Recursive Traversal:** The script walks the JSON tree looking specifically for values matching `xXx_PLACEHOLDER_xXx`.
2. **Contextual Prompting:**
* *Scenario A (Step Name):* Reads the step `text`; generates a short imperative title.
* *Scenario B (Description):* Reads the `headline` and sub-entities; generates a 160-char SEO summary.
* *Scenario C (Service Type):* Infers Schema classification.


3. **Semantic Diff Guardrail:** Post-generation, the script compares the Input JSON vs. Output JSON.
* **Pass Condition:** Only values associated with known placeholders have changed.
* **Fail Condition:** Any change to structure (keys added/removed), types (list → string), or non-placeholder values (dates, legal citations).
* *Result:* If validation fails, the file is rejected to prevent "hallucinations."



### Stage 4: Quality Assurance (Validation)

**Script:** `scripts/validate_quality.py`
**Input:** `json_output-enriched/` vs. `IPFR-Webpages-html/`
**Output:** `reports/validation_reports/Validation_Report.csv`

**Operational Logic:**

1. **Identity Check:** Verifies the UDID in the filename (e.g., `B1005`) matches the `identifier` field in the JSON payload.
2. **Schema Syntax:** Validates the presence of mandatory Schema.org keys (`@context`, `@type`, `headline`).
3. **Semantic Grounding (Fuzzy Match):**
* Compares the `description` and `text` fields in the JSON against the raw HTML.
* Requires >85% similarity (via `difflib`) to ensure the Schema accurately reflects the webpage content.


4. **FAQ Verification:** Ensures every `Question` object in the JSON actually exists as text in the source HTML (prevents invented questions).
5. **Link Integrity:** Verifies that every `relatedLink` URL in the JSON exists as an `href` anchor in the source DOM.

### Stage 5: Normalization (Relational Flattening)

**Script:** `scripts/json_to_csv.py`
**Configuration:** `scripts/schema_mapping.yaml`
**Input:** `json_output-enriched/`, `IPFR-Webpages/`, `IPFR-Webpages-html/`
**Output:** `sqlite_data/` (CSV & Excel)

**Operational Logic:**

1. **Registry Construction:** The system pre-scans all Markdown, HTML, and JSON assets to build a global `URL -> UDID` map. This enables the script to detect "Internal Links" and replace raw URLs with precise Document IDs (e.g., `B1005`) for knowledge graph integrity.
2. **Schema Projection:** utilizing `jsonpath-ng`, the script flattens the hierarchical JSON-LD into 7 relational tables defined in the YAML config:
* **Primary/Influences:** Core metadata and legislative citations.
* **LinksTo:** Graph edges containing outbound links with computed internal resolution.
* **HowTo/FAQ:** Exploded views of procedural steps and Q&A pairs.
* **RawData:** Contains the full text payload of HTML, MD, and JSON versions.


3. **Tokenization Metrics:** Uses OpenAI's `tiktoken` (cl100k_base encoding) to calculate and append precise token counts for every file version (HTML vs MD vs JSON). This data allows developers to optimize context-window usage for RAG applications.

---

## 4. Directory Structure Map

```text
DeterministicSchemaConversion/
├── IPFR-Webpages/              # [Context] Cleaned Markdown (Human/LLM readable)
├── IPFR-Webpages-html/         # [Context] Raw HTML (Source of Truth for Validation)
├── json_output/                # [Intermediate] Schema containing xXx_PLACEHOLDER_xXx
├── json_output-enriched/       # [Artifact] Final, Validated, AI-Enriched JSON-LD
├── sqlite_data/                # [Artifact] Relational Tables (CSV/XLSX) with Token Counts
├── reports/
│   ├── validation_reports/     # [Log] QA Pass/Fail CSVs
│   └── after_action_report.csv # [Log] AI modification audit trail
├── scripts/
│   ├── scraper.py              # [Logic] Selenium Stealth implementation
│   ├── process_md_to_json.py   # [Logic] Hybrid Parser & Schema Mapper
│   ├── enrich_howto_steps.py   # [Logic] recursive_enrich() & perform_diff_check()
│   ├── validate_quality.py     # [Logic] Structural & Semantic comparators
│   ├── json_to_csv.py          # [Logic] Relational Flattener & Token Counter
│   └── schema_mapping.yaml     # [Config] Mapping rules for Stage 5
├── metatable-Content.csv       # [Config] The Control Plane
└── sources.json                # [Config] Scraper target list

```

---

## 5. Key Algorithms & Heuristics

### The Archetype Mapper

Located in `process_md_to_json.py`, this maps CSV metadata to Schema Types:

| CSV Archetype | JSON-LD `@type` | Note |
| --- | --- | --- |
| `Self-Help` | `Article` | Previously `HowTo`, mapped to Article for broader search support. |
| `Government Service` | `GovernmentService` | Includes `serviceOperator` details. |
| `Commercial` | `Service` | Generic service fallback. |
| `Non-Government` | `Service` | Generic service fallback. |

### The Semantic Diff Check

Located in `enrich_howto_steps.py`, this enforces the "Zero-Hallucination" policy:

1. **Topology Check:** `len(input_keys) == len(output_keys)`
2. **Type Check:** `type(input_val) == type(output_val)`
3. **Mutation Check:** `if input_val != output_val AND input_val NOT IN [TARGET_PLACEHOLDERS] -> FAIL`

### The Relational Tokenizer

Located in `json_to_csv.py`, this calculates cost metrics:

1. **Encoding:** Loads `cl100k_base` (GPT-4 standard).
2. **Resolution:** Calculates tokens for `HTML_Raw`, `MD_Raw`, and `JSON_Raw` independently.
3. **Purpose:** Enables precise cost-benefit analysis of using Markdown vs. JSON for LLM Context Windows.

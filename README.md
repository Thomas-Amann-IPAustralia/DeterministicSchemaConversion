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

Auto-discovered pages from the Sitemap Monitor receive an `A`-prefix UDID (e.g., `A1000`) to distinguish them from manually curated entries.

---

## 3. Primary Pipeline (Automated)

The primary pipeline runs automatically every Sunday (or on manual trigger) and chains four stages:

```
Sitemap Monitor ──► Stage 1: Scrape ──► Stage 2: JSON-LD ──► Stage 5: Normalize
(check_sitemap)     (scrape)             (process_json)       (stage5_normalization)
```

Each stage dispatches the next automatically when changes are detected.

### Sitemap Monitor

**Script:** `scripts/check_sitemap.py`
**Workflow:** `.github/workflows/check_sitemap.yml`
**Schedule:** Every Sunday at midnight UTC (also manually triggerable)

**Operational Logic:**

1. Fetches `sitemap.xml` from `ipfirstresponse.ipaustralia.gov.au` via Selenium stealth (site is behind a WAF).
2. Filters for URLs containing `/options/`.
3. Compares discovered URLs against the `Canonical-url` column in `metatable-Content.csv`.
4. Appends new URLs to the CSV with auto-generated `A`-prefix UDIDs and titles derived from URL slugs. Existing rows are never modified or deleted.
5. If new URLs are found, dispatches **Stage 1 (Scraper)**.

### Stage 1: Ingestion (Stealth Scraper)

**Script:** `scripts/scraper.py`
**Workflow:** `.github/workflows/scrape.yml`
**Input:** `metatable-Content.csv`
**Output:** `IPFR-Webpages-html/` (Raw HTML) & `IPFR-Webpages/` (Clean Markdown)

**Operational Logic:**

1. **Bot Evasion:** Utilizing `selenium-stealth`, the scraper mocks a Windows 10/Chrome environment, overriding `navigator.webdriver`, User-Agent, and WebGL vendor flags to bypass Government WAFs.
2. **DOM Isolation:** Content is extracted via a priority cascade:
   * *Priority 1:* `<main>` tag (Semantic standard).
   * *Priority 2:* `.region-content` (GovCMS specific wrapper).
   * *Fallback:* `<body>`.
3. **Dual-State Serialization:**
   * **HTML Preservation:** The raw DOM of the isolated region is saved as `.html`.
   * **Markdown Normalization:** Content is passed through `markdownify` with custom Regex filters to strip UI noise, producing a clean `.md` file.
4. If content changes are detected, dispatches **Stage 2 (JSON-LD Generation)**.

### Stage 2: Transformation (Semantic Processor)

**Script:** `scripts/process_md_to_json.py`
**Workflow:** `.github/workflows/process_json.yml`
**Input:** `IPFR-Webpages/*.md`, `IPFR-Webpages-html/*.html`, `metatable-Content.csv`
**Output:** `json_output/*.json`

**Operational Logic:**

1. **Metadata Association:** Matches `.md` files to the CSV Control Plane via URL, UDID, or Fuzzy Title Match.
2. **Block Parsing:** Segments content into Key/Value blocks using HTML structure or Markdown headers.
3. **Schema Construction:**
   * **Root Type:** Mapped from CSV Archetype (e.g., "Self-Help" → `schema:Article`).
   * **HowTo Extraction:** Detects headers containing "step" or "proceed" and parses child list items into `HowToStep` objects.
   * **FAQ Extraction:** Headers ending in `?` are converted to `Question`/`Answer` objects.
   * **Placeholder Injection:** Specific fields populated with `xXx_PLACEHOLDER_xXx` tokens.
4. **Legislation Injection:** The `citation` array is populated by cross-referencing `Relevant-ip-right` against an internal `LEGISLATION_MAP`.
5. After completion, dispatches **Stage 5 (Normalization)**.

### Stage 5: Normalization (Relational Flattening)

**Script:** `scripts/json_to_csv.py`
**Configuration:** `scripts/schema_mapping.yaml`
**Workflow:** `.github/workflows/stage5_normalization.yml`
**Input:** `json_output-enriched/`, `IPFR-Webpages/`, `IPFR-Webpages-html/`
**Output:** `sqlite_data/` (CSV & Excel)

**Operational Logic:**

1. **Registry Construction:** Pre-scans all assets to build a global `URL → UDID` map for internal link resolution.
2. **Schema Projection:** Flattens hierarchical JSON-LD into 7 relational tables (Primary, Influences, LinksTo, HowTo, FAQ, Semantic, RawData).
3. **Tokenization Metrics:** Uses `tiktoken` (cl100k_base encoding) to calculate token counts for HTML, MD, and JSON versions.

---

## 4. Optional Stages (Manual Trigger Only)

These stages are not part of the automated pipeline. They can be triggered manually via GitHub Actions when needed.

### Optional - LLM Enrichment

**Script:** `scripts/enrich_howto_steps.py`
**Workflow:** `.github/workflows/optional_enrich_json.yml`
**Input:** `json_output/*.json`
**Output:** `json_output-enriched/*.json`, `reports/after_action_report.csv`

Replaces `xXx_PLACEHOLDER_xXx` tokens with LLM-generated content (step names, descriptions) using OpenAI. Protected by a Semantic Diff Guardrail that rejects any unauthorized structural changes.

### Optional - Quality Validation

**Script:** `scripts/validate_quality.py`
**Workflow:** `.github/workflows/optional_validate_quality.yml`
**Input:** `json_output-enriched/` vs. `IPFR-Webpages-html/`
**Output:** `reports/validation_reports/Validation_Report_Extended.csv`

Validates enriched JSON against source HTML: identity checks, schema syntax, semantic grounding (>85% similarity), FAQ verification, and link integrity.

### Optional - Semantic Embeddings

**Script:** `scripts/generate_embeddings.py`
**Workflow:** `.github/workflows/optional_create_embeddings.yml`
**Input:** `sqlite_data/Semantic.xlsx`
**Output:** `sqlite_data/Semantic_Embeddings_Output.*`

Generates vector embeddings via OpenAI `text-embedding-3-small` for RAG/semantic search applications.

### Optional - Load JSON into XLSX

**Script:** `scripts/load_json_output_into_xlsx.py`
**Workflow:** `.github/workflows/optional_load_json_xlsx.yml`

Legacy utility to populate an Excel template with JSON data.

---

## 5. Manual Triggering

Any pipeline stage can be triggered manually via the GitHub Actions UI:

1. Go to the **Actions** tab in the repository.
2. Select the desired workflow from the left sidebar.
3. Click **Run workflow** and select the branch.

The automated dispatch chain (Sitemap → Scrape → JSON-LD → Normalize) will fire downstream stages automatically when changes are detected. Optional stages must always be triggered manually.

---

## 6. Directory Structure

```text
DeterministicSchemaConversion/
├── .github/workflows/
│   ├── check_sitemap.yml              # [Automated] Sitemap Monitor (weekly)
│   ├── scrape.yml                     # [Automated] Stage 1 - Stealth Scraper
│   ├── process_json.yml               # [Automated] Stage 2 - JSON-LD Generation
│   ├── stage5_normalization.yml       # [Automated] Stage 5 - Relational Normalization
│   ├── optional_enrich_json.yml       # [Optional]  LLM Enrichment
│   ├── optional_validate_quality.yml  # [Optional]  Quality Validation
│   ├── optional_create_embeddings.yml # [Optional]  Semantic Embeddings
│   └── optional_load_json_xlsx.yml    # [Optional]  XLSX Loader
├── scripts/
│   ├── check_sitemap.py               # Sitemap monitor logic
│   ├── scraper.py                     # Selenium stealth scraper
│   ├── process_md_to_json.py          # Hybrid parser & Schema mapper
│   ├── json_to_csv.py                 # Relational flattener & token counter
│   ├── schema_mapping.yaml            # Table mapping config for Stage 5
│   ├── enrich_howto_steps.py          # LLM enrichment with diff guardrail
│   ├── validate_quality.py            # Structural & semantic validation
│   ├── generate_embeddings.py         # Vector embedding generator
│   └── load_json_output_into_xlsx.py  # Legacy XLSX loader
├── metatable-Content.csv              # [Control Plane] Master manifest
├── IPFR-Webpages/                     # [Stage 1 Output] Cleaned Markdown
├── IPFR-Webpages-html/                # [Stage 1 Output] Raw HTML
├── json_output/                       # [Stage 2 Output] JSON-LD with placeholders
├── json_output-enriched/              # [Optional Output] AI-enriched JSON-LD
├── sqlite_data/                       # [Stage 5 Output] Relational CSV/XLSX tables
├── reports/                           # Validation reports & audit trails
├── docs/                              # Architecture documentation
├── requirements.txt                   # Python dependencies
└── 260305_DB-Strcuture_05.xlsx        # Target database structure template
```

---

## 7. Key Algorithms & Heuristics

### The Archetype Mapper

Located in `scripts/process_md_to_json.py`, maps CSV metadata to Schema Types:

| CSV Archetype | JSON-LD `@type` | Note |
| --- | --- | --- |
| `Self-Help` | `Article` | Previously `HowTo`, mapped to Article for broader search support. |
| `Government Service` | `GovernmentService` | Includes `serviceOperator` details. |
| `Commercial` | `Service` | Generic service fallback. |
| `Non-Government` | `Service` | Generic service fallback. |

### The Semantic Diff Check

Located in `scripts/enrich_howto_steps.py`, enforces the "Zero-Hallucination" policy:

1. **Topology Check:** `len(input_keys) == len(output_keys)`
2. **Type Check:** `type(input_val) == type(output_val)`
3. **Mutation Check:** `if input_val != output_val AND input_val NOT IN [TARGET_PLACEHOLDERS] -> FAIL`

### The Relational Tokenizer

Located in `scripts/json_to_csv.py`, calculates cost metrics:

1. **Encoding:** Loads `cl100k_base` (GPT-4 standard).
2. **Resolution:** Calculates tokens for `HTML_Raw`, `MD_Raw`, and `JSON_Raw` independently.
3. **Purpose:** Enables precise cost-benefit analysis of using Markdown vs. JSON for LLM Context Windows.

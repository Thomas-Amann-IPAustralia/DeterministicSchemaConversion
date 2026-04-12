# CLAUDE.md — DeterministicSchemaConversion

## Project Overview

DeterministicSchemaConversion is an automated pipeline that converts unstructured government web content (HTML from the IPFR / GovCMS platform) into validated Schema.org JSON-LD data structures. The pipeline is entirely **rule-based and deterministic** — no probabilistic ML in the core path. LLM calls (GPT-4o) are used only as a safety-gated optional enrichment step.

The output is optimised for LLM/RAG consumption: clean Schema.org JSON-LD plus relational CSV/XLSX tables with token counts.

---

## Repository Layout

```
DeterministicSchemaConversion/
├── metatable-Content.csv          # CONTROL PLANE — master manifest, ~200 rows
├── requirements.txt               # Python dependencies
├── scripts/                       # Core pipeline scripts (all Python 3.9+)
│   ├── check_sitemap.py           # Stage 0: sitemap monitor
│   ├── scraper.py                 # Stage 1: Selenium stealth scraper
│   ├── process_md_to_json.py      # Stage 2: JSON-LD generator (largest/most complex)
│   ├── json_to_csv.py             # Stage 5: relational normaliser
│   ├── schema_mapping.yaml        # Config for Stage 5 table mappings (JSONPath)
│   ├── enrich_howto_steps.py      # Optional Stage 3: GPT-4o enrichment
│   ├── validate_quality.py        # Optional Stage 4: QA validation
│   ├── generate_embeddings.py     # Optional: vector embeddings
│   └── load_json_output_into_xlsx.py  # Legacy XLSX loader
├── IPFR-Webpages/                 # Stage 1 output: cleaned Markdown
├── IPFR-Webpages-html/            # Stage 1 output: raw HTML DOM
├── json_output/                   # Stage 2 output: JSON-LD (134 files)
├── json_output-enriched/          # Stage 3 output: AI-enriched JSON-LD
├── sqlite_data/                   # Stage 5 output: relational tables (CSV + XLSX, ~40 MB)
├── reports/                       # Validation and audit reports
├── docs/                          # Architecture documentation
└── .github/workflows/             # GitHub Actions (automated pipeline)
```

---

## Pipeline Architecture

The pipeline runs in numbered stages. Each automated stage dispatches the next when it detects changes.

```
[Stage 0] check_sitemap.py       — weekly cron, discovers new /options/ URLs
      ↓ dispatches on change
[Stage 1] scraper.py             — Selenium stealth → saves .md + .html per page
      ↓ dispatches on change
[Stage 2] process_md_to_json.py  — builds Schema.org JSON-LD from .md + CSV metadata
      ↓ dispatches on change
[Stage 5] json_to_csv.py         — flattens JSON-LD → 7 relational tables

[Optional] enrich_howto_steps.py — GPT-4o fills xXx_PLACEHOLDER_xXx tokens
[Optional] validate_quality.py   — 5-layer QA cross-validation
[Optional] generate_embeddings.py — vector embeddings for RAG
```

All stages are also triggerable manually via `workflow_dispatch` in GitHub Actions.

---

## Control Plane: metatable-Content.csv

Every script reads this file as its source of truth. **Do not rename or move it.**

Key columns:

| Column | Description |
|--------|-------------|
| `UDID` | Unique Document ID (e.g., `B1005`). Auto-discovered pages get `A`-prefix IDs. |
| `Main-title` | Canonical title (overrides scraped content) |
| `Canonical-url` | Target URL to scrape |
| `Archetype` | Controls JSON-LD `@type`: `Self-Help`→`Article`, `Government Service`→`GovernmentService`, `Commercial`/`Non-Government`→`Service` |
| `Relevant-ip-right` | Triggers legislation citation injection (`Patent`, `Trade Mark`, `Design`, etc.) |
| `Provider` | Service owner string |
| `Overtitle` | Contextual prefix for titles |
| `Description` | SEO description |
| `Last-updated` | Timestamp; auto-stamped by sitemap monitor |

---

## Development Commands

### Setup

```bash
pip install -r requirements.txt
# Requires Python 3.9+ and Chrome (for Selenium)
```

### Run Stages Locally (Sequential)

```bash
# Stage 0 – discover new sitemap URLs (optional; auto-runs weekly on CI)
python scripts/check_sitemap.py

# Stage 1 – scrape all pages in metatable-Content.csv
python scripts/scraper.py

# Stage 2 – generate JSON-LD from scraped Markdown
python scripts/process_md_to_json.py

# Stage 5 – flatten JSON-LD into relational tables
python scripts/json_to_csv.py \
  --config scripts/schema_mapping.yaml \
  --source json_output-enriched \
  --output sqlite_data \
  --md-source IPFR-Webpages \
  --html-source IPFR-Webpages-html
```

### Optional Enrichment (requires `OPENAI_API_KEY`)

```bash
python scripts/enrich_howto_steps.py
# Reads json_output/, writes json_output-enriched/
# Replaces xXx_PLACEHOLDER_xXx tokens via GPT-4o
# Protected by semantic diff guardrail (rejects structural mutations)
```

### Quality Validation

```bash
python scripts/validate_quality.py
# Writes reports/validation_reports/Validation_Report_Extended.csv
```

### No Test Suite

There is no automated test suite (no pytest, unittest, etc.). Validation is done via:
1. `validate_quality.py` — 5-layer QA (structure, schema, identity, semantic similarity, link integrity)
2. GitHub Actions integration checks (asserts outputs exist and are non-empty)
3. Manual spot-checks on generated JSON-LD

---

## Key Technical Details

### File Naming Convention

Output files follow `{UDID}_{slug}` naming:
- `IPFR-Webpages/B1005_receiving-a-letter-of-demand.md`
- `json_output/B1005_receiving-a-letter-of-demand.json`

### JSON-LD Structure (Stage 2 Output)

Each file contains a Schema.org `@graph` with:
- `WebPage` — root entity (metadata, dates, provider)
- Main entity — `Article` / `GovernmentService` / `Service` (driven by `Archetype`)
- `HowTo` with `HowToStep` arrays — steps parsed from Markdown headers
- `FAQPage` — Q&A pairs detected heuristically
- Citation objects — legislation links injected from CSV metadata
- `WebPageElement` — named content sections

Placeholders (`xXx_PLACEHOLDER_xXx`) mark fields where content was not deterministically extractable. These are filled by Stage 3 (optional LLM enrichment).

### Semantic Diff Guardrail (Stage 3)

The LLM enrichment script enforces strict constraints:
- **Topology check**: `len(input_keys) == len(output_keys)` — no keys added/removed
- **Type check**: `type(input_val) == type(output_val)` — no type changes
- **Mutation check**: Only `xXx_PLACEHOLDER_xXx` values may change; all other values must be byte-identical

Any violation causes the enrichment to be rejected and the original is preserved.

### Relational Tables (Stage 5 Output)

Seven tables are written to `sqlite_data/` as both `.csv` and `.xlsx`:

| Table | Content |
|-------|---------|
| `Primary` | Core webpage metadata |
| `HowTo` | Step-by-step procedures |
| `FAQ` | Q&A pairs |
| `LinksTo` | Internal/external link graph |
| `Influences` | Legislation/citation references |
| `Semantic` | Content chunks with token counts |
| `RawData` | HTML/MD/JSON sources with token metrics |

Token counts are calculated using `tiktoken` with the GPT-4 `cl100k_base` encoding.

### Link Resolution

`json_to_csv.py` pre-scans all JSON files to build a global URL→UDID map, then resolves:
- Relative links (`/path`, `path`)
- Absolute internal URLs
- URL fragments

Internal IPFR links resolve to a `webpage_id`; external links are preserved as-is.

### Selenium Scraper Behaviour

`scraper.py` uses `selenium-stealth` to bypass WAF protections on the GovCMS platform. It targets:
1. `<main>` element (preferred)
2. `.region-content` class (GovCMS fallback)

Outputs both cleaned Markdown (via `markdownify`) and raw HTML DOM per page.

---

## GitHub Actions Workflows

| File | Trigger | Purpose |
|------|---------|---------|
| `check_sitemap.yml` | Weekly (Sun midnight UTC) + manual | Stage 0: sitemap monitor |
| `scrape.yml` | Dispatched by Stage 0, or manual | Stage 1: scraper |
| `process_json.yml` | Dispatched by Stage 1, or manual | Stage 2: JSON-LD generation |
| `stage5_normalization.yml` | Dispatched by Stage 2, or manual | Stage 5: relational normalisation |
| `optional_enrich_json.yml` | Manual only | Stage 3: LLM enrichment |
| `optional_validate_quality.yml` | Manual only | Stage 4: QA validation |
| `optional_create_embeddings.yml` | Manual only | Vector embeddings |
| `optional_load_json_xlsx.yml` | Manual only | Legacy XLSX loader |

All workflows auto-commit changes back to the repository using `[skip ci]` commit messages to prevent infinite trigger loops.

---

## Architecture Documentation

Detailed architecture docs live in `docs/`:
- `docs/json_generation_logic.md` — Schema.org transformation logic & heuristics
- `docs/json_enrichment.md` — LLM enrichment strategy and guardrail details
- `docs/scraper-architecture.md` — Selenium stealth techniques and DOM extraction
- `docs/validation_architecture.md` — QA validation framework
- `docs/DeterministicSchemaConversion_FileReport.md` — File-by-file breakdown

---

## Design Principles (Important for Code Changes)

1. **Determinism first** — the core pipeline must be fully reproducible. Avoid any randomisation, timestamp-based branching, or non-deterministic ordering in Stages 1, 2, and 5.

2. **CSV is the source of truth** — `metatable-Content.csv` drives all pipeline behaviour. Do not hardcode values that belong in the CSV.

3. **Safety-gated AI** — LLM calls belong only in `enrich_howto_steps.py`. Do not introduce LLM calls into Stages 1, 2, or 5.

4. **Placeholder tokens** — the string `xXx_PLACEHOLDER_xXx` is a sentinel value with semantic meaning across the pipeline. Do not alter it or use it for other purposes.

5. **Committed outputs** — CSV, JSON, and XLSX outputs are intentionally committed to the repo (not gitignored). This provides a full audit trail and makes outputs directly accessible via GitHub Actions artifacts.

6. **No unit tests** — validation is integration-based. When adding new extraction logic, verify output correctness manually against known-good JSON files and run `validate_quality.py`.

---

## Git Branch

Development work goes on branch `claude/create-claude-md-ofeEN`. Push to this branch using:

```bash
git push -u origin claude/create-claude-md-ofeEN
```

# JSON-LD Generation Architecture & Logic

## 1. Overview

This project employs a hybrid content processing pipeline designed to transform human-readable content (Markdown and HTML) and structured metadata (CSV) into machine-readable **JSON-LD** (JavaScript Object Notation for Linked Data).

The primary goal is to optimize the "IP First Response" content for search engines and Large Language Models (LLMs) by mapping content to [Schema.org](https://schema.org) standards. The output organizes information into structured entities such as `WebPage`, `GovernmentService`, `HowTo`, and `FAQPage`.

## 2. Automation Workflow

The process is automated via GitHub Actions, defined in `.github/workflows/process_json.yml`.

### Trigger

The workflow runs automatically on:

* **Push to `main**` when changes are detected in:
* `IPFR-Webpages/*.md` (Content updates)
* `scripts/*.py` (Logic updates)
* `*.csv` (Metadata updates)


* **Manual Trigger:** via `workflow_dispatch`.

### Pipeline Steps

1. **Environment Setup:** Runs on `ubuntu-latest` with Python 3.x.
2. **Dependency Installation:** Installs `beautifulsoup4` (for HTML parsing).
3. **Execution:** Runs `scripts/process_md_to_json.py`.
4. **Artifact Handling:** Uploads the `json_output/` folder as a build artifact.
5. **Commit Back:** Checks for changes in `json_output/` and pushes the updated JSON files back to the repository automatically.

---

## 3. Data Sources & Inputs

The script `process_md_to_json.py` aggregates data from three distinct sources to build a single "source of truth" JSON object for each page.

| Source | File Type | Purpose |
| --- | --- | --- |
| **Metadata Registry** | `metatable-Content.csv` | **Master Data.** Provides the canonical Title, Description, UDID, Dates, Provider, and Archetype. It acts as the "Controller" for how the page is defined. |
| **Content (Primary)** | `.md` files | The raw text content. Used for parsing headers, lists, and links if HTML is unavailable. |
| **Content (Rich)** | `.html` files | If an HTML version exists (e.g., `filename-html.html`), the script prioritizes this for cleaner extraction of DOM elements before falling back to Markdown parsing. |

---

## 4. Processing Logic

### 4.1 Initialization

The script initializes by loading static "Knowledge Bases"—dictionaries that map keywords to authoritative URLs and Schema types.

* **`LEGISLATION_MAP`**: Maps terms like "trade mark" to the *Trade Marks Act 1995*.
* **`PROVIDER_MAP`**: Maps provider names (e.g., "IP Australia", "WIPO") to their specific Schema.org `Organization` or `GovernmentOrganization` objects.
* **`IP_TOPIC_MAP`**: Links general terms to Wikidata URLs (e.g., "design"  Q252799).

### 4.2 Metadata Matching

The script iterates through every `.md` file in the input directory. For each file, it attempts to find a matching row in `metatable-Content.csv`.
**Matching Heuristics (in order of priority):**

1. **Canonical URL:** Matches if the Markdown file contains a `PageURL` tag matching the CSV.
2. **UDID:** Matches if the filename contains a pattern like `B1005`.
3. **Title/Filename:** Performs a fuzzy match between the filename and the CSV `Main-title`.

### 4.3 Content Parsing (The Hybrid Approach)

The script parses the document into **Blocks**, where keys are headers (e.g., "What is it?") and values are the body text.

* **HTML Parsing (`parse_html_to_blocks`):**
* Uses `BeautifulSoup` to traverse the DOM.
* extracts text between `<h>` tags.
* **Cleaning:** It strips non-content tags (`<script>`, `<style>`) but preserves links by converting `<a href="...">` tags into Markdown-style links `[text](url)` for later extraction.


* **Markdown Parsing (`parse_markdown_blocks`):**
* Used as a fallback if HTML is missing.
* Splits content by `#` headers.



### 4.4 Schema.org Entity Construction

Based on the **Archetype** defined in the CSV, the script determines the root Schema type:

| CSV Archetype | Schema Type |
| --- | --- |
| `Self-Help` | `Article` (previously HowTo) |
| `Government Service` | `GovernmentService` |
| `Commercial` | `Service` |
| `Non-Government` | `Service` |

#### Sub-Entity Extraction

The script dynamically segments the content into different Schema objects nested within the main `WebPage`:

1. **The Service/Article:** Derived from the "What is it?" block.
2. **HowTo Steps:**
* Looks for headers containing "steps" or "proceed".
* Parses list items into `HowToStep` objects.


3. **FAQ (Dynamic Content):**
* Any header *not* reserved (like "Intro" or "Steps") is treated as a Question.
* Example: A header "What are the costs?" becomes a `Question` object, and the text below it becomes the `Answer`.



### 4.5 Link Extraction & Cleaning

A critical feature is the `extract_links_and_clean` function.

* **Input:** Text with Markdown links `[Link Name](URL)`.
* **Operation:**
1. Extracts the URL and Name into a `relatedLink` object.
2. **Strips** the link syntax from the text, leaving only plain text for the Schema `text` property.
3. Aggregates all found links into a master `relatedLink` list for the WebPage.



### 4.6 Citations

The script checks the `Relevant-ip-right` column in the CSV. Using the `LEGISLATION_MAP`, it automatically appends formal `Legislation` citations (e.g., links to the *Copyright Act 1968*) to the JSON-LD `citation` field.

---

## 5. Output Structure

The final JSON file follows this hierarchy:

```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Page Title",
  "audience": { ... },    // Defined globally (Aus Small Business)
  "citation": [ ... ],    // Auto-generated Legislation links
  "mainEntity": [
    {
      "@type": "GovernmentService", // or Service/Article
      "provider": { ... },
      "step": [ ... ]       // If applicable
    },
    {
      "@type": "FAQPage",   // Constructed from remaining headers
      "mainEntity": [
        {
          "@type": "Question",
          "name": "What are the costs?",
          "acceptedAnswer": { ... }
        }
      ]
    }
  ]
}

```

## 6. Maintenance Guide

* **Adding New Legislation:** Update `LEGISLATION_MAP` in `process_md_to_json.py`.
* **Changing Output Structure:** Modify the `json_ld` dictionary construction in the `process_file_pair` function.
* **HTML Parsing Issues:** If the HTML structure changes (e.g., new class names), update the `parse_html_to_blocks` function to target the correct container.

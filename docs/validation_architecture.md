# Stage 4: Quality Validation Architecture

## Overview

This document details the logic and architecture behind **Stage 4 - Quality Validation**. This stage serves as an automated Quality Assurance (QA) layer designed to verify the integrity, accuracy, and consistency of generated JSON-LD Schema markup against the source HTML content.

The system is composed of two primary components:

1. **The CI/CD Workflow (`validate-quality.yml`)**: Automates the execution environment.
2. **The Validation Logic (`validate_quality.py`)**: Performs specific semantic and structural checks.

---

## 1. CI/CD Pipeline Workflow

The validation process is orchestrated by GitHub Actions. It is triggered on every `push` or `pull_request` to the `main` branch, ensuring that no data corruption enters the production baseline.

### Workflow Steps

The pipeline runs on an `ubuntu-latest` runner using Python 3.9.

1. **Environment Setup**:
* Dependencies are installed, including `beautifulsoup4` (for HTML parsing).


2. **Execution**:
* The script `scripts/validate_quality.py` is executed.


3. **Reporting & Persistence**:
* The workflow is designed to be **self-documenting**. It generates a CSV report (`Validation_Report.csv`).
* **Auto-Commit Logic**: The workflow explicitly checks for changes in the generated report. If the validation run produces different results than the previous run, the workflow commits the updated CSV back to the repository. This creates a historical audit trail of data quality directly in the version control history.



---

## 2. Validation Logic (`validate_quality.py`)

The core script compares two datasets:

* **Source Truth**: The raw HTML content from `IPFR-Webpages-html`.
* **Generated Artifact**: The enriched JSON-LD files from `json_output-enriched`.

The validation engine applies **five distinct layers of integrity checks** to every file pair.

### Layer 1: Structural Integrity

Before checking *content*, the script validates the *format*.

* **JSON Syntax**: Verifies the file is valid, parseable JSON.
* **Schema Requirements**: Checks for the existence of mandatory Schema.org keys (`@context`, `@type`, `headline`, `description`).
* **HTML Source Existence**: Ensures the corresponding HTML source file actually exists for the given JSON file.

### Layer 2: Data Integrity (Identifier Consistency)

This check ensures file naming conventions match the internal data payload.

* **Logic**: It uses Regex (`^([A-Z]\d{4})`) to parse the ID (e.g., `B1000`) from the filename.
* **Verification**: It compares this filename ID against the `identifier.value` field inside the JSON data.
* **Failure Condition**: A mismatch indicates a "drift" where a JSON file may have been overwritten by data from a different source.

### Layer 3: Semantic Text Matching (Fuzzy Logic)

This layer verifies that the content in the JSON schema actually reflects the content on the webpage. It uses `difflib.SequenceMatcher` to calculate text similarity.

* **Normalization**: Both JSON and HTML text are normalized (lowercased, whitespace stripped, non-breaking spaces removed) to prevent false negatives caused by formatting.
* **Headline Check**:
* *Primary*: Exact match in HTML body.
* *Fallback*: Fuzzy match against `<h1>` or `<title>` tags.


* **Description Check**:
* Performs a similarity calculation between the JSON description and the HTML body.
* **Threshold**: A similarity score > 0.85 is a `PASS`. Scores between 0.1 and 0.85 trigger a `WARN`.



### Layer 4: Sub-Entity Validation (FAQ)

If the Schema type is an `FAQPage` (indicated by a list of `mainEntity` objects), the script performs deep validation.

* **Logic**: It iterates through every `@type: Question` in the JSON.
* **Verification**: It searches for the specific text of the Question within the HTML body.
* **Goal**: This prevents "hallucinated" FAQs where the LLM might generate questions that do not strictly exist on the page.

### Layer 5: Link Integrity

This ensures that `relatedLink` resources in the JSON are grounded in the source.

* **Extraction**: The script extracts all `href` attributes from the HTML and all `url` values from the JSON `relatedLink` array.
* **Verification**:
1. **Exact Match**: Checks if the JSON URL exists in the HTML `href` set.
2. **Relative Fallback**: If an absolute URL fails, it checks if the HTML contains a relative version of that path (common in CMS environments like Drupal/GovCMS).



---

## 3. Scoring and Status System

The script outputs a CSV report with the following columns:

| Column | Description |
| --- | --- |
| **File** | The filename being validated. |
| **Category** | The layer of checks (e.g., Structure, Schema, Semantic). |
| **Check** | The specific test being run (e.g., "ID Match", "Key: @context"). |
| **Details** | Context on the failure (e.g., "JSON: B1000 vs File: B1002"). |
| **Score** | A float value (0.0 to 1.0) indicating confidence/success rate. |
| **Status** | Human-readable status: **PASS**, **WARN**, **FAIL**, or **CRITICAL FAIL**. |

### Directory Requirements

For the script to execute successfully, the following directory structure is assumed:

* `json_output-enriched/`: Directory containing the JSON-LD files.
* `IPFR-Webpages-html/`: Directory containing the source HTML files.
* `reports/validation_reports/`: Target directory for the CSV output.

# IP First Response — Schema Conversion System: Operation Guide

**For:** IP First Response Content Management Team
**Purpose:** How to use the DeterministicSchemaConversion GitHub repository to keep JSON-LD content accurate when site content changes.

---

## Table of Contents

1. [How the System Works (Overview)](#1-how-the-system-works-overview)
2. [Getting Started with GitHub](#2-getting-started-with-github)
3. [Updating the Content Spreadsheet (metatable-Content.csv)](#3-updating-the-content-spreadsheet-metatable-contentcsv)
4. [The Four Processing Stages](#4-the-four-processing-stages)
   - [Stage 0 — Sitemap Monitor](#stage-0--sitemap-monitor-automatic)
   - [Stage 1 — Web Scraper (Build/Update Markdown Files)](#stage-1--web-scraper-buildupdate-markdown-files)
   - [Stage 2 — JSON-LD Generator](#stage-2--json-ld-generator)
   - [Stage 5 — Relational Tables](#stage-5--relational-tables)
5. [How to Run a Stage Manually](#5-how-to-run-a-stage-manually)
6. [Finding Your Output Files](#6-finding-your-output-files)
7. [What You Do NOT Need to Touch](#7-what-you-do-not-need-to-touch)
8. [Troubleshooting Common Problems](#8-troubleshooting-common-problems)
9. [Quick Reference — End-to-End Workflow](#9-quick-reference--end-to-end-workflow)

---

## 1. How the System Works (Overview)

The system automatically converts IP First Response web pages into structured **JSON-LD data files** — a format that tells search engines (and AI tools) precisely what the content means and how it is structured.

The pipeline runs in numbered stages, each triggering the next automatically:

```
[Stage 0] Sitemap Monitor
   Checks weekly for new or changed pages on the website
        ↓ (triggers automatically when changes are found)
[Stage 1] Web Scraper
   Downloads each page and saves it as a plain-text Markdown file
        ↓ (triggers automatically when content changes)
[Stage 2] JSON-LD Generator
   Reads the Markdown files + the content spreadsheet → creates the JSON-LD files
        ↓ (triggers automatically)
[Stage 5] Relational Tables
   Converts the JSON-LD into structured spreadsheet tables for analysis
```

All stages run **inside GitHub** using an automation feature called **GitHub Actions**. You do not need to install any software — everything runs in the cloud.

The master control file that drives the entire system is a spreadsheet called **`metatable-Content.csv`**. Think of it as the system's registry: every page that exists on the website must have a row in this file.

---

## 2. Getting Started with GitHub

### What is GitHub?

GitHub is a cloud platform for storing and collaborating on code and files. This project lives at:

> **https://github.com/thomas-amann-ipaustralia/deterministicschemaconversion**

You will need a free GitHub account to do anything beyond viewing files.

### Creating a GitHub Account

1. Go to [https://github.com](https://github.com) and click **Sign up**
2. Follow the prompts to create an account
3. Ask the repo owner (Thomas) to add you as a **Collaborator** — you need write access to run the pipeline

### Navigating the Repository

Once you have access, the repository home page shows all the files and folders. Key locations:

| Location | What's There |
|---|---|
| `metatable-Content.csv` | The master content spreadsheet — the main thing you will edit |
| `IPFR-Webpages/` | Markdown files — plain-text versions of each web page |
| `json_output/` | JSON-LD files — the structured data files you will paste into GovCMS |
| `scripts/` | The Python programs that run each stage (do not edit these) |
| `.github/workflows/` | The automation configuration (do not edit these) |

### Creating Your Own Branch

A **branch** is your own personal workspace inside the repository. Changes you make on your branch do not affect anyone else until you merge them.

**To create a branch:**

1. Go to the repository home page on GitHub
2. Click the branch dropdown (it shows `main` by default) near the top-left of the file list:
   ![Branch selector — click the dropdown that says "main"](docs/assets/branch-selector.png)
3. Click the dropdown and type a new branch name (e.g., `content-update-may-2025`)
4. Click **Create branch: content-update-may-2025 from 'main'**

You are now on your own branch. You can make edits safely here.

> **Note:** For simply running pipeline stages (Stages 0–5) via GitHub Actions, you do not need your own branch — the pipelines run on the `main` branch by default. Creating a personal branch is mainly useful when you want to edit files like `metatable-Content.csv` before committing them back.

---

## 3. Updating the Content Spreadsheet (metatable-Content.csv)

`metatable-Content.csv` is the single most important file in the system. It is the master registry of every page on the IP First Response website. All pipeline stages read this file to know what to scrape and how to label it.

### When Do You Need to Update It?

You need to update this file in two situations:

1. **A new page has been published** — add a new row for the page
2. **An existing page's content or metadata has changed** — update the relevant row

### How to Edit the File in GitHub

1. Navigate to the repository and find `metatable-Content.csv` in the file list
2. Click the filename to open it
3. Click the **pencil icon** (Edit this file) in the top-right of the file preview
4. GitHub will open a text editor. The file is in CSV (comma-separated values) format
5. Make your edits carefully — see the column reference below
6. When done, scroll down to the **"Commit changes"** section
7. Write a short description of what you changed (e.g., `Add new page B1050 - How to file a complaint`)
8. Select **"Commit directly to the main branch"** (or to your own branch if you created one)
9. Click **Commit changes**

> **Tip:** For easier editing, you can copy the file content into a notepad document and save it with the suffix '.csv'. You can then open it in Microsoft Excel, save your changes, open it in notepad then copy and paste it back into the file.

### Column Reference

Every row represents one web page. Here is what each column means:

| Column | Required? | What to Enter | Example |
|---|---|---|---|
| `UDID` | Yes | Unique ID for the page. Do not change existing IDs. For new pages, use the next available number in the `B1xxx` series (or ask Thomas for the correct prefix) | `B1050` |
| `Main-title` | Yes | The official page title — this overrides whatever is on the website | `How to file an IP complaint` |
| `Canonical-url` | Yes | The exact URL of the page (copy from your browser address bar) | `https://ipfirstresponse.ipaustralia.gov.au/options/how-to-file-complaint` |
| `Description` | Yes | A one-sentence summary of what the page is about (used in search results) | `A guide to lodging a formal IP complaint with IP Australia.` |
| `Archetype` | Yes | The page category — controls the type of JSON-LD generated. Must be one of the exact values below. | `Government Service` |
| `Relevant-ip-right` | Yes | Which IP right(s) this page relates to — controls which legislation is automatically cited. Must be one of the exact values below. | `Trade mark` |
| `Provider` | Yes | Who provides this service | `IP Australia` |
| `Overtitle` | Optional | A short breadcrumb/category label shown above the title | `Letter of demand` |
| `Publication-date` | Optional | When this page was first published, in D/M/YYYY format | `4/07/2025` |
| `Last-updated` | Optional | When this page was last updated, in D/M/YYYY format. Updating this date will cause the scraper to re-download the page. | `5/05/2026` |
| `Keywords` | Optional | Comma-separated keywords in quotes | `"Trade mark", "Infringement", "IP rights"` |
| `Additional-disclaimer` | Optional | Any specific legal warning text for this page | Leave blank unless needed |

### Archetype — Exact Values

The `Archetype` column must contain **exactly** one of these values (copy and paste):

- `Self-Help Strategy` → generates an `Article` type JSON-LD
- `Government Service` → generates a `GovernmentService` type JSON-LD
- `Commercial Third Party Service` → generates a `Service` type JSON-LD
- `Non-Government Third-Party Authority` → generates a `Service` type JSON-LD

### Relevant-ip-right — Exact Values

The `Relevant-ip-right` column must contain **exactly** one of these values (copy and paste):

- `Trade mark`
- `Patent`
- `Design`
- `PBR` (Plant Breeder's Rights)
- `Copyright`
- `Unregistered-tm`
- `Any IP right` (use when the page covers multiple IP types)

> **Important:** Spelling and capitalisation matter. A typo (e.g., `Trade Mark` instead of `Trade mark`) will cause the legislation citations to be skipped.

---

## 4. The Four Processing Stages

### Stage 0 — Sitemap Monitor *(Automatic)*

**What it does:** Every Sunday at midnight UTC, this stage automatically checks the IP First Response website's sitemap and compares it to `metatable-Content.csv`. If it finds new pages, it adds them to the spreadsheet automatically (with a temporary `A` prefix ID, e.g., `A1003`). If it finds pages whose `Last-updated` date has changed, it flags them for re-scraping.

**You generally don't need to do anything for Stage 0** — it runs automatically. However:

- Auto-discovered pages get a temporary `A` prefix ID and a title guessed from the URL. You should review and update these rows in `metatable-Content.csv` to add the correct metadata (title, description, archetype, etc.)
- To run it manually ahead of schedule, see [Section 5](#5-how-to-run-a-stage-manually)

---

### Stage 1 — Web Scraper *(Build/Update Markdown Files)*

**What it does:** Downloads every page listed in `metatable-Content.csv` and saves two files per page:

- A **Markdown file** (`.md`) — a clean, plain-text version of the page content, saved in the `IPFR-Webpages/` folder
- A **raw HTML backup** (`.html`) — a copy of the page's HTML source, saved in `IPFR-Webpages-html/`

The Markdown file is what Stage 2 uses to generate the JSON-LD. The HTML backup is kept for reference and debugging.

**When to run manually:**

- A page's content has been updated on the website and you want to re-generate its JSON-LD
- You have added a new row to `metatable-Content.csv` and want to scrape the new page immediately

---

### Stage 2 — JSON-LD Generator

**What it does:** Reads each Markdown file from `IPFR-Webpages/` and the metadata from `metatable-Content.csv`, then generates a fully structured JSON-LD file for each page. This is the file you will copy and paste into GovCMS.

Output files are saved to the `json_output/` folder, named `UDID_page-title.json` (e.g., `B1050_how-to-file-an-ip-complaint.json`).

**When to run manually:**

- After updating `metatable-Content.csv` (e.g., correcting a title or description)
- After Stage 1 has run and you need the JSON-LD files immediately

---

### Stage 5 — Relational Tables *(Usually Automatic)*

**What it does:** Converts the JSON-LD files into structured spreadsheet tables (CSV and Excel format) saved in the `sqlite_data/` folder. These are used for analysis and reporting — not for GovCMS.

You rarely need to interact with Stage 5 directly. It runs automatically after Stage 2.

---

## 5. How to Run a Stage Manually

All stages can be triggered manually from the GitHub Actions tab.

**Step-by-step:**

1. Go to the repository on GitHub
2. Click the **Actions** tab at the top of the page
3. In the left sidebar, you will see a list of workflows:
   - **Check Sitemap** — Stage 0
   - **Scrape IPFR Pages** — Stage 1
   - **Generate JSON-LD** — Stage 2
   - **Stage 5 Normalization** — Stage 5 (relational tables)
4. Click the workflow you want to run
5. On the workflow page, click the **Run workflow** button (grey button on the right)
6. A small dropdown will appear. Leave the branch set to `main` and click the green **Run workflow** button
7. The workflow will start. Click on the running job to watch its progress.

**How to know it worked:**

- A green tick (✓) next to the workflow run means it completed successfully
- A red cross (✗) means it failed — see [Section 8](#8-troubleshooting-common-problems) for how to investigate
- After a successful run, the output files will be automatically committed back to the repository. You should see a new commit appear in the file history.

> **Note:** Stages take a few minutes to run (Stage 1 can take 15–30 minutes as it downloads every page). You do not need to keep the page open — GitHub will run it in the background. BUT if you want to see the system logs (to help trouble shoot) you'll need to click on the grey box with the spinning yellow dot. Zscaler doesn't let us look at system logs AFTER they've been generated. #ZeroTrustIsAMust

---

## 6. Finding Your Output Files

### JSON-LD Files (What You Paste into GovCMS)

After Stage 2 runs, your JSON-LD files are in the **`json_output/`** folder.

**To find and download a specific file:**

1. Click **`json_output/`** in the repository file list
2. Find the file named after the page's UDID and title (e.g., `B1050_how-to-file-an-ip-complaint.json`)
3. Click the filename to open it
4. Click the **Raw** button (top-right of the file view) to see the raw JSON text
5. Select all the text (Ctrl+A / Cmd+A) and copy it — this is what you paste into GovCMS

Alternatively, to download the file:
1. On the file view page, click the **Download raw file** button (the download icon near the top-right)

### Markdown Files (Scraped Content)

Saved in `IPFR-Webpages/` — named `UDID_page-title.md`. These are plain-text representations of the web page. Useful for reviewing what was scraped before generating JSON-LD.

### Validation Reports

Saved in `reports/validation_reports/` — run Stage 4 (optional) to generate these. They list any quality issues found in the JSON-LD files.

### Relational Tables

Saved in `sqlite_data/` as both `.csv` and `.xlsx` files. These are the structured data tables for analysis.

---

## 7. What You Do NOT Need to Touch

The following parts of the repository are managed automatically or by a developer. **Do not edit these files** unless instructed to by Thomas:

| File/Folder | Why to Leave It Alone |
|---|---|
| `scripts/` | The Python programs that run the pipeline. Editing these could break the entire system. |
| `.github/workflows/` | GitHub Actions automation configuration. |
| `requirements.txt` | Python software dependencies. |
| `scripts/schema_mapping.yaml` | Internal configuration for Stage 5 table structure. |
| `IPFR-Webpages/` | These files are automatically generated by the scraper. Manually editing them would be overwritten on the next run. |
| `IPFR-Webpages-html/` | Raw HTML backups — automatically generated, not human-friendly to edit. |
| `sqlite_data/` | Automatically generated by Stage 5. |
| `json_output-enriched/` | Generated by the optional LLM enrichment stage — requires an API key. |

**The only file you will regularly need to edit is `metatable-Content.csv`.**

---

## 8. Troubleshooting Common Problems

### A GitHub Actions workflow run failed (red cross)

1. Click the red ✗ next to the failed run in the Actions tab
2. Click on the failed job name to expand the log
3. Scroll to the bottom of the log — the error message will appear in red
4. Common causes and fixes:

| Error in the log | Likely cause | What to do |
|---|---|---|
| `No module named 'X'` | Missing Python package | Contact Thomas — the environment needs updating |
| `[NO MATCH]` for a file | A Markdown file exists that has no corresponding row in `metatable-Content.csv` | Check the CSV for a missing or mismatched UDID |
| `Timeout waiting for page` | The website was slow or temporarily unavailable | Wait a few minutes and re-run the workflow |
| `Permission denied` | The workflow doesn't have write access | Contact Thomas to check the repository settings |
| `Invalid archetype value` | A typo in the `Archetype` column of the CSV | Open `metatable-Content.csv`, find the row, and correct the spelling exactly |

### A new page was published but no JSON-LD was generated

Work through this checklist:

1. **Is the page in `metatable-Content.csv`?** Check that a row exists for the page with the correct `Canonical-url`. If not, add it.
2. **Is the Markdown file in `IPFR-Webpages/`?** Look for a file matching the page's UDID. If it's missing, Stage 1 (scraper) has not run yet — trigger it manually (see Section 5).
3. **Did Stage 2 run after Stage 1?** Check the Actions tab — there should be a recent successful "Generate JSON-LD" run. If not, trigger it manually.
4. **Is the `Archetype` column correctly filled in?** If the value is blank or misspelled, the JSON-LD generator will skip the row.

### The JSON-LD file was generated but looks wrong or incomplete

Common reasons:

| Symptom | Likely cause |
|---|---|
| Title is wrong | `Main-title` in the CSV is incorrect — update it and re-run Stage 2 |
| Description says `xXx_PLACEHOLDER_xXx` | The system couldn't find a description — fill in the `Description` column in the CSV |
| No legislation citations appear | `Relevant-ip-right` is blank or misspelled — check the CSV value exactly |
| HowTo steps are missing | The page may not have numbered steps in the Markdown — check the `.md` file in `IPFR-Webpages/` |
| FAQs are missing | The Markdown may not have any headings ending with a `?` — this is used to detect FAQ sections |

### The sitemap monitor added a page with an "A" prefix ID (e.g., A1003) and incorrect metadata

This is expected behaviour — when the sitemap monitor auto-discovers a new page, it assigns a temporary ID and guesses the title from the URL. You need to:

1. Open `metatable-Content.csv` and find the row with the `A` prefix ID
2. Replace the auto-generated values with the correct title, description, archetype, and other metadata
3. If the UDID needs to change (e.g., to a `B` prefix), update it — but be aware that any existing Markdown/JSON files with the old ID will need to be renamed or re-generated
4. Commit the updated CSV
5. Re-run Stage 1 and Stage 2 to generate correct output

### I committed something by mistake

GitHub keeps a full history of every change. To revert a file to its previous version:

1. Navigate to the file on GitHub
2. Click **History** (or "X commits" near the top of the file view)
3. Find the commit just before your mistake
4. Click the commit to open it
5. Find the file in the diff and click **"View file"** to see the old version
6. Copy the old content, then edit the current file and paste it back in

If this feels complicated, contact Thomas — he can revert the change quickly.

### I don't know which workflow to run

Use this as a quick guide:

| Situation | Run This Workflow |
|---|---|
| A page has been updated on the website | **Stage 1 — Scrape** → then **Stage 2 — Generate JSON-LD** |
| I updated metadata in the CSV (title, description, etc.) but content hasn't changed | **Stage 2 — Generate JSON-LD** only |
| I think there might be a new page I don't know about | **Stage 0 — Check Sitemap** |
| I just want to check that everything is correct | **Optional: Validate Quality** |
| I need the relational tables updated | **Stage 5 — Normalization** |

---

## 9. Quick Reference — End-to-End Workflow

Here is the standard process for updating JSON-LD after a content change, from start to finish:

### For an existing page that has been updated

```
1. Content team publishes updated content on the GovCMS website
2. Update the Last-updated date in metatable-Content.csv for that page
3. GitHub Actions → Run "Scrape IPFR Pages" (Stage 1)
   → Wait ~15-30 mins for it to complete ✓
4. GitHub Actions → Run "Generate JSON-LD" (Stage 2)
   → Wait ~5 mins for it to complete ✓
5. Open json_output/ → find the file for your page → download/copy the JSON-LD
6. Paste the JSON-LD into GovCMS in the appropriate field
```

### For a brand new page

```
1. Content team publishes the new page on GovCMS
2. Add a new row to metatable-Content.csv with all required columns filled in
   (UDID, Main-title, Canonical-url, Description, Archetype, Relevant-ip-right, Provider)
3. GitHub Actions → Run "Scrape IPFR Pages" (Stage 1)
   → Wait ~15-30 mins ✓
4. GitHub Actions → Run "Generate JSON-LD" (Stage 2)
   → Wait ~5 mins ✓
5. Open json_output/ → find the new file → download/copy the JSON-LD
6. Insert the JSON-LD into the new page on GovCMS
```

### For a metadata-only change (e.g., fixing a title or description)

```
1. Edit metatable-Content.csv — correct the relevant column
2. GitHub Actions → Run "Generate JSON-LD" (Stage 2) only
   → Wait ~5 mins ✓
3. Open json_output/ → find the updated file → download/copy the JSON-LD
4. Update the JSON-LD in GovCMS
```

---

*For questions or issues not covered in this guide, contact Thomas Amann.*

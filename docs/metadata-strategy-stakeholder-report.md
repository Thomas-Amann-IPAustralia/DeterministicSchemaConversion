# Metadata Strategy — How It Works, and What Another Site Would Need to Change

**Audience:** Stakeholders at other government websites considering adopting this
metadata strategy. Mixed technical and non-technical.

**Purpose:** Explain, end to end, how the IP First Response (IPFR)
DeterministicSchemaConversion pipeline turns ordinary web pages into structured,
machine-readable data — and, just as importantly, flag every place where the
current system *assumes it is IP Australia / IP First Response*. Those assumptions
are what a new owner would need to rework.

> **How to read this document.** Each section opens with a plain-language summary
> in a quote box like this one. Underneath is the technical detail. Wherever the
> system bakes in something IPFR-specific, there is a **"What a new site must
> change"** callout with a portability rating:
>
> - 🟢 **Easy** — change a setting or a list. No programming judgement required.
> - 🟡 **Moderate** — needs someone technical, but it is a well-defined edit.
> - 🔴 **Significant** — encodes IPFR's subject matter or editorial style; needs
>   real rethinking and redesign for a different domain.

---

## 1. Executive Summary (non-technical)

> **In plain terms.** This system is an automated factory. Raw material goes in at
> one end (public web pages), and clean, structured, labelled data comes out the
> other end — the kind of data that search engines and AI assistants can read
> reliably. The factory runs the same way every time (it is *deterministic*: same
> input always gives the same output), which makes it trustworthy and auditable.
> There is an optional AI step, but it is fenced off and tightly supervised.

The pipeline takes unstructured government web content and converts it into
**Schema.org JSON-LD** — an open, internationally recognised standard for
describing what a page *is about* in a way machines understand (a "service", an
"article", a "step-by-step guide", a "frequently asked question", and so on). It
also produces spreadsheet-style tables optimised for feeding into AI/search
systems.

Three things make it distinctive, and all three transfer well to other sites:

1. **It is rule-based and deterministic.** The core path contains no AI guesswork.
   Every output can be traced back to a rule. For a government publisher, this is
   the headline selling point: the output is reproducible and auditable.
2. **A single spreadsheet controls everything.** A master file
   (`metatable-Content.csv`) lists every page and its key facts. Non-developers
   edit this file to steer the whole system.
3. **AI is optional and caged.** The one place an AI model is used (to fill small
   gaps) is wrapped in a safety check that rejects anything the AI changes beyond
   the specific blank it was asked to fill.

**The honest catch — and the reason for this report.** The *machinery* is
general-purpose, but the system has IP Australia's identity, Australian law, and
IP First Response's house writing style **wired directly into the code**. It works
beautifully for one website because it was built for one website. The sections
below separate the reusable machinery from the IPFR-specific wiring, so you can
scope what "making it yours" actually involves.

---

## 2. The Big Picture: A Five-Stage Assembly Line

> **In plain terms.** Work moves through numbered stations. Each station does one
> job, then automatically hands off to the next. You can also run any station by
> hand.

```
[Stage 0]  Watch the website         check_sitemap.py     → notices new/changed pages
     ↓
[Stage 1]  Collect the content       scraper.py           → saves a clean copy of each page
     ↓
[Stage 2]  Build the structured data  process_md_to_json.py → the core "brain": makes JSON-LD
     ↓
[Stage 5]  Flatten into tables       json_to_csv.py        → 7 spreadsheets for analysis/RAG

   Optional, run on demand:
[Stage 3]  AI gap-filling            enrich_howto_steps.py → fills marked blanks via GPT-4o
[Stage 4]  Quality assurance         validate_quality.py   → 5-layer cross-check
[Extra]    Embeddings                generate_embeddings.py → vectors for semantic search
```

Everything is automated through **GitHub Actions** (the hosting platform's built-in
automation). When one stage produces a change, it triggers the next. The whole
thing runs in the cloud on a schedule and commits its own results back into the
repository, creating a complete audit trail.

> **What a new site must change — the orchestration:** 🟢 **Easy.** The
> stage-to-stage automation is generic. The only site-specific parts are *names*
> (folder names like `IPFR-Webpages`, the schedule) and *secrets* (an AI API key
> if you use Stage 3). These are configuration, not logic.

The rest of this report walks each stage, then consolidates the portability
findings into a single checklist in §9.

---

## 3. The Control Plane: One Spreadsheet to Rule Them All

> **In plain terms.** There is one master list — a spreadsheet — that names every
> page the system manages and records the important facts about each one. Every
> station reads from this list. It is the steering wheel of the whole system, and
> it is designed so that content staff, not programmers, can drive.

The file is `metatable-Content.csv` (~120 rows today, one per page). Its columns:

| Column | What it holds | Reusable as-is? |
|---|---|---|
| `UDID` | A permanent ID for the page (e.g. `B1005`). Survives title changes. | 🟢 Generic concept |
| `Main-title` | The official title (overrides whatever was scraped) | 🟢 Generic |
| `Description` | The SEO/summary description | 🟢 Generic |
| `Canonical-url` | The page to collect | 🟢 Generic |
| `Overtitle` | A contextual prefix shown above the title | 🟢 Generic (naming aside) |
| `Keywords` | Search keywords | 🟢 Generic |
| `Publication-date`, `Last-updated` | Dates | 🟢 Generic |
| `Archetype` | **Decides what kind of thing the page is** (drives the output type) | 🔴 IPFR's content taxonomy |
| `Relevant-ip-right` | **Triggers automatic legal citations** (Patent, Trade Mark…) | 🔴 IP-domain-specific |
| `Provider` | Which organisation owns/runs the service described | 🟡 Concept generic, values IPFR's |
| `Entry-point` | IPFR navigation/journey labels | 🔴 IPFR-specific |

The crucial insight for a new adopter: **these columns mix three different jobs**,
and only some travel.

- **Crawl manifest** (which URLs, which IDs, what dates) — *fully generic*.
- **Editorial metadata** (title, description, keywords) — *fully generic*.
- **Domain semantics** (`Archetype`, `Relevant-ip-right`, `Provider`,
  `Entry-point`) — these columns hold values that the *code interprets using
  hardcoded IPFR knowledge*. The column can stay; what the code does with it is the
  problem (see §5).

> **What a new site must change — the control spreadsheet:** 🟡 **Moderate.** Keep
> the structure; replace the domain-semantic columns with ones that fit your
> subject matter (e.g. a health department might have `Condition` instead of
> `Relevant-ip-right`; a council might have `Service-category`). The catch is that
> renaming a column is *not enough on its own* — the code in Stage 2 has to be
> taught what the new column means. That is the 🔴 work described in §5.
>
> *Technical note:* there is even a known quirk — the archetype column is spelled
> `Archectype ` with a trailing space, and the loader has a special workaround for
> it (`process_md_to_json.py` `load_metatable`). A clean re-implementation would
> retire that.

---

## 4. Stages 0 & 1 — Watching and Collecting

> **In plain terms.** Stage 0 keeps an eye on the website and notices when pages
> are added or change. Stage 1 visits each listed page, strips away the website
> "furniture" (menus, footers, feedback widgets), and saves a clean text copy plus
> the raw source.

### Stage 0 — `check_sitemap.py` (the watcher)

Runs weekly. It reads the website's **sitemap** (a standard list of all the site's
pages), looks for new ones, and adds them to the master spreadsheet with an
auto-generated ID. It uses a "reconciler" (`url_reconciler.py`) to avoid creating
duplicate entries when a URL changes slightly, by comparing page-content
fingerprints.

### Stage 1 — `scraper.py` (the collector)

Because government sites often block automated traffic, the scraper uses
**`selenium-stealth`**: it drives a real, invisible Chrome browser and disguises
itself as an ordinary Windows user to get past web application firewalls. For each
page it:

1. Loads the page in the browser.
2. **Isolates the real content** by trying, in order: the `<main>` region → a
   `.region-content` block → the whole `<body>` as a last resort.
3. Converts the HTML to clean Markdown.
4. Removes "web-only noise" (feedback widgets, "Opens in a new tab" text, etc.).
5. Saves two files per page: a cleaned `.md` and the raw `.html`.

> **What a new site must change — collection:** 🟡 **Moderate**, with two distinct
> pieces:
>
> - **The stealth browser approach** is fully generic and reusable. 🟢
> - **The content-isolation selectors are CMS-specific.** 🟡 `.region-content` is a
>   Drupal/GovCMS wrapper. A WordPress, Squiz, or custom site uses different markup,
>   so the selector chain must be re-pointed. This is a small, well-defined edit —
>   *if* the new site runs GovCMS too, it may need almost no change.
> - **The noise patterns are IPFR-specific.** 🟡 The list of junk to strip ("Was
>   this information useful?", "Thumbs Up/Thumbs Down", the IPFR feedback form
>   link) reflects IPFR's page furniture. Another site has different furniture and
>   needs its own list.
> - **Hardcoded addresses.** 🟢 The sitemap URL, the `/options/` path that marks a
>   "real" content page, the `A`-prefix for auto-discovered IDs, and the output
>   folder names are all constants in `check_sitemap.py` / `scraper.py` and must be
>   swapped for the new site's values.

---

## 5. Stage 2 — The Core "Brain" (and where most of the IPFR DNA lives)

> **In plain terms.** This is the most important and most complex station. It reads
> each cleaned page plus its row in the master spreadsheet, and builds the
> structured Schema.org data. To do this it makes a series of *judgement calls*:
> What kind of thing is this page? Which paragraphs are the introduction, which are
> a step-by-step guide, which are FAQs? Who is the provider? What laws are
> relevant? **It answers these questions using rules and lookup tables that were
> written specifically for IP First Response.** This is where "it assumes a lot of
> information" — almost all of those assumptions live here.

`process_md_to_json.py` is ~2,000 lines. At a high level it does four things:

### 5.1 It loads fixed "knowledge bases" baked into the code

Before processing anything, the script loads several hardcoded dictionaries. Each
one is IPFR knowledge frozen into Python:

| Knowledge base | What it is | Portability |
|---|---|---|
| `IP_AUSTRALIA_ENTITY` | A ~30-line block declaring IP Australia as the organisation behind every page (publisher, copyright holder), with its Wikidata IDs, contact point, "knows about" topics. | 🔴 This is your publisher identity. **Every output page is stamped with IP Australia.** |
| `STANDARD_DISCLAIMER` | The exact IPFR legal disclaimer text, attached to every page. | 🔴 IPFR's wording. |
| `LEGISLATION_MAP` | Maps IP rights → specific Australian Acts and Regulations on legislation.gov.au (e.g. "trade mark" → *Trade Marks Act 1995*). | 🔴 Australian IP law. |
| `IP_TOPIC_MAP` / display names | Maps IP terms → Wikidata entries, and normalises their spelling/casing. | 🔴 IP subject matter. |
| Provider registry | ~20 named organisations (IP Australia, WIPO, ABF, Federal Court, mediators…) with their URLs and types. | 🔴 IPFR's ecosystem of providers. |
| `audience` block | Hardcodes the audience as "Small and medium businesses" in "Australia", with synonyms (Startups, Sole Trader…). | 🔴 IPFR's target audience. |

> **What a new site must change — the knowledge bases:** 🔴 **Significant.** This is
> the heart of the rework. None of these values are generic; they encode *who you
> are*, *what laws/authorities matter in your domain*, and *who you serve*. The good
> news is that they are **data-shaped** — lists and lookups — so the rework is
> mostly "supply your own equivalents", not "invent new logic". A health department
> would map conditions → clinical guidelines instead of IP rights → Acts; a council
> would register its own departments as providers. The *mechanism* (inject a
> citation when a keyword appears) is reusable; the *contents* are entirely yours.

### 5.2 It decides what type of thing each page is (the "Archetype")

The `Archetype` column in the spreadsheet is mapped to a Schema.org type:

| Spreadsheet archetype | Becomes Schema.org type |
|---|---|
| `Self-Help Strategy` / `Self-Help` | `Article` |
| `Government Service` | `GovernmentService` |
| `Commercial Third Party Service` | `Service` |
| `Non-Government Third-Party Authority` | `Service` |

This is the "polymorphic" behaviour you remember: one column makes the output
take different shapes. There is also a smart **fallback rule** — if a page tagged
as a service has no FAQs and no steps, it is quietly downgraded to a plain
`Article` to avoid duplicating text. That conditional logic is real programming,
not just a lookup.

> **What a new site must change — archetypes:** 🔴 **Significant but bounded.** The
> four archetypes *are* IPFR's content model. The polymorphism is genuinely useful
> and worth keeping, but it is "restricted in its flexibility" exactly as you
> recalled: it only knows these few shapes. A new site will likely want different
> types (`Course`, `Event`, `MedicalWebPage`, `Dataset`…) and different
> editorial-to-Schema mappings. The mapping table and the downgrade rules are
> currently hardcoded, so changing them means editing Python, not config.

### 5.3 It splits the page into sections — and this is the most fragile part

The brain reads the page's headings and classifies each one into: an
**introduction/body**, a **step in a how-to guide**, an **FAQ question**, a named
**content section**, or **noise to discard**. It does this with a function called
`_classify_heading`, using rules like:

- Headings in a fixed exclusion list ("See also", "Feedback") → discard.
- Headings matching a fixed list of IPFR's standard questions → FAQ.
- Headings ending in "?" → FAQ.
- Headings containing the words "step" or "proceed" → how-to step.
- A specific set of phrases ("What is it", "Overview", "Background"…) → the
  article's main body.

> **What a new site must change — section detection:** 🔴 **Significant — this is
> the single biggest porting risk.** These rules encode **IPFR's house writing
> style in English**. They assume your authors write FAQ headings as questions,
> introduce content under "What is it?", and signal procedures with the word
> "step" or "proceed". A site with different editorial conventions — or another
> language — will see this misclassify content silently. The *approach* (rule-based
> heading classification) is sound and reusable, but the specific phrase lists are
> a direct expression of one team's writing habits and must be rebuilt for a new
> author community. (A more robust redesign would lean on structural cues — numbered
> lists, "Step N" patterns, question words — that survive across domains; see the
> companion design proposal in §10.)

### 5.4 It assembles the final structured document

It stitches everything into a Schema.org `@graph` (a connected set of entities) in
a fixed order: publisher → provider → website → the page → the main entity
(Article/Service/etc.) → how-to → content sections → FAQ → citations → links to
other internal pages. Stable internal IDs (`#webpage`, `#article`, `#howto`,
`#faq-q1`…) tie it together.

Where the system *cannot* deterministically work something out, it writes a
**placeholder token** — the exact string `xXx_PLACEHOLDER_xXx` — into that field.
This is a deliberate signal meaning "a human or the AI step should fill this in".

> **What a new site must change — assembly:** 🟢 **Mostly reusable.** The assembly
> order and the placeholder mechanism are domain-agnostic and well-designed. They
> are among the most directly portable parts of the whole system.

---

## 6. Stage 5 — Flattening into Tables

> **In plain terms.** The structured data from Stage 2 is great for machines but
> awkward for analysts. Stage 5 unpacks it into seven plain spreadsheets — one for
> page metadata, one for how-to steps, one for FAQs, one for the link map, and so
> on — and counts how many "tokens" (the units AI models read) each chunk is.

`json_to_csv.py` reads a configuration file, `schema_mapping.yaml`, that says
"to fill this column, pull this path out of the JSON". It produces seven tables
(Primary, HowTo, FAQ, LinksTo, Influences, Semantic, RawData) as both CSV and
Excel. It also builds a global map of every internal URL → its UDID, so links
between pages resolve to clean internal references.

This stage is the most elegantly generic in design — most of its behaviour lives
in editable YAML rather than code — **except for two leaks**:

- `INTERNAL_DOMAIN = "ipfirstresponse.ipaustralia.gov.au"` is hardcoded, used to
  decide which links are "internal".
- The **FAQ table hardcodes IPFR's nine standard questions as column headers**
  (e.g. `What_are_the_benefits`, `Who_can_use_this`). So even the "flexible,
  config-driven" stage has IPFR's editorial questions frozen into it.

> **What a new site must change — tables:** 🟡 **Moderate.** Swap the internal
> domain (one line). The FAQ table is the real issue: its wide, one-column-per-known-question
> format only works because IPFR asks the same nine questions on every page. A new
> site either supplies its own canonical question set or, better, switches the FAQ
> table to a generic long format (one row per question). Everything else in this
> stage is genuinely reusable config.

---

## 7. Optional Stage 3 — The Caged AI Step

> **In plain terms.** This is the *only* place an AI model is used, and it is on a
> very short leash. Its single job is to fill in the blanks marked by the
> placeholder token — nothing else. A safety check compares the file before and
> after and rejects the AI's work entirely if it changed anything it wasn't
> supposed to. It is run by hand, never automatically, so costs and changes stay
> under human control.

`enrich_howto_steps.py` walks the JSON looking for `xXx_PLACEHOLDER_xXx` tokens.
For each one it builds a context-aware prompt (e.g. "given these step
instructions, write a short imperative title") and asks GPT-4o. Then the
**semantic diff guardrail** enforces three hard rules:

1. **No structural change** — the number of keys must be identical before/after.
2. **No type change** — a string cannot become a list or object.
3. **No unintended edits** — only fields that held a placeholder may change;
   everything else must be byte-for-byte identical.

Any violation → the whole file is rejected and the original kept. This is what lets
a government publisher use an AI model without surrendering determinism or
auditability over the rest of the data.

> **What a new site must change — AI enrichment:** 🟢 **Largely reusable, and a
> genuine asset.** The guardrail pattern is domain-independent and is arguably the
> most valuable single idea to carry across. The prompts contain some IPFR framing
> ("government body", IP context) that would want light tuning, and you would supply
> your own API key — but the architecture transfers directly. **Design principle to
> preserve: AI lives only here, never in Stages 0/1/2/5.**

---

## 8. Optional Stage 4 — Quality Assurance

> **In plain terms.** A final inspector that checks the structured data actually
> matches the real web page — that nothing was invented, mislabelled, or dropped.

`validate_quality.py` runs five layers of checks per page: (1) structural validity,
(2) the filename ID matches the ID inside the data, (3) the text genuinely appears
on the source page (fuzzy similarity ≥ 0.85), (4) FAQ questions are real and not
hallucinated, (5) links are grounded in the source HTML. It writes a scored CSV
report and commits it, building a quality history over time.

> **What a new site must change — QA:** 🟢 **Easy.** The five checks are generic.
> Only folder names and a couple of thresholds are settings. This stage ports
> almost as-is.

---

## 9. Portability Scorecard — The Consolidated Checklist

> **In plain terms.** This is the "what will it take" summary. The machinery is
> ~80% reusable. The remaining ~20% is concentrated, predictable, and mostly
> *data you supply* rather than *logic you invent* — with one genuinely hard area
> (how the system reads your authors' writing style).

| Area | Reusability | What a new site supplies / changes |
|---|---|---|
| Stage orchestration & automation | 🟢 Easy | Folder names, schedule, secrets |
| Master spreadsheet structure | 🟢 Easy | Same shape; your rows |
| Master spreadsheet *domain columns* | 🟡 Moderate | Your domain attributes (and teach Stage 2 to read them) |
| Stealth scraping engine | 🟢 Easy | Reusable as-is |
| Content-isolation selectors | 🟡 Moderate | Your CMS's markup (trivial if also GovCMS) |
| Noise-removal patterns | 🟡 Moderate | Your page furniture |
| Sitemap/URL/folder constants | 🟢 Easy | Your addresses |
| **Publisher identity** (`IP_AUSTRALIA_ENTITY`) | 🔴 Significant | **Your organisation** (every page is stamped with it) |
| **Disclaimer / fixed text** | 🔴 Significant | Your legal wording |
| **Legislation / citation map** | 🔴 Significant | Your authoritative sources (mechanism reusable) |
| **Topic & provider registries** | 🔴 Significant | Your subject terms & partner organisations |
| **Audience block** | 🔴 Significant | Your audience |
| **Archetype → Schema type mapping** | 🔴 Significant | Your content taxonomy & output types |
| **Heading classification rules** | 🔴 **Highest risk** | Your authors' writing conventions / language |
| @graph assembly & placeholder mechanism | 🟢 Easy | Reusable as-is |
| Stage 5 table config | 🟡 Moderate | Internal domain; FAQ question set |
| AI enrichment + guardrail | 🟢 Easy | API key; light prompt tuning |
| Quality validation | 🟢 Easy | Folder names, thresholds |

**The one-sentence message for stakeholders:** *the engine is reusable; what needs
rebuilding is the body of knowledge it was given about IP Australia, Australian IP
law, and the IP First Response writing style — and of these, the way it reads your
authors' headings is the part that needs the most care.*

---

## 10. Recommended Path Forward

The repository **already contains a detailed engineering design** for exactly this
generalisation: [`docs/generic_pipeline_design.md`](generic_pipeline_design.md). It
proposes turning all the 🔴 hardcoded knowledge into a per-site **"profile"** — a
folder of configuration files plus a small, safe extension point for the rare cases
that genuinely need code. That document is the technical blueprint; this report is
the plain-language explanation of *why* it is needed and *what* it would touch.

For stakeholders weighing adoption, the practical options are:

1. **Fork-and-edit (fastest to a demo, highest long-term cost).** Copy the repo and
   replace the IPFR-specific values directly in the code. Workable for a single new
   site, but every site becomes its own diverging codebase — the same coupling that
   created this situation in the first place.

2. **Generalise to a profile-driven engine (recommended for multi-site).** Implement
   the design in `generic_pipeline_design.md`: one shared engine, one configuration
   profile per site. Higher upfront effort, but onboarding each *additional* site
   then becomes mostly a configuration exercise rather than a software project — and
   IPFR becomes simply the first profile, with its 134 existing outputs serving as a
   correctness benchmark to prove the refactor changed nothing.

The deciding question is **how many sites**. For one, option 1 may suffice. For a
programme of government sites, option 2 is the one that scales, and the design work
is already done.

---

## Appendix A — Glossary for Non-Technical Readers

- **Schema.org / JSON-LD** — A shared, open vocabulary (Schema.org) written in a
  specific data format (JSON-LD) that lets a page declare, in machine-readable
  terms, "I am a government service", "this is a step in a procedure", "this is a
  frequently asked question". Search engines and AI assistants understand it.
- **Deterministic** — Same input always produces exactly the same output. No
  randomness, no guessing. Essential for auditability.
- **Markdown** — A lightweight plain-text format for documents. The clean,
  furniture-free version of each web page.
- **Scraping** — Programmatically visiting a web page and extracting its content.
- **Selector** — A pattern that points at a specific part of a web page's
  underlying code (e.g. "the main content region").
- **GovCMS / Drupal** — The content management system many Australian government
  sites are built on. It produces recognisable markup the scraper relies on.
- **RAG (Retrieval-Augmented Generation)** — A technique where an AI assistant
  looks up relevant source material before answering. The tables this pipeline
  produces are designed to be that source material.
- **Token** — The unit of text an AI model reads (roughly ¾ of a word). The
  pipeline counts these so downstream AI systems can budget their input.
- **Placeholder token** (`xXx_PLACEHOLDER_xXx`) — A deliberate "fill me in later"
  marker the system writes when it cannot work out a value with certainty.
- **Guardrail** — An automated safety check that rejects an AI's output if it
  changed anything beyond what it was explicitly permitted to change.
- **Control plane / manifest** — The master spreadsheet that lists every page and
  steers the whole system.
- **`@graph` / entity** — A connected set of described "things" (the organisation,
  the website, the page, its sections), each with a stable internal ID linking
  them together.
</content>
</invoke>

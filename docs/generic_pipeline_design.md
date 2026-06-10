# Design Proposal: Generic Deterministic Schema Conversion Pipeline

**Status:** Speculative design proposal — no implementation
**Scope:** Generalising the DeterministicSchemaConversion pipeline so it can be deployed
against any organisation's web content, while preserving determinism, Schema.org JSON-LD
output quality, and the placeholder/enrichment contract.

---

## 1. Problem Statement

The pipeline is functionally excellent but structurally single-tenant. A coupling audit of
the current codebase found that client-specific knowledge lives in four places:

| Layer | Coupling | Evidence |
|---|---|---|
| **Control plane** | `metatable-Content.csv` mixes three concerns: a crawl manifest (URLs), editorial metadata (titles, descriptions), and *domain semantics* (`Relevant-ip-right`, `Archectype`, `Provider`) that drive code branches | CSV header row; `MetaRecord` in `process_md_to_json.py:824-841` |
| **Stage 2 generator** | ~15 hardcoded constant blocks: publisher identity (`IP_AUSTRALIA_ENTITY`, lines 45–74), website identity (lines 38–40), the standard disclaimer (77–90), `IP_TOPIC_MAP` Wikidata IDs (93–108), `LEGISLATION_MAP` with Australian Act URLs (187–248), a provider registry of named AU organisations (267–385), the archetype→`@type` map (424–434), English heading heuristics for FAQ/HowTo/section classification (130–179), audience hardcoding ("Small and medium businesses", lines 1722–1735), link-noise patterns (Qualtrics, Drupal paths, line 1603) | `scripts/process_md_to_json.py` |
| **Scraper** | GovCMS selector fallback chain (`<main>` → `.region-content` → `<body>`), `option-detail-page-tag` overtitle class, IPFR disclaimer regexes, feedback-widget noise patterns | `scripts/scraper.py:73-109, 230-247` |
| **Downstream** | `INTERNAL_DOMAIN` hardcoded in `json_to_csv.py:38`; `SITEMAP_URL` and `/options/` prefix in `check_sitemap.py:42-44`; IPFR question strings baked into `schema_mapping.yaml` FAQ columns ("What are the benefits?" etc.); output directory names (`IPFR-Webpages*`) in four scripts | `scripts/json_to_csv.py`, `scripts/check_sitemap.py`, `scripts/schema_mapping.yaml`, `scripts/validate_quality.py:14` |

Even the *flexible* part of the system — `schema_mapping.yaml` — has IPFR editorial
concepts (the nine standard FAQ questions) frozen into its column definitions.

The goal: a single generic engine plus a per-deployment **profile** that captures all of
the above declaratively, with a narrow escape hatch for what cannot be made declarative.

---

## 2. Core Architectural Recommendation: Profile-Driven Engine with Thin Plugin Seams

We recommend a **three-layer architecture**, in deliberate proportions:

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 3: PLUGIN HOOKS (~5% of behaviour)                     │
│ Narrow, deterministic Python extension points, declared in   │
│ the profile, for logic that cannot be expressed as rules.    │
├──────────────────────────────────────────────────────────────┤
│ Layer 2: PROFILE (declarative config bundle, ~15%)           │
│ site.yaml · scrape.yaml · extraction.yaml · archetypes.yaml  │
│ · entities.yaml · citations.yaml · manifest.csv              │
│ One directory per deployment. Versioned. Schema-validated.   │
├──────────────────────────────────────────────────────────────┤
│ Layer 1: GENERIC ENGINE (~80%)                               │
│ Crawl manifest loader · scraper strategy runner · Markdown   │
│ section parser · rule-based classifier · @graph assembler ·  │
│ relational normaliser · provenance ledger · guardrails       │
└──────────────────────────────────────────────────────────────┘
```

A deployment is a directory:

```
profiles/
└── ipfr/                          # the current client becomes Profile Zero
    ├── profile.yaml               # root: name, version, engine compat, plugin refs
    ├── site.yaml                  # identity, publisher, license, disclaimer, audience
    ├── scrape.yaml                # selector strategy, noise patterns, politeness
    ├── extraction.yaml            # heading classifier rules, cleaning rules
    ├── archetypes.yaml            # @type mapping + graph assembly directives
    ├── entities.yaml              # provider/organisation registry
    ├── citations.yaml             # topic → citation objects (replaces LEGISLATION_MAP)
    ├── tables.yaml                # Stage 5 relational mapping (today's schema_mapping.yaml)
    ├── manifest.csv               # content manifest (replaces metatable-Content.csv)
    └── plugins.py                 # optional; only if declarative rules are insufficient
```

The engine takes exactly one runtime argument: `--profile profiles/ipfr`. Everything else
— directory names, domains, heuristics, schema types — resolves from the profile.

### Why this split (and not the two pure alternatives)

This is the central trade-off the proposal was asked to explore; the analysis is in
§8. Summary: a **fully config-driven** approach collapses into an ad-hoc DSL once you
try to encode conditional logic (e.g. "downgrade `Service` to `Article` when the page
has no FAQ sections" — `process_md_to_json.py:1481-1502`) in YAML. A **per-client
adapter layer** preserves full expressiveness but makes every onboarding a software
project and every profile a code-review and determinism-audit burden. The hybrid keeps
onboarding declarative for the common case and forces the exceptional case through a
small, auditable, typed interface.

---

## 3. The Configuration Schema

### 3.1 Replacing `metatable-Content.csv`: manifest + profile split

The key insight from the audit: the metatable's columns fall into three groups, and only
one of them belongs in a per-page CSV.

| Group | Current columns | Where it goes |
|---|---|---|
| Crawl manifest (per-page, operational) | `UDID`, `Canonical-url`, `Last-updated`, `Publication-date` | stays in `manifest.csv` (generic core columns) |
| Editorial metadata (per-page, content) | `Main-title`, `Overtitle`, `Description`, `Keywords`, `Additional-disclaimer` | stays in `manifest.csv` (generic core columns, renamed) |
| Domain semantics (per-page values, but *interpreted* by hardcoded Python) | `Archectype`, `Relevant-ip-right`, `Provider`, `Entry-point` | values stay per-page in `manifest.csv` as **namespaced attribute columns**; their *interpretation* moves to profile YAML |

**Recommended manifest format: keep CSV** (not YAML) for the per-page manifest. It is
edited by content/editorial staff, diffs cleanly per-row, and ~200–10,000 rows in YAML is
hostile to humans and to git. YAML is right for the profile (structural, edited by the
integrator); CSV is right for the manifest (tabular, edited by the content owner).

```csv
# manifest.csv — generic core columns + x: namespaced attributes
id,url,title,context_label,description,keywords,published,updated,page_disclaimer,x:archetype,x:topics,x:provider
B1005,https://.../receiving-a-letter-of-demand,Receiving a letter of demand,...,...,...,2025-02-28,2026-03-26,,Self-Help Strategy,"Trade mark, Patent",Self-Help
```

Rules:

- **Core columns are fixed and generic.** `id` (replaces `UDID`), `url`, `title`,
  `context_label` (replaces the IPFR-specific "Overtitle" concept), `description`,
  `keywords`, `published`, `updated`, `page_disclaimer`. The engine knows these and only
  these. This also retires the `Archectype ` typo-with-trailing-space workaround
  (`process_md_to_json.py:922-926`) permanently.
- **Everything domain-specific is an `x:` column.** The engine treats `x:*` columns as
  opaque string attributes attached to the page record. They acquire meaning *only*
  through profile rules that reference them (`attribute: archetype` in
  `archetypes.yaml`, `attribute: topics` in `citations.yaml`). A new client adds
  whatever attribute columns their domain needs — `x:department`, `x:service-category`,
  `x:audience-tier` — with zero engine changes.
- **A `manifest_schema` block in `profile.yaml`** declares each `x:` column's type
  (string / list / date / enum), allowed values, and whether it is required — so the
  engine can validate the manifest at load time instead of failing silently mid-run
  (the current behaviour when a CSV value is misspelt).

```yaml
# profile.yaml (excerpt)
manifest_schema:
  x:archetype: { type: enum, values: [Self-Help Strategy, Government Service, Commercial Third Party Service, Non-Government Third-Party Authority], required: true }
  x:topics:    { type: list, delimiter: ",", required: false }
  x:provider:  { type: string, required: false }
```

### 3.2 `site.yaml` — identity, fixed entities, fixed text

Everything that is "always injected" today becomes data. The publisher entity — currently
the 30-line `IP_AUSTRALIA_ENTITY` dict — is just a JSON-LD fragment in config:

```yaml
site:
  id: "https://ipfirstresponse.ipaustralia.gov.au/#website"
  name: "IP First Response"
  url: "https://ipfirstresponse.ipaustralia.gov.au/"
  internal_hosts:                      # replaces IPFR_HOST / INTERNAL_DOMAIN constants
    - ipfirstresponse.ipaustralia.gov.au
  language: en-AU
  license: "https://creativecommons.org/licenses/by/4.0/"

publisher:                             # verbatim JSON-LD entity, engine does not interpret it
  "@type": GovernmentOrganization
  "@id": "https://www.ipaustralia.gov.au/#organization"
  name: IP Australia
  sameAs: ["https://www.wikidata.org/wiki/Q5973154"]
  # ... full entity as data, not code

roles:                                 # which graph slots the publisher entity fills
  publisher: publisher
  copyrightHolder: publisher
  author: publisher                    # a different client may point author elsewhere

fixed_text:
  usage_info: |
    This IP First Response website has been designed to help IP rights holders...
  credit_text: "Source: IP First Response initiative led by IP Australia"

audience:                              # optional block; omit and no audience is emitted
  "@type": BusinessAudience
  audienceType: "Small and medium businesses"
  geographicArea: { "@type": Country, name: Australia }

link_policy:
  noise_patterns: ["qualtrics\\.com", "^mailto:", "/sites/default/files/", "/node/"]
  strip_query_params: ["utm_*", "_gl", "_ga"]

date_formats: ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]   # manifest date parsing
```

Design principle: **fixed JSON-LD fragments are passed through verbatim**, not modelled
field-by-field. The engine validates them (see §7) but does not understand them. This is
what makes the publisher block reusable for a university, a council, or a company without
the engine knowing what a "GovernmentOrganization" is.

### 3.3 `scrape.yaml` — CMS-agnostic extraction strategy

The scraper's GovCMS knowledge becomes an ordered **strategy chain**, each entry a
selector + method, tried in order until one yields non-empty content — exactly the
pattern the code already implements imperatively at `scraper.py:238-247`:

```yaml
fetch:
  engine: selenium-stealth        # selenium-stealth | selenium | http (requests, for un-WAF'd sites)
  wait_for: { selector: "body", timeout_s: 30 }
  scroll: half                    # none | half | full (lazy-load triggering)
  delay_range_s: [2.0, 4.0]       # politeness jitter (see §6 determinism note)
  user_agent: "Mozilla/5.0 ..."

content_strategies:               # first non-empty match wins — deterministic order
  - { selector: "main",            by: tag }
  - { selector: ".region-content", by: css }      # GovCMS fallback
  - { selector: "body",            by: tag, warn: true }

metadata:
  title:         { selector: "h1", by: tag }
  context_label: { selector: ".option-detail-page-tag", by: css, optional: true }

markdown:
  strip_tags: [script, style, iframe, noscript, button]
  heading_style: ATX
  demote_h2_to_h3: true           # current clean_markdown behaviour, now opt-in

noise_patterns:                   # applied to markdown post-conversion
  - 'Was this information useful\?'
  - 'Thumbs UpThumbs Down'
  - '\[Give feedback.*?\]\([^\)]+\)'
  - '\(Opens in a new tab/window\)'

discovery:                        # Stage 0 generalisation
  sitemap_url: "https://ipfirstresponse.ipaustralia.gov.au/sitemap.xml"
  include_path_prefixes: ["/options/"]
  auto_id_prefix: "A"
```

To lower onboarding cost, ship **CMS presets** the profile can extend:

```yaml
extends: presets/govcms.yaml      # also: presets/wordpress.yaml, presets/squiz.yaml, presets/generic.yaml
content_strategies:               # override or append
  - { selector: "#content-area", by: css }
```

Presets are just profile fragments maintained in the engine repo — data, not code. A new
GovCMS client's `scrape.yaml` can be three lines.

### 3.4 `extraction.yaml` — parameterising the HowTo / FAQ / section heuristics

This is the hardest part to genericise well, because the current heuristics
(`_classify_heading`, `process_md_to_json.py:663-701`) encode IPFR's editorial style:
nine known FAQ headings, "step"/"proceed" keywords, eleven section-hint phrases, English
throughout. The recommendation is a **declarative, ordered classifier rule list** — a
deliberately *small* rule language, not a general DSL:

```yaml
heading_rules:                     # evaluated top-to-bottom per H3 section; first match wins
  - match: { equals_any: ["see also", "feedback", "want to give us feedback?"] }
    classify: exclude

  - match: { equals_any: ["common features", "things to watch out for", "disclaimer",
                          "overview", "background", "before you start", "key features"] }
    classify: section              # → WebPageElement

  - match: { equals_any: ["what is it", "what is this", "overview", "background", "introduction"] }
    classify: body                 # → articleBody source (first match wins across doc)

  - match: { regex_any: ["what are the benefits", "what are the risks",
                         "who can use this", "who.?s involved", "how much time"] }
    classify: faq

  - match: { ends_with: "?" }
    classify: faq

  - match: { regex_any: ["\\bstep\\b", "\\bproceed\\b"] }
    classify: howto_step

  - match: { numbered_prefix: true }        # built-in matcher: "1. ", "Step 2:", "2)"
    classify: howto_step

  - default: section

howto:
  min_steps: 2                     # don't emit a HowTo entity for a single stray "step" heading
  name_from: page_title            # page_title | first_step_heading | manifest:x:howto-name
  estimated_cost_attribute: x:cost # optional manifest column → HowTo.estimatedCost

faq:
  question_normalisation: ensure_question_mark

cleaning_rules:                    # markdown-level deletions before sectioning
  - { regex: '\*?This IP First Response website has been designed.*?(?=\n\n|$)', scope: body }
  - { regex: 'Before you take any action.*?(?=\n\n|$)', scope: body }

text_normalisation:
  repair_mojibake: true            # the CP-1252 round-trip repair is generic — engine built-in
  sentence_case_preserve: [IP, WIPO, ABF, ASBFEO, TTIPA, PBR, QP, ACCC]
```

**Matcher vocabulary is closed and versioned**: `equals_any`, `regex_any`, `ends_with`,
`starts_with`, `numbered_prefix`, `min_words`/`max_words`, `language`. If a client needs
a matcher that doesn't exist, that is a signal to either (a) add it to the engine as a
new generic matcher — benefiting all profiles — or (b) use a classifier plugin (§5).
Resist the temptation to add `python_expression:` to the matcher vocabulary; that is the
DSL trap (§8.1).

Two structural heuristics should be **promoted from config to engine built-ins**, because
they are universal rather than IPFR-specific and the current keyword approach is the weak
point of the design:

1. **Ordinal step detection** — numbered headings, `Step N` patterns in any casing,
   ordered-list blocks under a "how to" heading. This is layout-structural and works
   across domains where the keyword "proceed" never appears.
2. **Interrogative detection** — `ends_with: "?"` plus WH-word prefix detection
   (configurable per language: `wh_words: [what, how, who, when, why, can, do, is]`).

The profile rules then become *overrides and additions* on top of robust structural
defaults, rather than carrying the full detection burden.

### 3.5 `archetypes.yaml` — extensible schema type mapping

The archetype concept is genuinely useful — it is the editorial-to-Schema.org bridge —
but the mapping and the per-type assembly behaviour are hardcoded
(`resolve_archetype`, `process_md_to_json.py:424-462`; body-vs-sections branching at
1478–1502). Both become data:

```yaml
default: article

archetypes:
  article:
    manifest_values: ["Self-Help Strategy", "Self-Help"]   # values in x:archetype that map here
    schema_type: Article
    body: articleBody              # main text goes into Article.articleBody
    sections_attach_to: article    # WebPageElement.isPartOf → #article
    provider_role: none

  government-service:
    manifest_values: ["Government Service"]
    schema_type: GovernmentService
    body: webpage_text             # no articleBody; text lives on WebPage.text
    sections_attach_to: webpage
    provider_role: serviceOperator
    provider_org_type: GovernmentOrganization   # forces org type regardless of registry

  third-party-service:
    manifest_values: ["Commercial Third Party Service", "Non-Government Third-Party Authority"]
    schema_type: Service
    body: webpage_text
    sections_attach_to: webpage
    provider_role: provider

fallback_rules:                    # the currently-hardcoded "downgrade" heuristics, as data
  - when: { schema_type_in: [Service, GovernmentService], faq_count: 0, howto_steps: 0 }
    then: { use_archetype: article }
```

The `schema_type` value is validated against a Schema.org type whitelist shipped with the
engine (a vendored snapshot of the Schema.org type hierarchy — deterministic, no network
call at runtime). A new client adds `Course`, `Event`, `Dataset`, `MedicalWebPage`, etc.
by adding an archetype block — no Python. The assembly directives (`body`,
`sections_attach_to`, `provider_role`) form a closed vocabulary of *graph-shaping
verbs*; new verbs are engine features, not profile hacks.

### 3.6 `entities.yaml` and `citations.yaml` — registries

The provider registry (`process_md_to_json.py:267-385`) and legislation map (187–248)
are already structured like config tables trapped in Python. They translate 1:1:

```yaml
# entities.yaml — resolves manifest x:provider values to JSON-LD org entities
match_strategy: [exact, first_of_comma_list, fuzzy]   # current _resolve_provider order
none_values: ["self-help", "self help", ""]           # values meaning "no provider entity"
entities:
  - keys: ["ip australia"]
    entity: { "@type": GovernmentOrganization, name: IP Australia,
              url: "https://www.ipaustralia.gov.au", sameAs: ["https://www.wikidata.org/wiki/Q5973154"] }
  - keys: ["mediator", "arbitrator", "qualified facilitator"]
    entity: { "@type": Organization, name: "{key|title}" }   # only templating allowed: the matched key
unknown_provider: { "@type": Organization }                  # current fallback behaviour
```

```yaml
# citations.yaml — generic "page attribute value → citation entities" injection
trigger_attribute: x:topics
topics:
  - keys: ["trade mark", "trademark"]
    display_name: "Trade mark"
    same_as: "https://www.wikidata.org/wiki/Q165196"
    citations:
      - { "@type": Legislation, name: "Trade Marks Act 1995",
          url: "https://www.legislation.gov.au/C2004A04969/latest/text",
          legislationType: Act }
      - { "@type": Legislation, name: "Trade Marks Regulations 1995",
          url: "https://www.legislation.gov.au/F1996B00084/latest/text" }
  # ... patent, design, copyright, pbr — exactly today's LEGISLATION_MAP as data
```

Note the generalisation: "legislation citation injection keyed on IP right" becomes
"**citation entity injection keyed on any manifest attribute**". A health department
profile keys `x:condition` to clinical guidelines; a university keys `x:policy-area` to
policy documents. The citation entities themselves are verbatim JSON-LD fragments —
`Legislation` is just one possible `@type`.

### 3.7 `tables.yaml` — fixing the Stage 5 leak

`schema_mapping.yaml` is the right idea but its FAQ table hardcodes IPFR question strings
as column definitions. Two changes:

1. **Pivot the FAQ table to long format by default** (`UDID, Question, Answer, Position`)
   — domain-agnostic, no per-question columns.
2. Where a client wants the wide format, generate columns from a profile-listed set of
   canonical questions, with fuzzy/normalised matching declared in config — making the
   IPFR wide table a profile choice, not an engine assumption.

The named `logic:` escape hatches (`derive_service_provider`, `check_is_internal_link`,
`lookup_internal_udid`, token counters) already follow the plugin pattern this proposal
recommends: a **named registry of deterministic functions** referenced from config. Keep
that pattern; generalise `check_is_internal_link` to read `site.internal_hosts`.

---

## 4. Generic Engine: @graph Assembly Contract

The engine's assembly order is already client-agnostic in shape
(`process_md_to_json.py:1861-1906`); it becomes the fixed, documented contract:

```
@graph := [ publisher_entity?            (site.yaml)
          , provider_entity?             (entities.yaml, if distinct from publisher)
          , WebSite                      (site.yaml identity)
          , WebPage                      (manifest + extracted metadata)
          , main_entity                  (archetypes.yaml: Article | Service | ...)
          , HowTo?                       (extraction.yaml classifier output)
          , WebPageElement[]             (sections)
          , FAQPage?                     (classifier output)
          , citation_entities[]          (citations.yaml)
          , internal_page_stubs[]        (link graph, site.internal_hosts) ]
```

Stable `@id` fragment conventions (`#webpage`, `#article`, `#howto`, `#faq-q{n}`,
`#section-{n}-{slug}`) are engine-defined and frozen — they are load-bearing for Stage 5
JSONPath queries and for the placeholder/enrichment contract, and there is no reason a
client should customise them.

**The placeholder contract is preserved unchanged.** `xXx_PLACEHOLDER_xXx` remains an
engine-level sentinel. The profile may declare *which fields are allowed to be
placeholdered* (today: `description`; a new client might add `HowTo.estimatedCost.price`),
giving the enrichment stage an explicit allowlist instead of an implicit convention:

```yaml
# profile.yaml
placeholders:
  allowed_paths: ["description", "abstract", "mainEntity[?@type=='HowTo'].estimatedCost.price"]
```

---

## 5. The Plugin Seam (Layer 3)

Where declarative rules genuinely run out, the profile may register plugins — but only at
**four named seams**, each with a typed, side-effect-free interface:

| Seam | Interface | Example use |
|---|---|---|
| `heading_classifier` | `(heading: str, section_text: str, page: PageRecord) -> Classification \| None` (None = fall through to YAML rules) | A client whose FAQ headings are statements, not questions |
| `entity_resolver` | `(attribute_value: str, page: PageRecord) -> dict \| None` (JSON-LD fragment) | Provider lookup against a client's internal org API *export* (a committed file, not a live call) |
| `citation_resolver` | `(attribute_value: str, page: PageRecord) -> list[dict]` | Citation rules too conditional for the keyed table |
| `post_assembler` | `(graph: list[dict], page: PageRecord) -> list[dict]` | Client-specific graph decoration (e.g. adding `OfferCatalog`) |

Guard-rails on plugins, enforced by the engine:

- **Declared in `profile.yaml`** (`plugins: {heading_classifier: plugins.py:classify}`),
  so a profile review sees immediately whether code is in play.
- **Determinism contract enforced mechanically**: the engine runs each plugin-bearing
  stage twice per CI run and byte-compares output (cheap, catches `dict` ordering,
  `datetime.now()`, `random`, network reads). Plugins receive no filesystem or network
  handles — only the typed inputs.
- **No LLM calls** — design principle 3 (safety-gated AI only in enrichment) extends to
  plugins and is checked by import-linting the plugin module against a denylist
  (`openai`, `anthropic`, `requests`, `httpx`, `urllib`).

This keeps the plugin layer honest: it is a place for *deterministic domain logic*, not a
side door around the architecture.

---

## 6. Determinism and the Auditable-Inference Fallback

### 6.1 What stays deterministic

The entire core path remains rule-based: scraping, sectioning, classification, assembly,
normalisation. Two existing wrinkles to fix while generalising:

- `delay_range_s` jitter and `datetime.now()` report timestamps are fine (they don't
  enter content outputs) but should be explicitly documented as *telemetry-only*; the
  engine should assert that no output JSON field derives from wall-clock time.
- Rule evaluation order, file iteration order, and dict key order must be explicitly
  sorted/stable (mostly true today; make it a tested invariant).

### 6.2 Where determinism genuinely cannot reach — and the audit contract

Generalising the pipeline *widens* the set of pages the heuristics will fail on (new
domains, new editorial styles). The current answer — emit `xXx_PLACEHOLDER_xXx` and let
optional GPT-4o enrichment fill it under the semantic-diff guardrail — is the right
shape. The proposal strengthens it into a full **provenance ledger** so that any LLM
contribution is auditable end-to-end:

**Every output file gets a sidecar provenance manifest** (`B1005_….provenance.json`,
committed alongside, like all other outputs):

```json
{
  "engine_version": "2.3.0",
  "profile": { "name": "ipfr", "version": "1.4.0", "content_hash": "sha256:…" },
  "inputs": { "markdown_sha256": "…", "manifest_row_sha256": "…" },
  "fields": {
    "@graph[3].description": {
      "source": "llm_enrichment",
      "rule": null,
      "enrichment": {
        "model": "gpt-4o-2024-08-06", "temperature": 0, "seed": 42,
        "prompt_sha256": "…", "response_sha256": "…",
        "guardrail": { "topology": "pass", "types": "pass", "mutation_scope": "pass" },
        "raw_exchange_ref": "reports/enrichment_logs/B1005_2026-06-10.json"
      }
    },
    "@graph[5].step[2].text": { "source": "rule", "rule": "heading_rules[6]:numbered_prefix" }
  }
}
```

Properties this buys:

1. **Field-level attribution**: every value is traceable to a named profile rule (with
   its index and matcher), an engine built-in, a manifest cell, or an LLM exchange.
   "Which rule produced this?" becomes answerable without reading Python.
2. **LLM exchanges are reproducibility-pinned**: model ID, temperature 0, seed where the
   API supports it, full prompt/response hashes, and the raw exchange archived under
   `reports/`. The existing semantic-diff guardrail verdicts are recorded per field, not
   just pass/fail per file.
3. **Replay verification**: a `verify-provenance` command re-runs the deterministic path
   from hashed inputs and confirms every `source: rule` field reproduces byte-identically;
   `source: llm_enrichment` fields are instead checked against the recorded response hash.
   This converts "trust the pipeline" into "check the pipeline" — and it is exactly the
   audit story a government or regulated client needs.
4. **Coverage metrics as a first-class report**: per-run, per-profile counts of
   fields-by-source. A new deployment starts at maybe 90% rule-sourced; the integrator
   tunes `extraction.yaml` until the placeholder rate is acceptable, with the ledger
   showing precisely which headings fell through to `default: section`.

The provenance ledger is cheap to implement (the generator already knows the provenance
of every field at write time; it currently just discards that knowledge) and it is the
single highest-leverage addition for the "auditable inference" requirement.

---

## 7. Validation Layers for the Config Itself

Config-driven systems fail at config time; the engine must make those failures loud:

1. **Profile schema validation** — every YAML file validated against a JSON Schema
   (or pydantic models) at load: unknown keys rejected (catches typos — the `Archectype `
   lesson), regexes compiled eagerly, enum vocabularies enforced.
2. **Manifest validation** — `manifest_schema` (§3.1) applied row-by-row with row-numbered
   errors, before any scraping starts.
3. **Schema.org conformance** — generated `@type`s and properties checked against the
   vendored Schema.org snapshot; verbatim entity fragments from `site.yaml`/
   `entities.yaml`/`citations.yaml` are linted the same way (warn, don't fail, since
   Schema.org tolerates extension).
4. **Profile dry-run** — `engine lint --profile profiles/acme` runs the classifier over
   already-scraped Markdown and reports the classification of every heading with the rule
   that matched, *without* writing JSON. This is the onboarding feedback loop.
5. **Golden-file regression for Profile Zero** — see §9.

---

## 8. Trade-off Analysis: Full Config vs Plugin/Adapter Layer

### 8.1 Fully config-driven (everything in YAML)

*Pros:* zero code per client; onboarding by non-developers; profiles are diffable,
reviewable data; determinism trivially auditable; profiles can be generated by tooling.

*Cons — and they are decisive at the margins:*

- **The inner-platform effect.** The current code contains real conditional logic:
  archetype downgrade rules, provider-type overrides per archetype, "prefer URL in
  parentheses" link parsing, the 70%-content-preservation mojibake threshold. Encoding
  arbitrary conditionals in YAML produces a worse programming language — untyped,
  untestable, undebuggable — interpreted by Python you now also maintain.
- **Regex-in-YAML is a debugging tarpit** beyond a modest rule count. Mitigated by the
  dry-run linter, but not eliminated.
- **The matcher vocabulary ratchets.** Each client need adds a keyword; in two years the
  "closed vocabulary" has 40 verbs and is a DSL anyway, but undesigned.

### 8.2 Thin plugin/adapter layer per content domain (everything in Python subclasses)

*Pros:* full expressiveness; real types, real tests, real debugger; no DSL to maintain;
honest about the fact that extraction heuristics are *logic*.

*Cons:*

- Every onboarding is a development task; the integrator pool shrinks to Python
  developers; the editorial owner of the manifest can no longer adjust heading rules.
- Determinism and the no-LLM rule become *review* properties instead of *structural*
  properties — every adapter must be audited.
- Adapters drift: client forks of heuristic code diverge from engine improvements
  (exactly how the current single-tenant coupling arose, one hardcode at a time).
- Profiles stop being shareable artifacts; a "GovCMS preset" can't exist as data.

### 8.3 Recommendation: config-first with structurally-bounded plugins (§2)

The decision rule for what goes where:

| Behaviour class | Layer | Rationale |
|---|---|---|
| Identity, fixed entities, fixed text, registries (providers, citations, topics) | Config (verbatim JSON-LD fragments) | Pure data today, trapped in Python |
| Selector strategies, noise regexes, date formats, link policy | Config (closed vocabulary) | Pure data, naturally tabular |
| Heading classification | Config rules over engine **structural built-ins** (ordinal/interrogative detection) | Rules are per-client; the hard NLP-ish detection is generic and belongs in tested engine code |
| Archetype → @type + graph shape | Config with closed "graph-verb" vocabulary | Bounded, enumerable variation |
| Conditional fallbacks (downgrade rules) | Config, but only the specific `when/then` forms the engine defines | The honest middle: enumerated condition keys, not expressions |
| Anything conditional beyond that; bespoke resolvers | Plugin at one of four seams | Code that pretends to be config is worse than code |
| Mojibake repair, slug/ID generation, date ISO-fication, placeholder mechanics, @graph assembly order | Engine, not configurable | Universal; configurability would only create profile divergence |

The strategic bet: **~95% of a typical onboarding is profile-only**, and the remaining 5%
is visible, typed, and mechanically determinism-checked. If experience shows plugins are
needed on most deployments, that is feedback that a matcher or graph-verb is missing from
the engine vocabulary — promote it, and the plugin disappears.

---

## 9. Migration Path (IPFR as Profile Zero)

The migration has a built-in correctness oracle: the 134 committed JSON files.

1. **Extract, don't rewrite.** Mechanically transcribe each hardcoded block of
   `process_md_to_json.py` into `profiles/ipfr/*.yaml` (the §3 examples are largely that
   transcription). The engine refactor replaces each constant read with a profile read —
   behaviour-preserving by construction.
2. **Golden-file gate.** CI job: run the engine with `--profile profiles/ipfr` over the
   committed Markdown and byte-diff `json_output/` against HEAD. The refactor lands only
   when the diff is empty (modulo a one-time, reviewed normalisation commit if e.g. key
   ordering is intentionally stabilised). This substitutes for the absent unit-test suite
   and respects design principle 6 (integration-based validation).
3. **Stage order.** (a) `site.yaml` + registries (lowest risk, pure data moves); (b)
   `archetypes.yaml` + assembly directives; (c) `extraction.yaml` classifier rules; (d)
   scraper strategy chain; (e) manifest column rename behind a compatibility shim
   (`UDID`→`id` etc. — the shim reads old headers and warns); (f) provenance ledger; (g)
   second profile (any other GovCMS site is the cheapest proof, since it exercises new
   identity + manifest with the same preset).
4. **Workflow changes are mechanical**: each GitHub Actions workflow gains a
   `PROFILE=profiles/ipfr` env; directory names (`IPFR-Webpages` →
   `profiles/ipfr/output/markdown` or a profile-declared path) move into `profile.yaml`.
5. **Defer multi-tenancy-in-one-repo.** The natural end state is engine as an installable
   package and one repo per deployment containing only `profiles/<name>/` + outputs +
   thin workflows. Don't build that until profile two exists; the profile directory
   structure already makes the split a `git mv`.

### Risks

- **Golden-diff churn**: incidental ordering differences will produce noisy diffs; fix by
  stabilising serialisation *first*, as its own commit.
- **Heuristic regression on profile two**: the structural built-ins (§3.4) are new code
  paths; gate them behind profile flags so Profile Zero keeps byte-identical behaviour.
- **Config sprawl**: seven YAML files is the *maximum* decomposition; small deployments
  should be allowed to inline everything into a single `profile.yaml` (the engine treats
  the split files as includes).
- **Scope creep into a framework**: the closed vocabularies (§3.4 matchers, §3.5 graph
  verbs, §5 seams) are the defence; changes to them are engine releases with changelogs,
  not per-client patches.

---

## 10. Summary of Concrete Recommendations

1. **Profile bundle** (`profiles/<client>/`) of seven schema-validated YAML files + a
   generic-core-columns CSV manifest with `x:`-namespaced domain attributes (§3.1–3.7).
2. **Verbatim JSON-LD fragments as the config idiom** for publisher, providers,
   citations, audience — the engine carries them, never interprets them (§3.2, §3.6).
3. **Selector strategy chains + CMS presets** for scraping; presets are data shipped with
   the engine (§3.3).
4. **Ordered declarative heading-classifier rules** with a closed matcher vocabulary,
   layered over new engine-built-in structural detectors (ordinal steps, interrogatives)
   (§3.4).
5. **Archetype mapping as data** with a closed graph-shaping verb vocabulary and
   enumerated `when/then` fallback rules; `@type` validated against a vendored Schema.org
   snapshot (§3.5).
6. **Four plugin seams** (heading_classifier, entity_resolver, citation_resolver,
   post_assembler) — typed, declared in the profile, double-run determinism-checked,
   import-linted against network/LLM libraries (§5).
7. **Per-file provenance ledger** attributing every output field to a rule, manifest
   cell, engine built-in, or hashed-and-archived LLM exchange, plus a
   `verify-provenance` replay command — the auditable-inference contract (§6.2).
8. **Placeholder contract unchanged**, with a new profile-declared allowlist of
   placeholder-eligible fields (§4).
9. **Profile linter + dry-run classifier** as the onboarding feedback loop (§7).
10. **IPFR as Profile Zero with a byte-diff golden-file gate** over the 134 committed
    JSON outputs as the migration oracle (§9).

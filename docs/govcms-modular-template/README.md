# GovCMS Modular Schema Template

This folder specifies a **GovCMS (Drupal) authoring template** that lets content
owners populate free-text fields and select from dropdowns, and that a web
developer can convert (in PHP) into a Schema.org JSON-LD `@graph` — the same
output shape produced today by `scripts/process_md_to_json.py`, but driven by
**explicit structured fields instead of heading heuristics**.

## What's here

| File | What it is | Audience |
|------|------------|----------|
| [`decision-tree.md`](./decision-tree.md) | The authoritative spec: every field, every dropdown value, and the exact JSON-LD each choice produces. Includes Mermaid decision trees + outcome tables. | Web developer + content lead |
| [`govcms-modular-template.html`](./govcms-modular-template.html) | A **self-contained, clickable mock-up** of the CMS form with a **live JSON-LD preview**. Open it in any browser, edit fields, and watch the `@graph` build in real time. No server, no build step. | Web developer + content lead |

> The HTML mock-up's JavaScript intentionally mirrors `build_jsonld()` in
> `scripts/process_md_to_json.py`, so the preview is a faithful demonstration of
> the intended converter output. **The production converter is expected to be
> PHP** living in the GovCMS theme/module layer — the JS is a reference, not the
> deliverable.

## How to use it

1. Open `govcms-modular-template.html` in a browser (it ships pre-filled with the
   real `A1007` example).
2. Change the **Archetype** dropdown and watch the root `@type` flip between
   `Article`, `GovernmentService`, and `Service`, and watch CreativeWork-only
   properties move between the main entity and the `WebPage`.
3. Add **Modular content blocks** and pick each block's type (`Content section` /
   `FAQ item` / `HowTo step`) — see them become `WebPageElement` / `Question` /
   `HowToStep` nodes.
4. Toggle **IP rights** and watch `about[]` topics and the `Legislation[]`
   citations auto-seed.
5. Read `decision-tree.md` alongside it for the full rule set.

## Key design decisions (already agreed)

* **Explicit modular blocks**, not heading heuristics. Each content block
  declares its type from a dropdown. This retires the fragile
  `_classify_heading()` guessing (e.g. "ends with `?` ⇒ FAQ").
* **Converter injects boilerplate**, but normally-constant items
  (standard disclaimer, citations, provider URL/sameAs) are **exposed as
  editable fields** so authors can override per page.
* **Entry-point / journey stage** is added as a new structured multi-select
  (mapped to `keywords` / `DefinedTerm`). The other CSV decision-support fields
  (cost, effort, resolution-rate) are **not** included.
* **Provider** is a **curated dropdown + "Other"**; the converter auto-fills
  `url`/`sameAs`/`@type` from the registry, with override fields.

## Additions after first review

Driven by side-by-side testing against the automated extractor:

* **Internal related links** now expose optional **`description`** and
  **`identifier` (UDID)** fields. When the link is internal they enrich the
  `WebPage` stub (matching the automated extractor, which pulls these from the
  CSV control plane). See `decision-tree.md` §8.
* **`Image`** is now a modular block type, producing a schema-valid
  **`ImageObject`** node (`contentUrl`, `url`, `name`, `caption`, `description`,
  auto-derived `encodingFormat`) referenced via `image` on the page's content
  entity. The automated extractor captures no image metadata, so this is net-new
  capability. See `decision-tree.md` §5.1.

## Suggested GovCMS / Drupal implementation

| Template element | Recommended Drupal mechanism |
|------------------|------------------------------|
| Page metadata, title, description, URL, dates | node base fields + `field_*` (`string`, `string_long`, `link`, `datetime`) |
| Archetype, Provider | `list_string` (select) |
| Entry-point, Relevant IP right(s) | `list_string` **multi-value** (checkboxes) or taxonomy term reference |
| Keywords | `string` multi-value or free-tagging taxonomy |
| Lead text, disclaimers, block bodies | `text_long` (rich text / CKEditor) |
| Modular content blocks | **Paragraphs** module: one Paragraph type with a `block_type` `list_string` + `heading` + `body`, plus a conditional `image_url` (`link`) shown when `block_type = Image` |
| Citations | Paragraphs type (`name`, `url`, `legislationType`), auto-seeded via a form-alter or default value callback keyed on the IP-right selection |
| Related links | Paragraphs type (`url`, `link_text`, `description`, `identifier`); description/identifier apply to internal IPFR links only |
| JSON-LD emission | a render/preprocess hook (or a computed field / normalizer) that walks the node + paragraphs and emits the `@graph` per `decision-tree.md` |

The lookup tables the converter needs (provider registry, IP-topic → Wikidata
map, legislation map, archetype → `@type` map) are all enumerated in
`decision-tree.md` §3–§4 and embedded as JS objects at the top of the HTML file —
they can be lifted directly into PHP arrays.

## Open questions for sign-off

These are flagged inline in `decision-tree.md`; they don't block the mock-up but
the developer will need an answer:

1. **Auto-collapse rule (§2.1).** Today a Service/GovernmentService with no FAQ
   and only intro sections is silently downgraded to `Article`. With explicit
   block types this is probably unwanted — **recommend dropping it** and keeping
   the author's archetype authoritative. Confirm?
2. **Compound providers (§3).** e.g. *"ACCC, ASCS, AFP, IP Australia"*. Recommend
   the author picks one primary provider from the dropdown and lists the rest as
   related links, rather than the current "first recognised gov body" logic.
   Confirm?
3. **Entry-point representation (§7).** `DefinedTerm` in `keywords` (recommended,
   machine-distinguishable) vs plain-text keywords. Confirm?
4. **`@id` strategy for "Other" providers.** When a provider URL is supplied we
   mint `<url>#organization`; otherwise `<page>#provider-organization`. Confirm
   this is acceptable, or whether unknown providers should be inlined without a
   stable `@id`.

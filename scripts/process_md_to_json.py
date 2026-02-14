#!/usr/bin/env python3
"""
md_to_jsonld.py — Deterministic Markdown-to-Schema.org JSON-LD converter.

Transforms cleaned government markdown files into structured, validated
JSON-LD optimised for LLM and RAG consumption. Metadata is enriched via
a companion CSV control plane (metatable-Content.csv).

Usage:
    python md_to_jsonld.py --md-dir ./IPFR-Webpages --csv metatable-Content.csv --out ./json_output

Author:  IP First Response pipeline
Licence: CC-BY-4.0
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# ──────────────────────────────────────────────────────────────────────
# 1.  CONSTANTS & CONFIGURATION
# ──────────────────────────────────────────────────────────────────────

SCHEMA_CONTEXT = "https://schema.org"

WEBSITE_ID = "https://ipfirstresponse.ipaustralia.gov.au/#website"
WEBSITE_NAME = "IP First Response"
WEBSITE_URL = "https://ipfirstresponse.ipaustralia.gov.au/"

DEFAULT_LANGUAGE = "en-AU"
DEFAULT_LICENCE = "https://creativecommons.org/licenses/by/4.0/"

# Headings whose content should be silently discarded (noise sections).
EXCLUDED_HEADINGS = {
    "see also",
    "want to give us feedback?",
    "want to give us feedback",
    "feedback",
}

# Headings that are treated as structured detail sections (WebPageElement)
# rather than FAQ questions, even if they happen to end with "?".
# These are identified by substring matching (lowercase).
SECTION_HEADING_HINTS = [
    "common features",
    "things to watch out for",
    "things to look out for",
    "how does this work",
    "how does it work",
    "how it works",
    "what is it",
    "what is this",
    "disclaimer",
    "important notice",
    "overview",
    "background",
    "before you start",
    "what you need to know",
    "key features",
]

# Headings whose body text should be used as the articleBody.
# The first match found (in document order) wins.
ARTICLE_BODY_HEADINGS = [
    "what is it",
    "what is this",
    "overview",
    "background",
    "introduction",
]

# Headings whose content is always treated as an FAQ question/answer.
FAQ_HEADING_PATTERNS = [
    r"what are the benefits",
    r"what are the risks",
    r"what are the possible outcomes",
    r"what might the costs be",
    r"how much time",
    r"how much is this used",
    r"who can use this",
    r"who.?s involved",
    r"what do you need to proceed",
]

# ──────────────────────────────────────────────────────────────────────
# 2.  LEGISLATION MAP
# ──────────────────────────────────────────────────────────────────────
# Maps the normalised keyword found in the CSV "Relevant-ip-right" field
# to a list of (url, name, legislationType) tuples.

LEGISLATION_MAP: dict[str, list[tuple[str, str, str]]] = {
    "trade mark": [
        (
            "https://www.legislation.gov.au/C2004A04969/latest/text",
            "Trade Marks Act 1995",
            "Act",
        ),
        (
            "https://www.legislation.gov.au/F1996B00084/latest/text",
            "Trade Marks Regulations 1995",
            "Regulations",
        ),
    ],
    "patent": [
        (
            "https://www.legislation.gov.au/C2004A04014/latest/text",
            "Patents Act 1990",
            "Act",
        ),
        (
            "https://www.legislation.gov.au/F1996B02697/latest/text",
            "Patents Regulations 1991",
            "Regulations",
        ),
    ],
    "design": [
        (
            "https://www.legislation.gov.au/C2004A01232/latest/text",
            "Designs Act 2003",
            "Act",
        ),
        (
            "https://www.legislation.gov.au/F2004B00136/latest/text",
            "Designs Regulations 2004",
            "Regulations",
        ),
    ],
    "pbr": [
        (
            "https://www.legislation.gov.au/C2004A04783/latest/text",
            "Plant Breeder\u2019s Rights Act 1994",
            "Act",
        ),
        (
            "https://www.legislation.gov.au/F1996B02512/latest/text",
            "Plant Breeder\u2019s Rights Regulations 1994",
            "Regulations",
        ),
    ],
    "copyright": [
        (
            "https://www.legislation.gov.au/C1968A00063/latest/text",
            "Copyright Act 1968",
            "Act",
        ),
        (
            "https://www.legislation.gov.au/F2017L01649/latest/text",
            "Copyright Regulations 2017",
            "Regulations",
        ),
    ],
}

# ──────────────────────────────────────────────────────────────────────
# 3.  PROVIDER REGISTRY
# ──────────────────────────────────────────────────────────────────────
# Canonical provider entries: (name, url, sameAs, @type override).
# The @type field here is resolved at build time depending on the
# archetype of the page; this registry supplies defaults.

@dataclass
class ProviderEntry:
    name: str
    url: str
    same_as: list[str] = field(default_factory=list)
    org_type: str = "Organization"  # default; overridden per-archetype


# Known government bodies.
_GOV_PROVIDERS: dict[str, ProviderEntry] = {
    "ip australia": ProviderEntry(
        name="IP Australia",
        url="https://www.ipaustralia.gov.au",
        same_as=["https://www.ipaustralia.gov.au"],
        org_type="GovernmentOrganization",
    ),
    "australian border force": ProviderEntry(
        name="Australian Border Force",
        url="https://www.abf.gov.au",
        same_as=["https://www.abf.gov.au"],
        org_type="GovernmentOrganization",
    ),
    "australian small business and family enterprise ombudsman": ProviderEntry(
        name="Australian Small Business and Family Enterprise Ombudsman",
        url="https://www.asbfeo.gov.au",
        same_as=["https://www.asbfeo.gov.au"],
        org_type="GovernmentOrganization",
    ),
    "court": ProviderEntry(
        name="Federal Court of Australia",
        url="https://www.fedcourt.gov.au",
        same_as=["https://www.fedcourt.gov.au"],
        org_type="GovernmentOrganization",
    ),
    "trans-tasman ip attorneys board": ProviderEntry(
        name="Trans-Tasman IP Attorneys Board",
        url="https://www.ttipattorney.gov.au",
        same_as=["https://www.ttipattorney.gov.au"],
        org_type="GovernmentOrganization",
    ),
}

# Known NGOs / international bodies.
_NGO_PROVIDERS: dict[str, ProviderEntry] = {
    "auda": ProviderEntry(
        name="auDA (.au Domain Administration Ltd)",
        url="https://www.auda.org.au",
        same_as=["https://www.auda.org.au"],
        org_type="NGO",
    ),
    "world intellectual property office": ProviderEntry(
        name="World Intellectual Property Organization (WIPO)",
        url="https://www.wipo.int",
        same_as=["https://www.wipo.int"],
        org_type="NGO",
    ),
    "world intellectual property office arbitration and mediation center": ProviderEntry(
        name="WIPO Arbitration and Mediation Center",
        url="https://www.wipo.int/amc/en/",
        same_as=["https://www.wipo.int/amc/en/"],
        org_type="NGO",
    ),
    "copyright council": ProviderEntry(
        name="Australian Copyright Council",
        url="https://www.copyright.org.au",
        same_as=["https://www.copyright.org.au"],
        org_type="NGO",
    ),
}

# Commercial / generic organisations.
_COMMERCIAL_PROVIDERS: dict[str, ProviderEntry] = {
    "legal service provider": ProviderEntry(
        name="Legal service provider",
        url="",
        org_type="Organization",
    ),
    "ecommerce provider": ProviderEntry(
        name="eCommerce provider",
        url="",
        org_type="Organization",
    ),
    "mediator": ProviderEntry(
        name="Mediator",
        url="",
        org_type="Organization",
    ),
    "arbitrator": ProviderEntry(
        name="Arbitrator",
        url="",
        org_type="Organization",
    ),
    "qualified facilitator": ProviderEntry(
        name="Qualified facilitator",
        url="",
        org_type="Organization",
    ),
    "qualified person": ProviderEntry(
        name="Qualified Person",
        url="",
        org_type="Organization",
    ),
    "ip insurers": ProviderEntry(
        name="IP Insurers",
        url="",
        org_type="Organization",
    ),
    "ip professionals": ProviderEntry(
        name="IP professionals",
        url="",
        org_type="Organization",
    ),
    "online marketplaces": ProviderEntry(
        name="Online Marketplaces",
        url="",
        org_type="Organization",
    ),
}


def _resolve_provider(name_raw: str) -> ProviderEntry | None:
    """Look up a provider by its CSV name (case-insensitive, stripped)."""
    key = name_raw.strip().lower()

    # Self-Help means no external provider entity is needed.
    if key in ("self-help", "self-help strategy", "self help", ""):
        return None

    # Handle compound providers (e.g. "ACCC, ASCS, AFP, IP Australia")
    # by resolving the first recognised government body.
    if "," in key:
        for fragment in key.split(","):
            result = _resolve_provider(fragment.strip())
            if result is not None:
                return result
        # Fallback: use the raw string as a generic organisation.
        return ProviderEntry(name=name_raw.strip(), url="", org_type="Organization")

    for registry in (_GOV_PROVIDERS, _NGO_PROVIDERS, _COMMERCIAL_PROVIDERS):
        if key in registry:
            return registry[key]

    # Fuzzy fallback: check if any registry key is contained in the input.
    for registry in (_GOV_PROVIDERS, _NGO_PROVIDERS, _COMMERCIAL_PROVIDERS):
        for reg_key, entry in registry.items():
            if reg_key in key or key in reg_key:
                return entry

    # Completely unknown provider; return a generic Organisation.
    return ProviderEntry(name=name_raw.strip(), url="", org_type="Organization")


# ──────────────────────────────────────────────────────────────────────
# 4.  ARCHETYPE MAPPER
# ──────────────────────────────────────────────────────────────────────

def resolve_archetype(csv_archetype: str) -> str:
    """Map the CSV 'Archectype' value to a Schema.org @type."""
    normalised = csv_archetype.strip().lower()
    mapping = {
        "self-help strategy": "Article",
        "self-help": "Article",
        "government service": "GovernmentService",
        "commercial third party service": "Service",
        "non-government third-party authority": "Service",
    }
    return mapping.get(normalised, "Article")


def resolve_provider_type_for_archetype(
    archetype_type: str, provider: ProviderEntry | None
) -> str:
    """
    Determine the Schema.org Organisation @type to use for the provider,
    respecting the rule:
      - GovernmentService  → always GovernmentOrganization
      - Service            → NGO or Organization (from registry)
      - Article            → use registry default
    """
    if provider is None:
        return "Organization"

    if archetype_type == "GovernmentService":
        return "GovernmentOrganization"

    if archetype_type == "Service":
        if provider.org_type == "GovernmentOrganization":
            # Edge case: the CSV says "Non-Government Third-Party Authority"
            # but the provider is actually governmental (e.g. Court).
            # Honour the provider's true nature.
            return "GovernmentOrganization"
        return provider.org_type  # "NGO" or "Organization"

    return provider.org_type


# ──────────────────────────────────────────────────────────────────────
# 5.  MARKDOWN PARSER
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ParsedSection:
    heading: str
    level: int
    body: str  # cleaned text (may include markdown lists)
    classification: str  # "intro", "section", "faq", "howto_step", "excluded"


@dataclass
class ParsedMarkdown:
    page_url: str
    title: str
    intro_text: str
    sections: list[ParsedSection]
    links: list[tuple[str, str]]  # (url, anchor_text)


def _clean_text(text: str) -> str:
    """Strip markdown noise: images, widget buttons, stray nbsp, excess whitespace."""
    # Remove image tags.
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove link-wrapped images: [![alt](img)](url)
    text = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", text)
    # Replace non-breaking spaces.
    text = text.replace("\u00a0", " ").replace("Â", "")
    # Remove italic disclaimer blocks (leading paragraph wrapped in *...*).
    # These span multiple lines and start with '*This IP First Response...'
    text = re.sub(
        r"\*This IP First Response.*?\*",
        "",
        text,
        flags=re.DOTALL,
    )
    # Collapse multiple blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_links(text: str, base_url: str = "") -> list[tuple[str, str]]:
    """Pull all markdown-style [text](url) links from the body.
    
    Handles both absolute URLs and relative paths (resolved against base_url).
    """
    results = []
    seen_urls: set[str] = set()

    # Determine the domain for resolving relative URLs.
    base_domain = ""
    if base_url:
        parsed = urlparse(base_url)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"

    for match in re.finditer(r"\[([^\]]*)\]\(([^\)]+)\)", text):
        anchor = match.group(1).strip()
        raw_url = match.group(2).strip()

        # Strip optional title text: [text](url "title")
        title_match = re.match(r'^([^\s"]+)(?:\s+"[^"]*")?$', raw_url)
        if title_match:
            raw_url = title_match.group(1)

        # Skip images, mailto, and anchor-only links.
        if raw_url.startswith(("mailto:", "#", "/sites/default/")):
            continue
        if any(raw_url.lower().endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg")):
            continue

        # Resolve relative URLs.
        if raw_url.startswith("/") and base_domain:
            url_clean = base_domain + raw_url
        elif raw_url.startswith("http"):
            url_clean = raw_url
        else:
            continue  # Skip unresolvable relative paths.

        if url_clean not in seen_urls:
            seen_urls.add(url_clean)
            results.append((url_clean, anchor))

    return results


def _classify_heading(heading: str) -> str:
    """
    Classify a heading into one of: section, faq, howto_step, excluded.

    Rules:
      1. If the heading is in the exclusion list, mark as excluded.
      2. If the heading matches a known FAQ pattern, mark as faq.
      3. If the heading ends with '?', mark as faq.
      4. If the heading contains 'step' or 'proceed' (case-insensitive),
         mark as howto_step.
      5. Otherwise, mark as section.
    """
    h_lower = heading.strip().lower().rstrip("?").strip()

    # Exclusion check.
    if h_lower in EXCLUDED_HEADINGS:
        return "excluded"

    # Check known section hints first (these override the '?' rule).
    for hint in SECTION_HEADING_HINTS:
        if hint in h_lower:
            return "section"

    # Known FAQ patterns.
    for pattern in FAQ_HEADING_PATTERNS:
        if re.search(pattern, heading.strip(), re.IGNORECASE):
            return "faq"

    # General question detection.
    if heading.strip().endswith("?"):
        return "faq"

    # HowTo step detection.
    if re.search(r"\bstep\b", heading, re.IGNORECASE):
        return "howto_step"
    if re.search(r"\bproceed\b", heading, re.IGNORECASE):
        return "howto_step"

    return "section"


def parse_markdown(md_text: str) -> ParsedMarkdown:
    """
    Parse a cleaned markdown file into structured blocks.

    Expects the file to optionally start with a PageURL line, followed
    by markdown headings (## or ###) and body content.
    """
    md_text = _clean_text(md_text)
    lines = md_text.split("\n")

    # ── Extract page URL (first line convention) ──
    # The PageURL line may use markdown link syntax:
    #   PageURL: "[https://...](https://...)"
    # We want the actual URL, not the display text portion.
    page_url = ""
    start_idx = 0
    first_line = lines[0].strip() if lines else ""
    if first_line.lower().startswith("pageurl:"):
        # Prefer the URL inside parentheses (the actual link target).
        paren_match = re.search(r'\]\((https?://[^\)]+)\)', first_line)
        if paren_match:
            page_url = paren_match.group(1).strip().rstrip('"')
        else:
            # Fallback: grab the first URL-like string.
            url_match = re.search(r'https?://[^\s\)"\]]+', first_line)
            page_url = url_match.group(0).rstrip('"') if url_match else ""
        start_idx = 1
    elif lines and re.search(r'https?://', first_line) and "ipfirstresponse" in first_line:
        paren_match = re.search(r'\]\((https?://[^\)]+)\)', first_line)
        if paren_match:
            page_url = paren_match.group(1).strip().rstrip('"')
        else:
            url_match = re.search(r'https?://[^\s\)"\]]+', first_line)
            page_url = url_match.group(0).rstrip('"') if url_match else ""
        start_idx = 1

    # ── Extract the document title (first H1) ──
    title = ""
    for line in lines[start_idx:]:
        if line.startswith("# ") and not line.startswith("## "):
            title = line.lstrip("# ").strip()
            break

    # ── Split into heading + body blocks ──
    heading_pattern = re.compile(r"^(#{1,4})\s+(.+)$")
    blocks: list[tuple[str, int, list[str]]] = []
    current_heading = ""
    current_level = 0
    current_body: list[str] = []

    for line in lines[start_idx:]:
        m = heading_pattern.match(line)
        if m:
            # Flush previous block.
            if current_heading or current_body:
                blocks.append((current_heading, current_level, current_body))
            current_heading = m.group(2).strip()
            current_level = len(m.group(1))
            current_body = []
        else:
            current_body.append(line)

    # Flush final block.
    if current_heading or current_body:
        blocks.append((current_heading, current_level, current_body))

    # ── Build parsed sections ──
    # Derive domain for relative URL resolution.
    base_domain = ""
    if page_url:
        _parsed = urlparse(page_url)
        base_domain = f"{_parsed.scheme}://{_parsed.netloc}"

    all_links = _extract_links(md_text, page_url)
    sections: list[ParsedSection] = []
    intro_parts: list[str] = []

    for heading, level, body_lines in blocks:
        body_text = "\n".join(body_lines).strip()

        # Content before the first meaningful heading is intro text.
        if not heading:
            intro_parts.append(body_text)
            continue

        # Skip the title itself when it reappears as a heading.
        if heading == title:
            # But capture any body underneath it as intro.
            if body_text:
                intro_parts.append(body_text)
            continue

        classification = _classify_heading(heading)
        sections.append(
            ParsedSection(
                heading=heading,
                level=level,
                body=body_text,
                classification=classification,
            )
        )

    intro_text = "\n\n".join(p for p in intro_parts if p).strip()
    # Strip any remaining link/formatting markup from intro for clean articleBody.
    intro_text_clean = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", intro_text)
    intro_text_clean = re.sub(r"!\[.*?\]\(.*?\)", "", intro_text_clean)
    intro_text_clean = re.sub(r"\[\s*\]\([^\)]+\)", "", intro_text_clean)
    intro_text_clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", intro_text_clean)
    intro_text_clean = re.sub(r"\*\*(.+?)\*\*", r"\1", intro_text_clean)
    intro_text_clean = re.sub(r"\n{3,}", "\n\n", intro_text_clean).strip()

    return ParsedMarkdown(
        page_url=page_url,
        title=title or "Untitled",
        intro_text=intro_text_clean,
        sections=sections,
        links=all_links,
    )


# ──────────────────────────────────────────────────────────────────────
# 6.  CSV CONTROL PLANE LOADER
# ──────────────────────────────────────────────────────────────────────

@dataclass
class MetaRecord:
    udid: str
    overtitle: str
    main_title: str
    description: str
    canonical_url: str
    entry_point: str
    relevant_ip_right: str
    estimate_cost: str
    estimated_effort: str
    resolution_rate: str
    archetype: str
    provider: str
    publication_date: str
    last_updated: str
    additional_disclaimer: str


def load_metatable(csv_path: str | Path) -> dict[str, MetaRecord]:
    """
    Load the CSV control plane, returning a dict keyed by canonical URL
    (stripped and lowercased) for fast lookup.
    """
    records: dict[str, MetaRecord] = {}
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"[WARN] Metatable not found at {csv_path}; proceeding without metadata.")
        return records

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            # The CSV has a trailing space on 'Archectype ' — handle that.
            archetype_key = None
            for k in row:
                if k.strip().lower().startswith("archectype") or k.strip().lower().startswith("archetype"):
                    archetype_key = k
                    break

            rec = MetaRecord(
                udid=row.get("UDID", "").strip(),
                overtitle=row.get("Overtitle", "").strip(),
                main_title=row.get("Main-title", "").strip(),
                description=row.get("Description", "").strip(),
                canonical_url=row.get("Canonical-url", "").strip(),
                entry_point=row.get("Entry-point", "").strip(),
                relevant_ip_right=row.get("Relevant-ip-right", "").strip(),
                estimate_cost=row.get("Estimate-cost", "").strip(),
                estimated_effort=row.get("Estimated-effort", "").strip(),
                resolution_rate=row.get("Resolution-rate", "").strip(),
                archetype=row.get(archetype_key, "").strip() if archetype_key else "",
                provider=row.get("Provider", "").strip(),
                publication_date=row.get("Publication-date", "").strip(),
                last_updated=row.get("Last-updated", "").strip(),
                additional_disclaimer=row.get("Additional-disclaimer", "").strip(),
            )
            url_key = rec.canonical_url.lower().rstrip("/")
            records[url_key] = rec

    print(f"[INFO] Loaded {len(records)} records from metatable.")
    return records


def match_meta(
    parsed: ParsedMarkdown, metatable: dict[str, MetaRecord]
) -> MetaRecord | None:
    """Match a parsed markdown document to its CSV metadata row."""
    # Primary: exact URL match.
    url_key = parsed.page_url.lower().rstrip("/")
    if url_key in metatable:
        return metatable[url_key]

    # Fallback: fuzzy title match.
    for rec in metatable.values():
        if rec.main_title.lower().strip() == parsed.title.lower().strip():
            return rec

    return None


# ──────────────────────────────────────────────────────────────────────
# 7.  DATE UTILITIES
# ──────────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> str:
    """Convert various date formats to ISO 8601 (YYYY-MM-DD)."""
    raw = raw.strip()
    if not raw or raw.lower() == "null":
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw  # return as-is if unparseable


# ──────────────────────────────────────────────────────────────────────
# 8.  LINK & SLUG UTILITIES
# ──────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Produce a URL-safe slug from a heading."""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def _link_name_from_url(url: str, anchor: str) -> str:
    """Derive a human-readable name from a link's anchor text or URL path."""
    if anchor and not anchor.startswith("http"):
        # Clean markdown bold, italics, etc. from anchor text.
        name = re.sub(r"[*_]", "", anchor).strip()
        if name:
            return name

    # Fallback: derive from URL path.
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if "/" in path else path
    return slug.replace("-", " ").replace("_", " ").strip().title() or url


# ──────────────────────────────────────────────────────────────────────
# 9.  LEGISLATION RESOLVER
# ──────────────────────────────────────────────────────────────────────

def resolve_legislation(ip_right_field: str) -> list[tuple[str, str, str]]:
    """
    Given the CSV 'Relevant-ip-right' field, return deduplicated legislation
    entries. The field may contain multiple quoted keywords, e.g.:
        "Trade Mark", "Copyright"
    or a catch-all:
        "Any dispute related to intellectual property"
    """
    normalised = ip_right_field.lower().replace('"', "").replace("'", "")

    # Catch-all: include everything.
    if "any dispute" in normalised:
        all_laws: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for entries in LEGISLATION_MAP.values():
            for entry in entries:
                if entry[0] not in seen:
                    all_laws.append(entry)
                    seen.add(entry[0])
        return all_laws

    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    keyword_aliases: dict[str, str] = {
        "trade mark": "trade mark",
        "trade marks": "trade mark",
        "trademark": "trade mark",
        "unregistered-tm": "trade mark",
        "unregistered tm": "trade mark",
        "unreistered tm": "trade mark",  # typo in CSV
        "patent": "patent",
        "patents": "patent",
        "design": "design",
        "designs": "design",
        "pbr": "pbr",
        "plant breeder": "pbr",
        "copyright": "copyright",
    }

    for alias, canonical_key in keyword_aliases.items():
        if alias in normalised and canonical_key in LEGISLATION_MAP:
            for entry in LEGISLATION_MAP[canonical_key]:
                if entry[0] not in seen:
                    results.append(entry)
                    seen.add(entry[0])

    return results


# ──────────────────────────────────────────────────────────────────────
# 10. BODY TEXT FORMATTER
# ──────────────────────────────────────────────────────────────────────

def _format_body_text(raw_body: str) -> str:
    """
    Convert markdown body text into clean plain text suitable for
    Schema.org `text` or `articleBody` fields. Preserves list structure
    using '- ' prefixes but strips link markup and bold/italic markers.
    """
    text = raw_body

    # Remove image links: [![alt](img)](url)
    text = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", text)
    # Remove standalone images: ![alt](url)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove empty-text links: [](url)
    text = re.sub(r"\[\s*\]\([^\)]+\)", "", text)
    # Convert markdown links [text](url) → text.
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Strip bold / italic markers.
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Strip link title references like [text](/path "title").
    text = re.sub(r'\s*"[^"]*"\s*', "", text)
    # Normalise list bullets from * to -.
    text = re.sub(r"^(\s*)\*\s+", r"\1- ", text, flags=re.MULTILINE)
    # Normalise whitespace.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ──────────────────────────────────────────────────────────────────────
# 11. JSON-LD BUILDER
# ──────────────────────────────────────────────────────────────────────

def build_jsonld(parsed: ParsedMarkdown, meta: MetaRecord | None) -> dict:
    """Assemble the full @graph JSON-LD document."""

    base_url = parsed.page_url or (meta.canonical_url if meta else "")
    udid = meta.udid if meta else ""
    main_title = (meta.main_title if meta else "") or parsed.title
    description = (meta.description if meta else "").strip('"').strip()
    pub_date = _parse_date(meta.publication_date) if meta else ""
    mod_date = _parse_date(meta.last_updated) if meta else ""
    disclaimer = (meta.additional_disclaimer if meta else "").strip()
    copyright_year = ""
    if mod_date:
        try:
            copyright_year = int(mod_date[:4])
        except (ValueError, IndexError):
            copyright_year = date.today().year

    # ── Resolve archetype and provider ──
    archetype_type = resolve_archetype(meta.archetype) if meta else "Article"
    provider_entry = _resolve_provider(meta.provider) if meta else None
    provider_org_type = resolve_provider_type_for_archetype(archetype_type, provider_entry)

    # ── Resolve "about" from the relevant IP right field ──
    about_name = "Any dispute related to intellectual property"
    if meta and meta.relevant_ip_right:
        about_raw = meta.relevant_ip_right.strip('"').strip()
        if about_raw:
            about_name = about_raw

    # ── Build the organisation entity ──
    org_id = f"{provider_entry.url}/#organization" if (provider_entry and provider_entry.url) else f"{base_url}/#organization"

    if provider_entry and provider_entry.name.lower() not in ("self-help", ""):
        org_entity = {
            "@type": provider_org_type,
            "@id": org_id,
            "name": provider_entry.name,
        }
        if provider_entry.url:
            org_entity["url"] = provider_entry.url
        if provider_entry.same_as:
            org_entity["sameAs"] = provider_entry.same_as
    else:
        # Default to IP Australia when provider is Self-Help.
        ip_au = _GOV_PROVIDERS["ip australia"]
        org_id = f"{ip_au.url}/#organization"
        org_entity = {
            "@type": "GovernmentOrganization",
            "@id": org_id,
            "name": ip_au.name,
            "url": ip_au.url,
            "sameAs": ip_au.same_as,
        }

    # ── Classify sections and build sub-entities ──
    faq_questions: list[ParsedSection] = []
    content_sections: list[ParsedSection] = []
    howto_steps: list[ParsedSection] = []
    article_body_text = parsed.intro_text  # fallback

    # Check if the CSV overtitle appears as a heading; if so, skip it
    # (it's a navigational label, not content).
    overtitle_lower = (meta.overtitle.lower().strip() if meta else "")

    for sec in parsed.sections:
        if sec.classification == "excluded":
            continue

        # Skip overtitle headings (e.g. "Letter of demand" when the title
        # is "Receiving a letter of demand").
        if overtitle_lower and sec.heading.lower().strip() == overtitle_lower:
            # If it has body content, treat it as intro.
            if sec.body.strip():
                article_body_text = _format_body_text(sec.body)
            continue

        # Check if this heading should supply the articleBody.
        heading_lower = sec.heading.lower().strip().rstrip("?")
        is_article_body_source = any(
            hint in heading_lower for hint in ARTICLE_BODY_HEADINGS
        )
        if is_article_body_source and sec.body.strip():
            article_body_text = _format_body_text(sec.body)
            # For Article types, this becomes the articleBody directly.
            # For Service/GovernmentService types, we still need to keep
            # this content as a section, since those types have no
            # articleBody field.
            if archetype_type != "Article":
                content_sections.append(sec)
            continue

        if sec.classification == "faq":
            faq_questions.append(sec)
        elif sec.classification == "howto_step":
            howto_steps.append(sec)
        else:
            content_sections.append(sec)

    # ── Build section IDs ──
    section_ids: list[str] = []
    section_entities: list[dict] = []
    for idx, sec in enumerate(content_sections, start=1):
        slug = _slugify(sec.heading)
        sec_id = f"{base_url}#section-{idx}-{slug}"
        section_ids.append(sec_id)
        section_entities.append(
            {
                "@type": "WebPageElement",
                "@id": sec_id,
                "headline": sec.heading,
                "text": _format_body_text(sec.body),
                "position": idx,
                "isPartOf": {"@id": f"{base_url}#{archetype_type.lower()}"},
            }
        )

    # ── Build FAQ entity ──
    faq_id = f"{base_url}#faq"
    faq_entity = None
    if faq_questions:
        q_entities = []
        for qi, q in enumerate(faq_questions, start=1):
            q_id = f"{faq_id}#q{qi}"
            q_entities.append(
                {
                    "@type": "Question",
                    "@id": q_id,
                    "name": q.heading.rstrip("?").strip() + "?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "@id": f"{q_id}-a",
                        "text": _format_body_text(q.body),
                    },
                }
            )
        faq_entity = {
            "@type": "FAQPage",
            "@id": faq_id,
            "url": faq_id,
            "inLanguage": DEFAULT_LANGUAGE,
            "isPartOf": {"@id": f"{base_url}#webpage"},
            "mainEntity": q_entities,
        }

    # ── Build HowTo entity (if applicable) ──
    howto_entity = None
    if howto_steps:
        step_entities = []
        for si, step in enumerate(howto_steps, start=1):
            step_entities.append(
                {
                    "@type": "HowToStep",
                    "position": si,
                    "name": step.heading,
                    "text": _format_body_text(step.body),
                }
            )
        howto_entity = {
            "@type": "HowTo",
            "@id": f"{base_url}#howto",
            "name": main_title,
            "step": step_entities,
        }

    # ── Collect unique links ──
    link_objects: list[dict] = []
    seen_link_urls: set[str] = set()

    # Filter out noisy links (feedback forms, email, images, CMS nodes).
    noise_patterns = ["qualtrics.com", "mailto:", "/sites/default/files/", "/node/"]
    for url, anchor in parsed.links:
        if any(p in url for p in noise_patterns):
            continue
        # Skip self-referencing URLs (the page linking to itself).
        if base_url and url.rstrip("/") == base_url.rstrip("/"):
            continue
        if url not in seen_link_urls:
            seen_link_urls.add(url)
            link_objects.append(
                {
                    "@type": "WebPage",
                    "@id": url,
                    "url": url,
                    "name": _link_name_from_url(url, anchor),
                }
            )

    # ── Legislation ──
    legislation_entries = resolve_legislation(meta.relevant_ip_right) if meta else []
    citation_refs = [{"@id": entry[0]} for entry in legislation_entries]
    legislation_entities = [
        {
            "@type": "Legislation",
            "@id": entry[0],
            "name": entry[1],
            "url": entry[0],
            "legislationType": entry[2],
        }
        for entry in legislation_entries
    ]

    # ── Assemble hasPart references for the WebPage ──
    has_part_refs: list[dict] = []
    if faq_entity:
        has_part_refs.append({"@id": faq_id})
    for sid in section_ids:
        has_part_refs.append({"@id": sid})

    # ── Build the disclaimer section if present ──
    if disclaimer and disclaimer.lower() != "null":
        disclaimer_slug = "disclaimer"
        disclaimer_id = f"{base_url}#section-{len(content_sections) + 1}-{disclaimer_slug}"
        disclaimer_entity = {
            "@type": "WebPageElement",
            "@id": disclaimer_id,
            "headline": "Disclaimer",
            "text": disclaimer,
            "position": len(content_sections) + 1,
            "isPartOf": {"@id": f"{base_url}#{archetype_type.lower()}"},
        }
        section_entities.append(disclaimer_entity)
        has_part_refs.append({"@id": disclaimer_id})

    # ── Build the WebPage entity ──
    webpage_entity: dict = {
        "@type": "WebPage",
        "@id": f"{base_url}#webpage",
        "url": base_url,
        "headline": f"{main_title} - {WEBSITE_NAME}",
        "description": description,
        "identifier": udid,
        "about": {"@type": "Thing", "name": about_name},
        "inLanguage": DEFAULT_LANGUAGE,
        "license": DEFAULT_LICENCE,
        "audience": {
            "@type": "BusinessAudience",
            "audienceType": "Small and medium businesses",
            "geographicArea": {"@type": "Country", "name": "Australia"},
        },
        "usageInfo": (
            "This information is general in nature and does not constitute "
            "legal advice. You should consider obtaining professional advice "
            "that is specific to your circumstances."
        ),
        "publisher": {"@id": org_id},
        "isPartOf": {"@id": WEBSITE_ID},
        "mainEntity": {"@id": f"{base_url}#{archetype_type.lower()}"},
    }
    if pub_date:
        webpage_entity["datePublished"] = pub_date
    if mod_date:
        webpage_entity["dateModified"] = mod_date
    if copyright_year:
        webpage_entity["copyrightYear"] = copyright_year
        webpage_entity["copyrightHolder"] = {"@id": org_id}
    webpage_entity["creditText"] = "IP First Response initiative led by IP Australia"
    if has_part_refs:
        webpage_entity["hasPart"] = has_part_refs

    # ── Build the main content entity (Article / GovernmentService / Service) ──
    main_entity: dict = {
        "@type": archetype_type,
        "@id": f"{base_url}#{archetype_type.lower()}",
        "headline": main_title,
        "description": description,
        "inLanguage": DEFAULT_LANGUAGE,
        "license": DEFAULT_LICENCE,
        "publisher": {"@id": org_id},
        "mainEntityOfPage": {"@id": f"{base_url}#webpage"},
    }

    # Article-specific fields.
    if archetype_type == "Article":
        main_entity["articleBody"] = article_body_text or description
        if pub_date:
            main_entity["datePublished"] = pub_date
        if mod_date:
            main_entity["dateModified"] = mod_date

    # GovernmentService-specific fields.
    if archetype_type == "GovernmentService":
        main_entity["serviceType"] = meta.archetype if meta else "Government Service"
        main_entity["serviceOperator"] = {"@id": org_id}
        if provider_entry and provider_entry.url:
            main_entity["provider"] = {"@id": org_id}
        if article_body_text:
            main_entity["text"] = article_body_text

    # Service-specific fields.
    if archetype_type == "Service":
        main_entity["serviceType"] = meta.archetype if meta else "Service"
        main_entity["provider"] = {"@id": org_id}
        if article_body_text:
            main_entity["text"] = article_body_text

    # HowTo reference (if applicable).
    if howto_entity:
        main_entity["hasPart"] = [{"@id": f"{base_url}#howto"}]
        article_parts = main_entity.get("hasPart", [])
    else:
        article_parts = []

    # Attach section + FAQ references to the main entity.
    for sid in section_ids:
        article_parts.append({"@id": sid})
    if faq_entity:
        article_parts.append({"@id": faq_id})
    if article_parts:
        main_entity["hasPart"] = article_parts

    # Citations.
    if citation_refs:
        main_entity["citation"] = citation_refs

    # Related links (as semantically rich WebPage objects).
    if link_objects:
        main_entity["relatedLink"] = link_objects

    # ── Assemble the @graph ──
    graph: list[dict] = []

    # 1. Organisation.
    graph.append(org_entity)

    # 2. WebSite.
    graph.append(
        {
            "@type": "WebSite",
            "@id": WEBSITE_ID,
            "name": WEBSITE_NAME,
            "url": WEBSITE_URL,
            "publisher": {"@id": org_id},
            "inLanguage": DEFAULT_LANGUAGE,
            "license": DEFAULT_LICENCE,
        }
    )

    # 3. WebPage.
    graph.append(webpage_entity)

    # 4. Main content entity.
    graph.append(main_entity)

    # 5. HowTo (if any).
    if howto_entity:
        graph.append(howto_entity)

    # 6. Content sections.
    graph.extend(section_entities)

    # 7. FAQ.
    if faq_entity:
        graph.append(faq_entity)

    # 8. Legislation.
    graph.extend(legislation_entities)

    return {"@context": SCHEMA_CONTEXT, "@graph": graph}


# ──────────────────────────────────────────────────────────────────────
# 12. MAIN PIPELINE
# ──────────────────────────────────────────────────────────────────────

def process_single_file(
    md_path: Path,
    metatable: dict[str, MetaRecord],
    output_dir: Path,
) -> Path | None:
    """Process one markdown file and write the JSON-LD output."""
    md_text = md_path.read_text(encoding="utf-8")
    parsed = parse_markdown(md_text)
    meta = match_meta(parsed, metatable)

    if meta:
        print(f"  [OK]  {md_path.name} → matched UDID: {meta.udid}")
    else:
        print(f"  [WARN] {md_path.name} → no CSV match found; using defaults.")

    jsonld = build_jsonld(parsed, meta)

    # Determine output filename: prefer UDID-based naming.
    if meta and meta.udid:
        out_name = f"{meta.udid}_{_slugify(meta.main_title)}.json"
    else:
        out_name = f"{md_path.stem}.json"

    out_path = output_dir / out_name
    out_path.write_text(json.dumps(jsonld, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert Markdown files to Schema.org JSON-LD."
    )
    parser.add_argument(
        "--md-dir",
        type=str,
        default="./IPFR-Webpages",
        help="Directory containing .md files to convert.",
    )
    parser.add_argument(
        "--md-file",
        type=str,
        default=None,
        help="Path to a single .md file to convert (overrides --md-dir).",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="./metatable-Content.csv",
        help="Path to the metatable CSV control plane.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="./json_output",
        help="Output directory for JSON-LD files.",
    )

    args = parser.parse_args()
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    metatable = load_metatable(args.csv)

    if args.md_file:
        md_files = [Path(args.md_file)]
    else:
        md_dir = Path(args.md_dir)
        if not md_dir.exists():
            print(f"[ERROR] Markdown directory not found: {md_dir}")
            sys.exit(1)
        md_files = sorted(md_dir.glob("*.md"))

    if not md_files:
        print("[ERROR] No .md files found to process.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Markdown → JSON-LD Converter")
    print(f"  Processing {len(md_files)} file(s)")
    print(f"{'='*60}\n")

    results: list[Path] = []
    for md_path in md_files:
        result = process_single_file(md_path, metatable, output_dir)
        if result:
            results.append(result)

    print(f"\n{'='*60}")
    print(f"  Complete: {len(results)}/{len(md_files)} files converted.")
    print(f"  Output:   {output_dir.resolve()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

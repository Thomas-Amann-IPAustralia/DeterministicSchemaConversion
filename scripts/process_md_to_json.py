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
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


# ──────────────────────────────────────────────────────────────────────
# 1.  CONSTANTS & CONFIGURATION
# ──────────────────────────────────────────────────────────────────────

SCHEMA_CONTEXT = "https://schema.org"

WEBSITE_ID = "https://ipfirstresponse.ipaustralia.gov.au/#website"
WEBSITE_NAME = "IP First Response"
WEBSITE_URL = "https://ipfirstresponse.ipaustralia.gov.au/"

DEFAULT_LANGUAGE = "en-AU"
DEFAULT_LICENCE = "https://creativecommons.org/licenses/by/4.0/"

# ── Hardcoded IP Australia identity (always the publisher & copyrightHolder) ──
IP_AUSTRALIA_ID = "https://www.ipaustralia.gov.au/#organization"
IP_AUSTRALIA_ENTITY: dict = {
    "@type": "GovernmentOrganization",
    "@id": IP_AUSTRALIA_ID,
    "name": "IP Australia",
    "url": "https://www.ipaustralia.gov.au",
    "parentOrganization": {
        "@type": "GovernmentOrganization",
        "name": "Australian Government",
        "sameAs":"https://www.wikidata.org/wiki/Q2991162"
    },
    "sameAs": [ "https://www.wikidata.org/wiki/Q5973154",
    "https://en.wikipedia.org/wiki/IP_Australia"
    ],
    "knowsAbout": [
      "Intellectual Property",
      "Patents",
      "Trade Marks",
      "Design Rights",
      "Plant Breeder's Rights",
      "Intellectual Property Disputes"
    ],
    "contactPoint": {
      "@type": "ContactPoint",
      "contactType": "IP First Response content managers",
      "email": "IPFirstResponse@IPAustralia.gov.au",
      "description": "Feedback and enquiries regarding IP First Response"
    },
}

# ── Standard disclaimer (hardcoded on every page as usageInfo) ──
STANDARD_DISCLAIMER: dict = {
    "@type": "CreativeWork",
    "name": "Disclaimer and Feedback Policy",
    "text": (
        "This IP First Response website has been designed to help IP rights "
        "holders navigate IP infringement and enforcement by making it visible, "
        "accessible, and to provide information about the factors involved in "
        "pursuing different options. It does not provide legal, business or "
        "other professional advice, and none of the content should be regarded "
        "as recommending a specific course of action. We welcome any feedback "
        "via our IP First Response feedback form and by emailing us."
    ),
    "url": "mailto:IPFirstResponse@IPAustralia.gov.au?subject=Feedback on IP First Response",
}

# ── IP topic → Wikidata sameAs map (for 'about' Thing objects) ──
IP_TOPIC_MAP: dict[str, str] = {
    "intellectual property right": "https://www.wikidata.org/wiki/Q108855835",
    "trade mark": "https://www.wikidata.org/wiki/Q165196",
    "trade marks": "https://www.wikidata.org/wiki/Q165196",
    "trademark": "https://www.wikidata.org/wiki/Q165196",
    "unregistered-tm": "https://www.wikidata.org/wiki/Q165196",
    "unregistered tm": "https://www.wikidata.org/wiki/Q165196",
    "patent": "https://www.wikidata.org/wiki/Q253623",
    "patents": "https://www.wikidata.org/wiki/Q253623",
    "design": "https://www.wikidata.org/wiki/Q1240325",
    "designs": "https://www.wikidata.org/wiki/Q1240325",
    "copyright": "https://www.wikidata.org/wiki/Q12978",
    "pbr": "https://www.wikidata.org/wiki/Q695112",
    "plant breeder's rights": "https://www.wikidata.org/wiki/Q695112",
    "plant breeder": "https://www.wikidata.org/wiki/Q695112",
}

# ── Canonical display names for IP topics (sentence case) ──
# Ensures consistent naming regardless of CSV input casing.
IP_TOPIC_DISPLAY_NAMES: dict[str, str] = {
    "trade mark": "Trade mark",
    "trade marks": "Trade mark",
    "trademark": "Trade mark",
    "unregistered-tm": "Unregistered trade mark",
    "unregistered tm": "Unregistered trade mark",
    "patent": "Patent",
    "patents": "Patent",
    "design": "Design",
    "designs": "Design",
    "copyright": "Copyright",
    "pbr": "Plant breeder's rights",
    "plant breeder's rights": "Plant breeder's rights",
    "plant breeder": "Plant breeder's rights",
    "intellectual property right": "Intellectual property",
}

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
            "Plant Breeder's Rights Act 1994",
            "Act",
        ),
        (
            "https://www.legislation.gov.au/F1996B02512/latest/text",
            "Plant Breeder's Rights Regulations 1994",
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
    alternate_name: str | list[str] | None = None
    org_type: str = "Organization"  # default; overridden per-archetype


# Known government bodies.
_GOV_PROVIDERS: dict[str, ProviderEntry] = {
    "ip australia": ProviderEntry(
        name="IP Australia",
        alternate_name="Intellectual Property Australia",
        url="https://www.ipaustralia.gov.au",
        same_as=["https://www.wikidata.org/wiki/Q5973154"],
        org_type="GovernmentOrganization",
    ),
    "australian border force": ProviderEntry(
        name="Australian Border Force",
        alternate_name="ABF",
        url="https://www.abf.gov.au",
        same_as=["https://www.wikidata.org/wiki/Q17000879"],
        org_type="GovernmentOrganization",
    ),
    "australian small business and family enterprise ombudsman": ProviderEntry(
        name="Australian Small Business and Family Enterprise Ombudsman",
        alternate_name="ASBFEO",
        url="https://www.asbfeo.gov.au",
        same_as=["https://www.asbfeo.gov.au"],
        org_type="GovernmentOrganization",
    ),
    "court": ProviderEntry(
        name="Federal Court of Australia",
        url="https://www.fedcourt.gov.au",
        same_as=["https://www.wikidata.org/wiki/Q1400030"],
        org_type="GovernmentOrganization",
    ),
    "trans-tasman ip attorneys board": ProviderEntry(
        name="Trans-Tasman IP Attorneys Board",
        alternate_name="TTIPA",
        url="https://www.ttipattorney.gov.au",
        same_as=["https://www.ttipattorney.gov.au"],
        org_type="GovernmentOrganization",
    ),
}

# Known NGOs / international bodies.
_NGO_PROVIDERS: dict[str, ProviderEntry] = {
    "auda": ProviderEntry(
        name=".au Domain Administration",
        alternate_name="auDA",
        url="https://www.auda.org.au",
        same_as=["https://www.wikidata.org/wiki/Q151602"],
        org_type="NGO",
    ),
    "world intellectual property office": ProviderEntry(
        name="World Intellectual Property Organization",
        alternate_name="WIPO",
        url="https://www.wipo.int",
        same_as=["https://www.wikidata.org/wiki/Q177773"],
        org_type="NGO",
    ),
    "world intellectual property office arbitration and mediation center": ProviderEntry(
        name="WIPO Arbitration and Mediation Center",
        url="https://www.wipo.int/amc/en/",
        same_as=["https://www.wikidata.org/wiki/Q177773"],
        org_type="NGO",
    ),
    "copyright council": ProviderEntry(
        name="Australian Copyright Council",
        url="https://www.copyright.org.au",
        same_as=["https://www.wikidata.org/wiki/Q4824042"],
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
        same_as=["https://www.wikidata.org/wiki/Q4859473"],
        url="",
        org_type="Organization",
    ),
    "arbitrator": ProviderEntry(
        name="Arbitrator",
        same_as=["https://www.wikidata.org/wiki/Q105425483"],
        url="",
        org_type="Organization",
    ),
    "qualified facilitator": ProviderEntry(
        name="Qualified facilitator",
        same_as=["https://www.wikidata.org/wiki/Q1150166"],
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
        same_as=["https://www.wikidata.org/wiki/Q3390477"],
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


def _repair_mojibake(text: str) -> str:
    """
    Repair common UTF-8 to Windows-1252 mojibake sequences.

    Smart quotes and apostrophes encoded as UTF-8 but decoded as CP-1252
    produce characteristic multi-byte artefacts such as 'a euro tm' for
    the right single quotation mark (U+2019).
    """
    # Attempt byte-level repair: re-encode mojibaked segments as latin-1
    # then decode as UTF-8. This handles the general case robustly.
    # We do this in a safe, segment-by-segment manner.
    #
    # Common visible mojibake patterns (CP-1252 interpretation of UTF-8 bytes):
    #   U+2019 ' (right single quote): â€™
    #   U+2018 ' (left single quote):  â€˜
    #   U+201C " (left double quote):  â€œ
    #   U+2013 – (en dash):           â€"
    #   U+2026 … (ellipsis):          â€¦
    #   U+202F   (narrow no-break):    â€¯
    #   U+2009   (thin space):         â€‰

    # Pattern: â (0xC3 0xA2) followed by € (0xE2 0x82 0xAC in UTF-8, but
    # in mojibake context it's the CP-1252 byte 0x80) followed by another
    # character. We match the known visible sequences directly.
    mojibake_map = [
        ("\u00e2\u0080\u0099", "\u2019"),  # right single quote
        ("\u00e2\u0080\u0098", "\u2018"),  # left single quote
        ("\u00e2\u0080\u009c", "\u201c"),  # left double quote
        ("\u00e2\u0080\u009d", "\u201d"),  # right double quote
        ("\u00e2\u0080\u0093", "\u2013"),  # en dash
        ("\u00e2\u0080\u0094", "\u2014"),  # em dash
        ("\u00e2\u0080\u00a6", "\u2026"),  # ellipsis
        ("\u00e2\u0080\u00af", "\u202f"),  # narrow no-break space
        ("\u00e2\u0080\u0089", "\u2009"),  # thin space
    ]
    for bad, good in mojibake_map:
        text = text.replace(bad, good)

    # Byte-round-trip repair for any remaining mojibake not in the
    # explicit map.  Only attempted when the text still contains
    # C1 control characters (U+0080–U+009F), which are the strongest
    # signal of mojibake: they are the CP-1252 interpretation of UTF-8
    # continuation bytes and virtually never appear in legitimate text.
    # After the explicit map has cleaned known sequences, any remaining
    # C1 controls indicate unmapped mojibake worth repairing.
    _MOJIBAKE_MARKER = re.compile(r"[\u0080-\u009f]")
    if _MOJIBAKE_MARKER.search(text):
        try:
            # Use latin-1 (not cp1252) because the mojibake characters
            # in the explicit map above use C1 control codepoints
            # (U+0080–U+009F) which are the latin-1 1:1 byte mappings,
            # not the CP-1252 mappings (e.g. U+0080 = byte 0x80 in
            # latin-1, vs U+20AC = byte 0x80 in CP-1252).
            repaired = text.encode("latin-1", errors="ignore").decode(
                "utf-8", errors="ignore"
            )
            # Accept the repair only if it didn't lose significant
            # content.  When mojibake resolves, 3 codepoints compress
            # to 1, so the repaired string is naturally shorter.  The
            # C1-control marker already provides high confidence, so
            # we use a generous threshold here.
            if len(repaired) >= len(text) * 0.7:
                text = repaired
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

    return text


def _clean_text(text: str) -> str:
    """Strip markdown noise: images, widget buttons, stray nbsp, excess whitespace."""
    # Repair mojibake before any further processing.
    text = _repair_mojibake(text)
    # Remove image tags.
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove link-wrapped images: [![alt](img)](url)
    text = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", text)
    # Replace non-breaking spaces.
    text = text.replace("\u00a0", " ").replace("Â", "")
    # Remove strikethrough artefacts.
    text = re.sub(r"~~.*?~~", "", text)
    # Remove the italic disclaimer paragraph. Use a tightly anchored pattern
    # that matches the entire paragraph (across inner italic/link spans)
    # to avoid accidentally stripping unrelated bold/italic content.
    text = re.sub(
        r"^\s*\*This IP First Response[^\n]*?emailing us[^\n]*?\*[\.\s]*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Fallback: if the above didn't catch it (e.g. multi-line disclaimer),
    # match the full italic block but only if it starts with the known prefix.
    text = re.sub(
        r"\*This IP First Response website has been designed to help IP rights "
        r"holders.*?emailing us\*[\.\s]*",
        "",
        text,
        flags=re.DOTALL,
    )
    # Also strip the Before you take any action... disclaimer block.
    text = re.sub(
        r"\*Before you take any action.*?consultation with an attorney\*[\.\s]*",
        "",
        text,
        flags=re.DOTALL,
    )
    # Collapse multiple blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_tracking_params(url: str) -> str:
    """Remove known analytics/tracking query parameters from a URL.

    Strips parameters matching common tracking patterns (_gl, _ga, utm_*)
    and returns the cleaned URL. If all parameters are removed, the trailing
    '?' is also stripped.
    """
    TRACKING_PREFIXES = ("utm_", "_gl", "_ga")
    parsed = urlparse(url)
    if not parsed.query:
        return url
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {
        k: v for k, v in params.items()
        if not any(k.startswith(prefix) for prefix in TRACKING_PREFIXES)
    }
    new_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return urlunparse(parsed._replace(query=new_query))


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

        # Strip known tracking query parameters before deduplication.
        url_clean = _strip_tracking_params(url_clean)

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
    # Run the unified body text formatter for consistent markdown stripping,
    # footnote removal, and mojibake repair (replaces prior ad-hoc cleanup).
    intro_text_clean = _format_body_text(intro_text)

    return ParsedMarkdown(
        page_url=page_url,
        title=_repair_mojibake(title) if title else "Untitled",
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
    keywords: list[str]


def _sentence_case(text: str) -> str:
    """Normalise a string to sentence case.

    Capitalises the first letter and lowercases the remainder, while
    preserving known acronyms and proper nouns that appear in the IP
    domain (e.g. "IP", "WIPO", "ABF").
    """
    text = text.strip()
    if not text:
        return text

    # Lowercase everything, then capitalise the first character.
    result = text[0].upper() + text[1:].lower() if len(text) > 1 else text.upper()

    # Restore common uppercase acronyms that should remain capitalised.
    _ACRONYMS = ["IP", "WIPO", "ABF", "ASBFEO", "TTIPA", "PBR", "QP", "ACCC"]
    for acronym in _ACRONYMS:
        result = re.sub(
            rf"\b{re.escape(acronym.lower())}\b",
            acronym,
            result,
            flags=re.IGNORECASE,
        )

    return result


def _parse_keywords(raw: str) -> list[str]:
    """Parse a comma-separated keywords string into a clean list.

    Handles values that may be wrapped in inner double quotes,
    e.g. ``"Intellectual property rights", "Letter of demand"``
    as well as simple unquoted comma-separated values.

    Each keyword is normalised to sentence case.
    """
    raw = raw.strip()
    if not raw or raw.lower() == "null":
        return []

    # Split on commas that separate keywords.
    parts = [p.strip().strip('"').strip() for p in raw.split(",")]

    # Recombine fragments that were split mid-keyword (unlikely given
    # the observed format, but defensive).  Filter empty strings.
    keywords = [_sentence_case(p) for p in parts if p]

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            deduped.append(kw)

    return deduped


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
                keywords=_parse_keywords(row.get("Keywords", "")),
            )
            url_key = rec.canonical_url.lower().rstrip("/")
            records[url_key] = rec

    print(f"[INFO] Loaded {len(records)} records from metatable.")
    return records

def _normalise_key(value: str) -> str:
    return (value or "").strip().lower().rstrip("/")


def _extract_udid_from_filename(md_path: Path) -> str:
    """
    Extract a leading UDID from filenames like:
      B1013 - Respond to an unjustified threat.md
      101-1 - How to avoid infringing others' intellectual property.md
    """
    stem = md_path.stem.strip()
    match = re.match(r"^([A-Za-z]?\d+(?:-\d+)?)\b", stem)
    return match.group(1).strip() if match else ""


def _find_meta_by_udid_and_url(
    metatable: dict[str, MetaRecord], udid: str, canonical_url: str
) -> MetaRecord | None:
    udid_key = _normalise_key(udid)
    url_key = _normalise_key(canonical_url)
    if not udid_key or not url_key:
        return None

    for rec in metatable.values():
        if _normalise_key(rec.udid) == udid_key and _normalise_key(rec.canonical_url) == url_key:
            return rec
    return None


def _find_meta_by_udid(
    metatable: dict[str, MetaRecord], udid: str
) -> MetaRecord | None:
    udid_key = _normalise_key(udid)
    if not udid_key:
        return None

    matches = [
        rec for rec in metatable.values()
        if _normalise_key(rec.udid) == udid_key
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _find_meta_by_title_and_overtitle(
    metatable: dict[str, MetaRecord], title: str, overtitle: str
) -> MetaRecord | None:
    title_key = _normalise_key(title)
    overtitle_key = _normalise_key(overtitle)
    if not title_key or not overtitle_key:
        return None

    matches = [
        rec for rec in metatable.values()
        if _normalise_key(rec.main_title) == title_key
        and _normalise_key(rec.overtitle) == overtitle_key
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def match_meta(
    parsed: ParsedMarkdown,
    metatable: dict[str, MetaRecord],
    md_path: Path,
) -> MetaRecord | None:
    """
    Match a parsed markdown document to its CSV metadata row.

    Match order:
      1. Exact pair match on UDID and canonical URL
      2. Exact canonical URL match
      3. Exact UDID match from filename, if filename starts with the UDID
      4. Exact pair match on title and overtitle
      5. Otherwise fail, log, and return None
    """
    page_url_key = _normalise_key(parsed.page_url)
    filename_udid = _extract_udid_from_filename(md_path)

    # Try to derive an overtitle from the first section heading when present.
    parsed_overtitle = ""
    if parsed.sections:
        parsed_overtitle = parsed.sections[0].heading.strip()

    # 1. Exact pair match on UDID and canonical URL
    if filename_udid and page_url_key:
        rec = _find_meta_by_udid_and_url(metatable, filename_udid, page_url_key)
        if rec:
            print(
                f"  [MATCH] {md_path.name} → UDID + canonical URL "
                f"({filename_udid}, {page_url_key})"
            )
            return rec

    # 2. Exact canonical URL match
    if page_url_key and page_url_key in metatable:
        rec = metatable[page_url_key]
        print(f"  [MATCH] {md_path.name} → canonical URL ({page_url_key})")
        return rec

    # 3. Exact UDID match from filename
    if filename_udid:
        rec = _find_meta_by_udid(metatable, filename_udid)
        if rec:
            print(f"  [MATCH] {md_path.name} → filename UDID ({filename_udid})")
            return rec

    # 4. Exact pair match on title and overtitle
    if parsed.title and parsed_overtitle:
        rec = _find_meta_by_title_and_overtitle(
            metatable,
            parsed.title,
            parsed_overtitle,
        )
        if rec:
            print(
                f"  [MATCH] {md_path.name} → title + overtitle "
                f"({parsed.title!r}, {parsed_overtitle!r})"
            )
            return rec

    # 5. Fail safely
    print(
        f"  [NO MATCH] {md_path.name} → could not deterministically match "
        f"(page_url={parsed.page_url!r}, filename_udid={filename_udid!r}, "
        f"title={parsed.title!r}, parsed_overtitle={parsed_overtitle!r})"
    )
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


def _link_name_from_url(
    url: str, anchor: str, url_title_map: dict[str, str] | None = None
) -> str:
    """Derive a human-readable name from a link's anchor text or URL path.

    For internal IP First Response links the canonical page title is looked
    up from *url_title_map* (built from the CSV metatable).  If the URL is
    not in the map the name is derived from the URL slug so that we never
    use contextual anchor text (e.g. "speak to an IP lawyer") as a page
    name.  External links continue to prefer anchor text.
    """
    IPFR_HOST = "ipfirstresponse.ipaustralia.gov.au"
    is_internal = IPFR_HOST in url

    # ── Internal IPFR links: CSV title → slug-derived name ──
    if is_internal:
        # 1. Try the CSV metatable lookup.
        if url_title_map:
            lookup_key = url.lower().rstrip("/")
            # Also try without query strings / fragments.
            lookup_key_clean = lookup_key.split("?")[0].split("#")[0].rstrip("/")
            title = url_title_map.get(lookup_key) or url_title_map.get(
                lookup_key_clean
            )
            if title:
                return title

        # 2. Derive from the URL slug (sentence-case).
        path = urlparse(url).path.rstrip("/")
        slug = path.split("/")[-1] if "/" in path else path
        words = slug.replace("-", " ").replace("_", " ").strip()
        if words:
            # Apply sentence-case then fix known abbreviations.
            name = words[0].upper() + words[1:]
            _ABBREVIATIONS = {"ip", "adr", "abn", "accc", "nda"}
            name = " ".join(
                w.upper() if w.lower() in _ABBREVIATIONS else w
                for w in name.split()
            )
            return name
        return url

    # ── External links: prefer anchor text, then slug ──
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
        "Any IP right"
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


def resolve_about_topics(ip_right_field: str) -> list[dict]:
    """
    Parse the CSV 'Relevant-ip-right' field into an array of Schema.org
    Thing objects, each with an optional Wikidata sameAs link.

    Input examples:
        '"Trade Mark", "Copyright"'
        '"Any IP right"'
        '"Patent"'
    """
    if not ip_right_field or not ip_right_field.strip():
        return [{"@type": "Thing", "name": "Intellectual property"}]

    # Strip outer quotes and split on comma-delimited quoted values.
    raw = ip_right_field.strip()
    # Extract individually quoted terms: "Trade Mark", "Copyright", etc.
    terms = re.findall(r'"([^"]+)"', raw)
    if not terms:
        # Fallback: treat the whole string as a single term.
        terms = [raw.strip('" ')]

    seen: set[str] = set()
    things: list[dict] = []
    for term in terms:
        term_clean = term.strip()
        if not term_clean:
            continue
        # Normalise for deduplication.
        key = term_clean.lower()
        if key in seen:
            continue
        seen.add(key)

        # Build the display name from the canonical map (sentence case).
        display_name = IP_TOPIC_DISPLAY_NAMES.get(key)
        if not display_name:
            # Fallback: sentence-case the first letter only.
            display_name = term_clean[0].upper() + term_clean[1:] if term_clean else term_clean

        # Special case: the catch-all IP topic gets a descriptive name and
        # the Wikidata link for "intellectual property right".
        if "any dispute" in key and "intellectual property" in key:
            thing: dict = {
                "@type": "Thing",
                "name": "All intellectual property (IP)",
                "description": "A topic which relates to all intellectual property",
                "sameAs": IP_TOPIC_MAP.get("intellectual property right", ""),
            }
            things.append(thing)
            continue

        thing: dict = {"@type": "Thing", "name": display_name}

        # Attach Wikidata sameAs if available.
        same_as_url = IP_TOPIC_MAP.get(key)
        if same_as_url:
            thing["sameAs"] = same_as_url

        things.append(thing)

    return things if things else [{"@type": "Thing", "name": "Intellectual property"}]


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

    # Repair mojibake before any further processing.
    text = _repair_mojibake(text)

    # Remove image links: [![alt](img)](url)
    text = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", text)
    # Remove standalone images: ![alt](url)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove empty-text links: [](url)
    text = re.sub(r"\[\s*\]\([^\)]+\)", "", text)
    # Convert markdown links [text](url) → text.
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Strip strikethrough markers: ~~content~~ → remove entirely.
    text = re.sub(r"~~.*?~~", "", text)
    # Strip bold / italic markers (handle multi-line with DOTALL).
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
    # Strip markdown line breaks (trailing backslash before newline).
    text = re.sub(r"\\\s*\n", "\n", text)
    # Strip link title references like [text](/path "title").
    text = re.sub(r'\s*"[^"]*"\s*', "", text)
    # Normalise list bullets from * to -.
    text = re.sub(r"^(\s*)\*\s+", r"\1- ", text, flags=re.MULTILINE)
    # Normalise space-only-indented list items (common in markdown
    # converted from CMS rich-text) to consistent '- ' prefixed items.
    # Only targets lines that are indented but lack a bullet or number
    # prefix, and that appear within a list context (i.e. near other
    # list items or after a blank line).
    _normalised_lines: list[str] = []
    for _line in text.split("\n"):
        _stripped = _line.lstrip()
        _indent = len(_line) - len(_stripped)
        if (
            _indent > 0
            and _stripped
            and not _stripped.startswith("-")
            and not re.match(r"^\d+\.\s", _stripped)
        ):
            _normalised_lines.append(" " + _stripped)
        else:
            _normalised_lines.append(_line)
    text = "\n".join(_normalised_lines)
    # Strip inline footnote reference markers at sentence boundaries.
    # Matches 1-2 digits following a sentence-ending period, where the
    # marker is followed by a space+uppercase letter (new sentence) or
    # end-of-string. This avoids stripping legitimate decimals like "2.5%".
    text = re.sub(r"(?<=\.)\d{1,2}(?=\s+[A-Z]|\s*$)", "", text)
    # Also strip markers that follow closing punctuation at end of text.
    text = re.sub(r"(?<=[\.\)\]\"\u2019])\d{1,2}\s*$", "", text)
    # Strip trailing footnote blocks (consecutive lines like "1. Act s 18.").
    text = re.sub(r"(?:\n\d+\.\s[^\n]+)+\s*$", "", text)
    # Normalise whitespace.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ──────────────────────────────────────────────────────────────────────
# 11. JSON-LD BUILDER
# ──────────────────────────────────────────────────────────────────────

def build_jsonld(
    parsed: ParsedMarkdown,
    meta: MetaRecord | None,
    metatable: dict[str, MetaRecord] | None = None,
) -> dict:
    """Assemble the full @graph JSON-LD document."""

    base_url = (parsed.page_url or (meta.canonical_url if meta else "")).rstrip("/")
    udid = meta.udid if meta else ""
    main_title = _repair_mojibake((meta.main_title if meta else "") or parsed.title)
    description = _repair_mojibake((meta.description if meta else "").strip('"').strip())
    # Fix 4: Use placeholder sentinel when description is empty;
    # replaced by _validate_and_repair_jsonld() after build.
    if not description:
        description = _PLACEHOLDER_SENTINEL
    pub_date = _parse_date(meta.publication_date) if meta else ""
    mod_date = _parse_date(meta.last_updated) if meta else ""
    disclaimer = _repair_mojibake((meta.additional_disclaimer if meta else "").strip())
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

    # ── Resolve "about" as an array of Thing objects (Fix 2 + 7) ──
    about_things = resolve_about_topics(meta.relevant_ip_right) if meta else [
        {"@type": "Thing", "name": "Intellectual property"}
    ]

    # ── Build the dynamic service-provider entity (if distinct from IP Australia) ──
    # IP Australia is always publisher and copyrightHolder (hardcoded).
    # The CSV "Provider" column drives only Service.provider / GovernmentService.serviceOperator.
    provider_entity: dict | None = None
    provider_id: str | None = None

    if provider_entry and provider_entry.name.lower().strip() not in ("self-help", "self help", ""):
        is_ip_australia = provider_entry.name.lower().strip() == "ip australia"
        if is_ip_australia:
            provider_id = IP_AUSTRALIA_ID
        else:
            provider_id = (
                f"{provider_entry.url.rstrip('/')}#organization"
                if provider_entry.url
                else f"{base_url}#provider-organization"
            )
            provider_entity = {
                "@type": provider_org_type,
                "@id": provider_id,
                "name": provider_entry.name,
            }
            if provider_entry.url:
                provider_entity["url"] = provider_entry.url
            if provider_entry.same_as:
                provider_entity["sameAs"] = provider_entry.same_as
            if provider_entry.alternate_name:
                provider_entity["alternateName"] = provider_entry.alternate_name
                
                    # ── Classify sections and build sub-entities ──
                    faq_questions: list[ParsedSection] = []
                    content_sections: list[ParsedSection] = []
                    howto_steps: list[ParsedSection] = []
                    article_body_text = parsed.intro_text  # fallback
                    # Track whether the article body originated from a named section that
                    # will also appear as a WebPageElement. If True, we skip populating
                    # "text" on Service entities to avoid duplication.
                    article_body_from_section = False
                
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
                                article_body_from_section = True
                            continue
                
                        if sec.classification == "faq":
                            faq_questions.append(sec)
                        elif sec.classification == "howto_step":
                            howto_steps.append(sec)
                        else:
                            content_sections.append(sec)
                
                    # ── Fix 3: If the page has no FAQ questions (only a "What is it?"
                    # section), override the archetype to Article to avoid duplicating the
                    # same body text in both "text" and a separate WebPageElement. ──
                    if not faq_questions and archetype_type != "Article":
                        # Check whether the only content sections are article-body sources
                        # (e.g. "What is it?", "Overview").
                        non_article_body_sections = [
                            s for s in content_sections
                            if not any(
                                hint in s.heading.lower().strip().rstrip("?")
                                for hint in ARTICLE_BODY_HEADINGS
                            )
                        ]
                        if not non_article_body_sections:
                            archetype_type = "Article"
                            # Remove article-body sections from content_sections since
                            # Article uses articleBody directly (no separate WebPageElement).
                            content_sections = [
                                s for s in content_sections
                                if not any(
                                    hint in s.heading.lower().strip().rstrip("?")
                                    for hint in ARTICLE_BODY_HEADINGS
                                )
                            ]
                
                    # ── Build section IDs ──
                    section_ids: list[str] = []
                    section_entities: list[dict] = []
                    for idx, sec in enumerate(content_sections, start=1):
                        slug = _slugify(sec.heading)
                        sec_id = f"{base_url}#section-{idx}-{slug}"
                        section_ids.append(sec_id)
                        # isPartOf must reference a CreativeWork. Article qualifies, but
                        # Service and GovernmentService do not, so sections fall back to
                        # the WebPage (which is always a CreativeWork).
                        is_part_of_id = (
                            f"{base_url}#{archetype_type.lower()}"
                            if archetype_type == "Article"
                            else f"{base_url}#webpage"
                        )
                        section_entities.append(
                            {
                                "@type": "WebPageElement",
                                "@id": sec_id,
                                "headline": sec.heading,
                                "text": _format_body_text(sec.body),
                                "position": idx,
                                "isPartOf": {"@id": is_part_of_id},
                            }
                        )
                
                    # ── Build FAQ entity ──
                    faq_id = f"{base_url}#faq"
                    faq_entity = None
                    if faq_questions:
                        q_entities = []
                        for qi, q in enumerate(faq_questions, start=1):
                            # Use a single fragment with dash separator (RFC 3986 compliance).
                            q_id = f"{base_url}#faq-q{qi}"
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
                    IPFR_HOST = "ipfirstresponse.ipaustralia.gov.au"
                    related_link_urls: list[str] = []       # plain URL strings for relatedLink
                    internal_page_entities: list[dict] = []  # full WebPage stubs for @graph
                    internal_page_refs: list[dict] = []      # @id refs for WebPage.mentions
                    seen_link_urls: set[str] = set()
                
                    # Build a URL → MetaRecord lookup from the full metatable so that
                    # internal IPFR links can be enriched with title and description.
                    url_meta_map: dict[str, MetaRecord] = {}
                    url_title_map: dict[str, str] = {}
                    if metatable:
                        for rec in metatable.values():
                            if rec.canonical_url:
                                key = rec.canonical_url.lower().rstrip("/")
                                url_meta_map[key] = rec
                                if rec.main_title:
                                    url_title_map[key] = rec.main_title
                
                    # Filter out noisy links (feedback forms, email, images, CMS nodes).
                    noise_patterns = ["qualtrics.com", "mailto:", "/sites/default/files/", "/node/"]
                    for url, anchor in parsed.links:
                        if any(p in url for p in noise_patterns):
                            continue
                        # Strip tracking parameters for deduplication.
                        url = _strip_tracking_params(url)
                        # Skip self-referencing URLs (the page linking to itself).
                        if base_url and url.rstrip("/") == base_url.rstrip("/"):
                            continue
                        # Normalise for deduplication.
                        dedup_key = url.rstrip("/").lower()
                        if dedup_key not in seen_link_urls:
                            seen_link_urls.add(dedup_key)
                            clean_url = url.rstrip("/")
                
                            # relatedLink always gets a plain URL string (both
                            # internal and external) per Schema.org spec.
                            related_link_urls.append(clean_url)
                
                            # For internal IPFR links, also build a rich WebPage
                            # entity for the @graph and a @id ref for mentions.
                            if IPFR_HOST in url:
                                page_id = f"{clean_url}#webpage"
                                internal_page_refs.append({"@id": page_id})
                
                                # Strip query strings / fragments for metatable lookup.
                                lookup_key = dedup_key.split("?")[0].split("#")[0].rstrip("/")
                                linked_meta = url_meta_map.get(lookup_key)
                
                                if linked_meta:
                                    page_entity: dict = {
                                        "@type": "WebPage",
                                        "@id": page_id,
                                        "url": clean_url,
                                        "name": f"{linked_meta.main_title} - {WEBSITE_NAME}",
                                    }
                                    desc = linked_meta.description.strip().strip('"')
                                    if desc and desc.lower() != "null":
                                        page_entity["description"] = desc
                                    if linked_meta.udid:
                                        page_entity["identifier"] = linked_meta.udid
                                    page_entity["isPartOf"] = {"@id": WEBSITE_ID}
                                    internal_page_entities.append(page_entity)
                                else:
                                    # No CSV match; build a minimal stub from the URL.
                                    slug_name = _link_name_from_url(
                                        clean_url, anchor, url_title_map
                                    )
                                    internal_page_entities.append(
                                        {
                                            "@type": "WebPage",
                                            "@id": page_id,
                                            "url": clean_url,
                                            "name": f"{slug_name} - {WEBSITE_NAME}",
                                            "isPartOf": {"@id": WEBSITE_ID},
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
                    disclaimer_section_id: str | None = None
                    if disclaimer and disclaimer.lower() != "null":
                        disclaimer_slug = "disclaimer"
                        disclaimer_id = f"{base_url}#section-{len(content_sections) + 1}-{disclaimer_slug}"
                        disclaimer_section_id = disclaimer_id
                        # isPartOf target: Article (CreativeWork) or WebPage for Service types.
                        disclaimer_parent_id = (
                            f"{base_url}#{archetype_type.lower()}"
                            if archetype_type == "Article"
                            else f"{base_url}#webpage"
                        )
                        disclaimer_entity = {
                            "@type": "WebPageElement",
                            "@id": disclaimer_id,
                            "headline": "Disclaimer",
                            "text": disclaimer,
                            "position": len(content_sections) + 1,
                            "isPartOf": {"@id": disclaimer_parent_id},
                        }
                        section_entities.append(disclaimer_entity)
                        has_part_refs.append({"@id": disclaimer_id})
                
                    # ── Standard disclaimer is represented via usageInfo on the WebPage ──
                    # (No separate WebPageElement is created; this avoids triple-redundancy.)
                
                    # ── Build the WebPage entity ──
                    # Fix 3: Always use the H1 heading from markdown (parsed.title) as the
                    # canonical headline. CSV main_title is a fallback only.
                    h1_title = parsed.title if (parsed.title and parsed.title != "Untitled") else main_title
                    webpage_entity: dict = {
                        "@type": "WebPage",
                        "@id": f"{base_url}#webpage",
                        "url": base_url,
                        "name": f"{h1_title} - {WEBSITE_NAME}",
                        "description": description,
                        "identifier": udid,
                        "about": about_things,
                        "inLanguage": DEFAULT_LANGUAGE,
                        "license": DEFAULT_LICENCE,
                        "audience": {
                            "@type": "BusinessAudience",
                            "audienceType": "Small and medium businesses",
                            "geographicArea": {"@type": "Country", "name": "Australia"},
                            "alternateName": [
                                "Startups",
                                "Entrepreneurs",
                                "SME",
                                "Startup",
                                "Small to Medium Enterprise",
                                "Sole Trader",
                                "Australian Small Business Owners"
                            ],
                        },
                        # Fix 5: Always include the standard hardcoded disclaimer.
                        "usageInfo": STANDARD_DISCLAIMER,
                        # Fix 1: Publisher and copyrightHolder are always IP Australia.
                        "publisher": {"@id": IP_AUSTRALIA_ID},
                        "isPartOf": {"@id": WEBSITE_ID},
                        "mainEntity": {"@id": f"{base_url}#{archetype_type.lower()}"},
                    }
                    if pub_date:
                        webpage_entity["datePublished"] = pub_date
                    if mod_date:
                        webpage_entity["dateModified"] = mod_date
                
                    # ── Add keywords (from CSV Keywords column) ──
                    if meta and meta.keywords:
                        webpage_entity["keywords"] = meta.keywords
                    if copyright_year:
                        webpage_entity["copyrightYear"] = copyright_year
                        webpage_entity["copyrightHolder"] = {"@id": IP_AUSTRALIA_ID}
                    webpage_entity["creditText"] = "Source: IP First Response initiative led by IP Australia"
                    # For Service / GovernmentService types, "text" is a CreativeWork
                    # property and is not valid on the main entity. Preserve any intro
                    # body text (not already in a named section) on the WebPage instead.
                    if archetype_type != "Article" and article_body_text and not article_body_from_section:
                        webpage_entity["text"] = article_body_text
                    if has_part_refs:
                        webpage_entity["hasPart"] = has_part_refs
                
                    # ── Build the main content entity (Article / GovernmentService / Service) ──
                    # Fix 3: Use H1 from markdown as the canonical title.
                    # Fix 4: Use "name" for Service types; "headline" only for Article.
                    #
                    # Service and GovernmentService inherit from Thing > Intangible > Service,
                    # NOT from CreativeWork. Only properties valid on the target type are
                    # included; CreativeWork-specific properties (inLanguage, license,
                    # publisher, author, text) are confined to Article and the WebPage.
                    main_entity: dict = {
                        "@type": archetype_type,
                        "@id": f"{base_url}#{archetype_type.lower()}",
                        "description": description,
                        "mainEntityOfPage": {"@id": f"{base_url}#webpage"},
                    }
                
                    # CreativeWork-only properties (valid on Article, not on Service types).
                    if archetype_type == "Article":
                        main_entity["inLanguage"] = DEFAULT_LANGUAGE
                        main_entity["license"] = DEFAULT_LICENCE
                        main_entity["publisher"] = {"@id": IP_AUSTRALIA_ID}
                        main_entity["author"] = {"@id": IP_AUSTRALIA_ID}
                
                    # Fix 4: Articles use "headline"; Service types use "name".
                    if archetype_type == "Article":
                        main_entity["headline"] = h1_title
                    else:
                        main_entity["name"] = h1_title
                
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
                        if provider_id:
                            main_entity["serviceOperator"] = {"@id": provider_id}
                            main_entity["provider"] = {"@id": provider_id}
                
                    # Service-specific fields (non-government / commercial).
                    if archetype_type == "Service":
                        main_entity["serviceType"] = meta.archetype if meta else "Service"
                        if provider_id:
                            main_entity["provider"] = {"@id": provider_id}
                
                    # HowTo reference (if applicable).
                    # hasPart is only valid on CreativeWork subtypes (e.g. Article), not on
                    # Service or GovernmentService. For non-Article archetypes, the WebPage
                    # (which IS a CreativeWork) already carries the hasPart references to
                    # sections, FAQ and disclaimer; we add HowTo there too.
                    if archetype_type == "Article":
                        article_parts: list[dict] = []
                        if howto_entity:
                            article_parts.append({"@id": f"{base_url}#howto"})
                        for sid in section_ids:
                            article_parts.append({"@id": sid})
                        if faq_entity:
                            article_parts.append({"@id": faq_id})
                        if disclaimer_section_id:
                            article_parts.append({"@id": disclaimer_section_id})
                        if article_parts:
                            main_entity["hasPart"] = article_parts
                    else:
                        # For Service / GovernmentService, add HowTo to the WebPage's
                        # hasPart (sections and FAQ are already there).
                        if howto_entity:
                            has_part_refs.append({"@id": f"{base_url}#howto"})
                
                    # "mentions" is a CreativeWork property, so it belongs on the Article
                    # or the WebPage, not on Service / GovernmentService.
                    #
                    # Legislation citation_refs attach to the Article when the archetype
                    # is Article, otherwise they fall through to the WebPage.
                    #
                    # Internal IPFR page references always attach to the WebPage so that
                    # AI agents traversing the graph from the WebPage can discover
                    # related pages within the site.  These are full WebPage objects
                    # (with @id, url, name, description) emitted into the @graph, and
                    # referenced here by @id.
                    webpage_mentions: list[dict] = list(internal_page_refs)
                    if citation_refs:
                        if archetype_type == "Article":
                            main_entity["mentions"] = citation_refs
                        else:
                            webpage_mentions.extend(citation_refs)
                    if webpage_mentions:
                        webpage_entity["mentions"] = webpage_mentions
                
                    # relatedLink: strictly plain URL strings (Schema.org expects URL
                    # values).  Both internal and external links appear here as strings.
                    if related_link_urls:
                        webpage_entity["relatedLink"] = related_link_urls
                
                    # ── Assemble the @graph ──
                    graph: list[dict] = []
                
                    # 1. IP Australia (always present as publisher & copyrightHolder).
                    graph.append(dict(IP_AUSTRALIA_ENTITY))
                
                    # 1b. Dynamic service provider (if distinct from IP Australia).
                    if provider_entity:
                        graph.append(provider_entity)
                
                    # 2. WebSite (publisher is always IP Australia).
                    graph.append(
                        {
                            "@type": "WebSite",
                            "@id": WEBSITE_ID,
                            "name": WEBSITE_NAME,
                            "url": WEBSITE_URL,
                            "publisher": {"@id": IP_AUSTRALIA_ID},
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
                
                    # 9. Internal IPFR page stubs (rich WebPage entities for
                    #    graph-traversable cross-page links via WebPage.mentions).
                    graph.extend(internal_page_entities)
                
                    return {"@context": SCHEMA_CONTEXT, "@graph": graph}
                

# ──────────────────────────────────────────────────────────────────────
# 11b. POST-BUILD VALIDATION
# ──────────────────────────────────────────────────────────────────────

_PLACEHOLDER_SENTINEL = "xXx_PLACEHOLDER_xXx"


def _validate_and_repair_jsonld(jsonld: dict) -> dict:
    """Post-build validation pass.

    Currently handles:
      - Replacing placeholder descriptions with a generated summary
        derived from the first 160 characters of the articleBody, text,
        or longest WebPageElement text in the main content entity.
    """
    graph = jsonld.get("@graph", [])

    # Locate the main content entity (Article, GovernmentService, or Service)
    # and extract its body text for summary generation.
    body_text = ""
    for entity in graph:
        etype = entity.get("@type", "")
        if etype in ("Article", "GovernmentService", "Service"):
            body_text = entity.get("articleBody", "") or entity.get("text", "")
            break

    # Fallback: use the longest WebPageElement text (e.g. "What is it?" section).
    if not body_text:
        for entity in graph:
            if entity.get("@type") == "WebPageElement":
                candidate = entity.get("text", "")
                if len(candidate) > len(body_text):
                    body_text = candidate

    # Generate a summary: first 160 characters, trimmed to the last whole word.
    generated_summary = ""
    if body_text:
        truncated = body_text[:160].strip()
        # Trim to the last complete word boundary.
        if len(body_text) > 160:
            last_space = truncated.rfind(" ")
            if last_space > 80:
                truncated = truncated[:last_space]
            generated_summary = truncated.rstrip(".,;:- ") + "..."
        else:
            generated_summary = truncated

    # Walk the graph and replace any placeholder descriptions.
    for entity in graph:
        if entity.get("description") == _PLACEHOLDER_SENTINEL:
            if generated_summary:
                entity["description"] = generated_summary
                print(f"  [REPAIR] Generated description for {entity.get('@type', '?')}: "
                      f"\"{generated_summary[:60]}...\"")
            else:
                print(f"  [WARN] No body text available to generate description for "
                      f"{entity.get('@type', '?')}; placeholder remains.")

    return jsonld


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
    meta = match_meta(parsed, metatable, md_path)

    if not meta:
        print(f"  [SKIP] {md_path.name} → no deterministic CSV match; JSON not generated.")
        return None

    print(f"  [OK]  {md_path.name} → matched UDID: {meta.udid}")

    jsonld = build_jsonld(parsed, meta, metatable)
    jsonld = _validate_and_repair_jsonld(jsonld)

    out_name = f"{meta.udid}_{_slugify(meta.main_title)}.json"
    out_path = output_dir / out_name
    out_path.write_text(
        json.dumps(jsonld, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
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

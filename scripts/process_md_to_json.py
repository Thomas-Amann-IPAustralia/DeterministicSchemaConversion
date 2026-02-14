#!/usr/bin/env python3
"""
Markdown to JSON-LD Converter
Converts markdown files to structured JSON-LD schema.org format with metadata enrichment.
Usage:
    python process_md_to_json.py [--csv metadata.csv] [--md-dir IPFR-Webpages] [--output json_output]
"""


import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import csv


# --- CONFIGURATION ---
CSV_PATH = 'metatable-Content.csv'
MD_DIR = 'IPFR-Webpages'
OUTPUT_DIR = 'json_output'


@dataclass
class MetadataEnrichment:
    """Enrichment data from CSV metadata file"""
    identifier: str
    overtitle: str = ""
    main_title: str = ""
    description: str = ""
    canonical_url: str = ""
    entry_point: str = ""
    relevant_ip_right: str = ""
    estimate_cost: str = ""
    estimated_effort: str = ""
    resolution_rate: str = ""
    archetype: str = ""
    provider: str = ""
    publication_date: str = ""
    last_updated: str = ""
    additional_disclaimer: str = ""




@dataclass
class Section:
    """Represents a content section"""
    heading: str
    content: str
    level: int
    section_id: str




@dataclass
class FAQ:
    """Represents a frequently asked question"""
    question: str
    answer: str




class MarkdownParser:
    """Parse markdown content into structured components"""
    
    # Question indicators for FAQ detection
    FAQ_INDICATORS = [
        "what is", "what are", "who can", "who's", "how much", "how to",
        "why should", "when should", "where can", "do i need"
    ]
    
    # Headings to exclude from FAQ detection (structural elements)
    FAQ_EXCLUSIONS = [
        "what is it?",
        "see also",
        "want to give us feedback?",
        "feedback",
        "related content",
        "references"
    ]
    
    def __init__(self, content: str):
        self.content = content
        self.lines = content.split('\n')
        self.page_url = self._extract_page_url()
        
    def _extract_page_url(self) -> str:
        """Extract PageURL from the first line if present"""
        first_line = self.lines[0] if self.lines else ""
        url_match = re.search(r'PageURL:\s*"?\[?([^\]"\n]+)', first_line)
        return url_match.group(1) if url_match else ""
    
    def extract_main_title(self) -> str:
        """Extract the main H1 title (single #)"""
        for line in self.lines:
            if re.match(r'^#\s+(?!#)', line):
                return line.strip('#').strip()
        return ""
    
    def extract_overtitle(self) -> str:
        """Extract overtitle (H2 before main title)"""
        for line in self.lines:
            if re.match(r'^#{2}\s+(?!#)', line):
                return line.strip('#').strip()
        return ""
    
    def extract_article_body(self) -> str:
        """
        Extract main article body content.
        Focuses on the 'What is it?' section or first substantial content section.
        Falls back to all content before first FAQ-like section if no 'What is it?' found.
        """
        lines_to_process = []
        in_what_is_section = False
        found_what_is = False
        main_content_started = False
        
        for i, line in enumerate(self.lines):
            # Skip PageURL line
            if i == 0 and line.startswith('PageURL:'):
                continue
            
            # Skip initial disclaimer/italic text
            if line.strip().startswith('*This IP First Response website'):
                continue
            
            # Check for "What is it?" section
            if re.search(r'###?\s+What is it\?', line, re.IGNORECASE):
                in_what_is_section = True
                found_what_is = True
                continue
            
            # Stop at the next major section after "What is it?"
            if found_what_is and in_what_is_section and re.match(r'###\s+', line):
                break
            
            # If we're in "What is it?" section, collect content
            if in_what_is_section:
                # Skip image/button references
                if not (line.strip().startswith('![') or line.strip().startswith('[![')):
                    lines_to_process.append(line)
            
            # If no "What is it?" section found, collect main content
            elif not found_what_is:
                # Start collecting after H1 heading
                if re.match(r'^#\s+(?!#)', line):
                    main_content_started = True
                    continue
                
                # Stop at first FAQ-like section or "See also"
                if main_content_started and re.match(r'###\s+', line):
                    heading = line.strip('#').strip().lower()
                    # Stop at structural sections
                    if heading in ['see also', 'want to give us feedback?'] or '?' in line:
                        break
                
                # Collect content after H1
                if main_content_started:
                    # Skip images and disclaimers
                    if not (line.strip().startswith('![') or 
                           line.strip().startswith('[![') or
                           line.strip().startswith('*This IP First Response')):
                        lines_to_process.append(line)
        
        # Clean and format the text
        body = '\n'.join(lines_to_process).strip()
        body = re.sub(r'\*\*([^*]+)\*\*', r'\1', body)  # Remove bold
        body = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', body)  # Clean links
        body = re.sub(r'\n{3,}', '\n\n', body)  # Normalize spacing
        
        return body
    
    def extract_sections(self) -> List[Section]:
        """Extract content sections (H3 headings)"""
        sections = []
        current_section = None
        current_content = []
        
        for line in self.lines:
            h3_match = re.match(r'^###\s+(.+)$', line)
            
            if h3_match:
                # Save previous section
                if current_section:
                    sections.append(Section(
                        heading=current_section,
                        content='\n'.join(current_content).strip(),
                        level=3,
                        section_id=self._create_section_id(current_section)
                    ))
                
                current_section = h3_match.group(1).strip()
                current_content = []
            elif current_section:
                current_content.append(line)
        
        # Save last section
        if current_section:
            sections.append(Section(
                heading=current_section,
                content='\n'.join(current_content).strip(),
                level=3,
                section_id=self._create_section_id(current_section)
            ))
        
        return sections
    
    def extract_faqs(self, sections: List[Section]) -> List[FAQ]:
        """
        Extract FAQs from sections based on formatting rules.
        Any H3 heading ending with '?' is treated as a question,
        excluding structural headings like "What is it?" or "See also".
        """
        faqs = []
        
        for section in sections:
            heading_lower = section.heading.lower()
            
            # Skip excluded structural headings
            if heading_lower in self.FAQ_EXCLUSIONS:
                continue
            
            # Check if heading is a question
            is_question = section.heading.endswith('?')
            
            # Also check if heading contains common question patterns
            if not is_question:
                is_question = any(
                    indicator in heading_lower 
                    for indicator in self.FAQ_INDICATORS
                )
            
            if is_question and section.content:
                # Clean the answer content
                answer = self._clean_faq_answer(section.content)
                faqs.append(FAQ(
                    question=section.heading,
                    answer=answer
                ))
        
        return faqs
    
    def _clean_faq_answer(self, content: str) -> str:
        """Clean and format FAQ answer text"""
        # Remove image references
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'\[!\[.*?\]\(.*?\)\]\(.*?\)', '', content)
        
        # Remove markdown formatting
        content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)  # Bold
        content = re.sub(r'\*([^*]+)\*', r'\1', content)  # Italic
        
        # Clean up links but keep text
        content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
        
        # Clean whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = content.strip()
        
        return content
    
    def _create_section_id(self, heading: str) -> str:
        """Create a URL-friendly section ID from heading"""
        section_id = heading.lower()
        section_id = re.sub(r'[^\w\s-]', '', section_id)
        section_id = re.sub(r'[-\s]+', '-', section_id)
        return f"section-{section_id}"
    
    def extract_links(self) -> List[str]:
        """Extract unique URLs from markdown content"""
        urls = set()
        
        # Pattern for markdown links
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        
        for match in re.finditer(link_pattern, self.content):
            url = match.group(2)
            # Filter out image URLs and relative paths
            if url.startswith('http') and not url.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                urls.add(url)
        
        return sorted(list(urls))




class MetadataLoader:
    """Load and manage metadata from CSV file"""
    
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        self.metadata_cache: Dict[str, MetadataEnrichment] = {}
        self._load_metadata()
    
    def _load_metadata(self):
        """Load metadata from CSV into cache"""
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    identifier = row.get('UDID', '').strip()
                    if identifier:
                        # Note: CSV has typo "Archectype " with space
                        archetype_key = 'Archectype ' if 'Archectype ' in row else 'Archetype'
                        
                        self.metadata_cache[identifier] = MetadataEnrichment(
                            identifier=identifier,
                            overtitle=row.get('Overtitle', '').strip(),
                            main_title=row.get('Main-title', '').strip(),
                            description=row.get('Description', '').strip(),
                            canonical_url=row.get('Canonical-url', '').strip(),
                            entry_point=row.get('Entry-point', '').strip(),
                            relevant_ip_right=row.get('Relevant-ip-right', '').strip(),
                            estimate_cost=row.get('Estimate-cost', '').strip(),
                            estimated_effort=row.get('Estimated-effort', '').strip(),
                            resolution_rate=row.get('Resolution-rate', '').strip(),
                            archetype=row.get(archetype_key, '').strip(),
                            provider=row.get('Provider', '').strip(),
                            publication_date=row.get('Publication-date', '').strip(),
                            last_updated=row.get('Last-updated', '').strip(),
                            additional_disclaimer=row.get('Additional-disclaimer', '').strip()
                        )
        except Exception as e:
            print(f"Warning: Could not load metadata from {self.csv_path}: {e}")
    
    def get_metadata(self, identifier: str) -> Optional[MetadataEnrichment]:
        """Get metadata for a specific identifier"""
        return self.metadata_cache.get(identifier)
    
    def find_metadata_by_url(self, page_url: str) -> Optional[MetadataEnrichment]:
        """Find metadata by matching the canonical URL against a PageURL"""
        if not page_url:
            return None
        # Normalise trailing slashes for comparison
        normalised = page_url.rstrip('/')
        for meta in self.metadata_cache.values():
            if meta.canonical_url.rstrip('/') == normalised:
                return meta
        return None




class JSONLDBuilder:
    """Build JSON-LD structure from parsed markdown and metadata"""
    
    BASE_ORGANIZATION_ID = "https://www.ipaustralia.gov.au/#organization"
    BASE_WEBSITE_ID = "https://ipfirstresponse.ipaustralia.gov.au/#website"
    LANGUAGE = "en-AU"
    LICENSE = "https://creativecommons.org/licenses/by/4.0/"
    
    # Known government organizations
    GOVERNMENT_ORGS = {
        "IP Australia": {
            "name": "IP Australia",
            "url": "https://www.ipaustralia.gov.au"
        },
        "ACCC": {
            "name": "Australian Competition and Consumer Commission",
            "url": "https://www.accc.gov.au"
        },
        "ASCS": {
            "name": "Australian Signals and Communications Security",
            "url": "https://www.cyber.gov.au"
        },
        "AFP": {
            "name": "Australian Federal Police",
            "url": "https://www.afp.gov.au"
        },
        "Australian Border Force": {
            "name": "Australian Border Force",
            "url": "https://www.abf.gov.au"
        },
        "TGA": {
            "name": "Therapeutic Goods Administration",
            "url": "https://www.tga.gov.au"
        },
        "Scamwatch": {
            "name": "Scamwatch",
            "url": "https://www.scamwatch.gov.au"
        },
        "Law Enforcement": {
            "name": "Law Enforcement",
            "url": "https://www.afp.gov.au"
        },
        "Australian Small Business and Family Enterprise Ombudsman": {
            "name": "Australian Small Business and Family Enterprise Ombudsman",
            "url": "https://www.asbfeo.gov.au"
        }
    }
    
    # Known NGOs / non-government third-party authorities
    NGOS = {
        "Copyright Council": {
            "name": "Australian Copyright Council",
            "url": "https://www.copyright.org.au"
        },
        "auDA": {
            "name": "auDA (au Domain Administration)",
            "url": "https://www.auda.org.au"
        },
        "World Intellectual Property Office": {
            "name": "World Intellectual Property Organization",
            "url": "https://www.wipo.int"
        },
        "World Intellectual Property Office Arbitration and Mediation Center": {
            "name": "WIPO Arbitration and Mediation Center",
            "url": "https://www.wipo.int/amc/en/"
        },
        "Court": {
            "name": "Federal Court of Australia",
            "url": "https://www.fedcourt.gov.au"
        },
        "Trans-Tasman IP Attorneys Board": {
            "name": "Trans-Tasman IP Attorneys Board",
            "url": "https://www.ttipattorney.gov.au"
        }
    }
    
    def __init__(self, parser: MarkdownParser, metadata: Optional[MetadataEnrichment] = None):
        self.parser = parser
        self.metadata = metadata
        self.page_url = parser.page_url
    
    # ------------------------------------------------------------------
    # Public build method
    # ------------------------------------------------------------------

    def build(self) -> Dict:
        """Build complete JSON-LD structure"""
        graph = []
        
        # Determine entity type and build appropriate provider organization
        entity_type, provider_type = self._determine_entity_type()
        
        # Add provider organization if needed (for services)
        if entity_type in ["GovernmentService", "Service"]:
            provider_orgs = self._build_provider_organizations(provider_type)
            graph.extend(provider_orgs)
        else:
            # For articles, add the base organization
            graph.append(self._build_organization())
        
        # Add website
        graph.append(self._build_website())
        
        # Add webpage
        sections = self.parser.extract_sections()
        faqs = self.parser.extract_faqs(sections)
        graph.append(self._build_webpage(entity_type, sections, faqs))
        
        # Add main entity (Article, GovernmentService, or Service)
        main_entity = self._build_main_entity(entity_type, provider_type, sections)
        graph.append(main_entity)
        
        # Add sections as WebPageElements
        for section in sections:
            graph.append(self._build_section(section))
        
        # Add FAQ page if FAQs exist
        if faqs:
            graph.append(self._build_faq_page(faqs))
        
        return {
            "@context": "https://schema.org",
            "@graph": graph
        }
    
    # ------------------------------------------------------------------
    # Entity type determination
    # ------------------------------------------------------------------

    def _determine_entity_type(self) -> Tuple[str, str]:
        """
        Determine the entity type based on metadata archetype.
        Returns: (entity_type, provider_type)
        """
        if not self.metadata or not self.metadata.archetype:
            return ("Article", "None")
        
        archetype = self.metadata.archetype.lower()
        provider = self.metadata.provider.strip() if self.metadata.provider else ""
        
        if "government service" in archetype:
            return ("GovernmentService", "GovernmentOrganization")
        
        if "commercial third party service" in archetype or "third party service" in archetype:
            if any(ngo_name.lower() in provider.lower() for ngo_name in self.NGOS.keys()):
                return ("Service", "NGO")
            else:
                return ("Service", "Organization")
        
        if "non-government third-party authority" in archetype:
            if any(ngo_name.lower() in provider.lower() for ngo_name in self.NGOS.keys()):
                return ("Service", "NGO")
            else:
                return ("Service", "Organization")
        
        # Default to Article for self-help strategies and other types
        return ("Article", "None")
    
    # ------------------------------------------------------------------
    # Organization builders
    # ------------------------------------------------------------------

    def _build_provider_organizations(self, provider_type: str) -> List[Dict]:
        """Build provider organization entities based on provider type"""
        if not self.metadata or not self.metadata.provider:
            return [self._build_organization()]
        
        provider_str = self.metadata.provider.strip()
        providers = []
        
        if provider_type == "GovernmentOrganization":
            provider_names = [p.strip() for p in provider_str.split(',')]
            
            for provider_name in provider_names:
                if provider_name in self.GOVERNMENT_ORGS:
                    org_info = self.GOVERNMENT_ORGS[provider_name]
                    org_id = f"{org_info['url']}/#organization"
                    providers.append({
                        "@type": "GovernmentOrganization",
                        "@id": org_id,
                        "name": org_info["name"],
                        "url": org_info["url"],
                        "sameAs": [org_info["url"]]
                    })
                else:
                    slug = provider_name.lower().replace(' ', '-')
                    org_id = f"https://www.example.gov.au/{slug}/#organization"
                    providers.append({
                        "@type": "GovernmentOrganization",
                        "@id": org_id,
                        "name": provider_name,
                    })
        
        elif provider_type == "NGO":
            for ngo_name, ngo_info in self.NGOS.items():
                if ngo_name.lower() in provider_str.lower():
                    org_id = f"{ngo_info['url']}/#organization"
                    providers.append({
                        "@type": "NGO",
                        "@id": org_id,
                        "name": ngo_info["name"],
                        "url": ngo_info["url"],
                        "sameAs": [ngo_info["url"]]
                    })
                    break
            
            if not providers:
                slug = provider_str.lower().replace(' ', '-')
                org_id = f"https://www.example.org/{slug}/#organization"
                providers.append({
                    "@type": "NGO",
                    "@id": org_id,
                    "name": provider_str,
                })
        
        elif provider_type == "Organization":
            slug = provider_str.lower().replace(' ', '-')
            org_id = f"https://www.example.com/{slug}/#organization"
            providers.append({
                "@type": "Organization",
                "@id": org_id,
                "name": provider_str,
            })
        
        if not providers:
            providers.append(self._build_organization())
        
        return providers
    
    def _build_organization(self) -> Dict:
        """Build the base organization entity (IP Australia)"""
        return {
            "@type": "GovernmentOrganization",
            "@id": self.BASE_ORGANIZATION_ID,
            "name": "IP Australia",
            "url": "https://www.ipaustralia.gov.au",
            "sameAs": [
                "https://www.ipaustralia.gov.au"
            ]
        }
    
    # ------------------------------------------------------------------
    # WebSite entity
    # ------------------------------------------------------------------

    def _build_website(self) -> Dict:
        """Build the WebSite entity (fixed values for IP First Response)"""
        return {
            "@type": "WebSite",
            "@id": self.BASE_WEBSITE_ID,
            "name": "IP First Response",
            "url": "https://ipfirstresponse.ipaustralia.gov.au/",
            "publisher": {
                "@id": self.BASE_ORGANIZATION_ID
            },
            "inLanguage": self.LANGUAGE,
            "license": self.LICENSE
        }
    
    # ------------------------------------------------------------------
    # WebPage entity
    # ------------------------------------------------------------------

    def _build_webpage(self, entity_type: str, sections: List[Section], faqs: List[FAQ]) -> Dict:
        """Build the WebPage entity"""
        title = self.parser.extract_main_title()
        headline = f"{title} - IP First Response" if title else "IP First Response"
        
        # Determine alternativeHeadline: CSV overtitle first, then markdown H2
        alt_headline = ""
        if self.metadata and self.metadata.overtitle:
            alt_headline = self.metadata.overtitle
        else:
            md_overtitle = self.parser.extract_overtitle()
            if md_overtitle:
                alt_headline = md_overtitle
        
        webpage = {
            "@type": "WebPage",
            "@id": f"{self.page_url}#webpage" if self.page_url else "#webpage",
            "url": self.page_url or "",
            "headline": headline,
            "description": self.metadata.description if self.metadata else "",
            "inLanguage": self.LANGUAGE,
            "isPartOf": {
                "@id": self.BASE_WEBSITE_ID
            },
            "publisher": {
                "@id": self.BASE_ORGANIZATION_ID
            },
            "copyrightYear": datetime.now().year,
            "copyrightHolder": {
                "@id": self.BASE_ORGANIZATION_ID
            },
            "creditText": "IP First Response initiative led by IP Australia",
            "license": self.LICENSE,
            "audience": {
                "@type": "BusinessAudience",
                "audienceType": "Small and medium businesses, startups, and individuals"
            },
            "usageInfo": (
                "This information is general in nature and should not be relied upon "
                "as legal advice. You should seek independent professional advice "
                "relevant to your specific circumstances."
            )
        }
        
        if alt_headline:
            webpage["alternativeHeadline"] = alt_headline
        
        # Add identifier from CSV
        if self.metadata and self.metadata.identifier:
            webpage["identifier"] = self.metadata.identifier
        
        # Add dates
        pub_date = self._convert_date(self.metadata.publication_date if self.metadata else "")
        mod_date = self._convert_date(self.metadata.last_updated if self.metadata else "")
        if pub_date:
            webpage["datePublished"] = pub_date
        if mod_date:
            webpage["dateModified"] = mod_date
        
        # Add mainEntity reference
        if self.page_url:
            webpage["mainEntity"] = {
                "@id": f"{self.page_url}#article"
            }
        
        # Build hasPart references to all child entities
        has_part = []
        if self.page_url:
            has_part.append({"@id": f"{self.page_url}#article"})
        for section in sections:
            has_part.append({"@id": f"{self.page_url}#{section.section_id}"})
        if faqs:
            has_part.append({"@id": f"{self.page_url}#faq"})
        if has_part:
            webpage["hasPart"] = has_part
        
        return webpage
    
    # ------------------------------------------------------------------
    # Main entity builders (Article / GovernmentService / Service)
    # ------------------------------------------------------------------

    def _build_main_entity(self, entity_type: str, provider_type: str, sections: List[Section]) -> Dict:
        """Build the main content entity based on type"""
        if entity_type == "Article":
            return self._build_article(sections)
        elif entity_type == "GovernmentService":
            return self._build_government_service(sections)
        else:
            return self._build_service(sections, provider_type)
    
    def _build_article(self, sections: List[Section]) -> Dict:
        """Build an Article entity (for Self-Help Strategy archetype)"""
        title = self.parser.extract_main_title()
        article_body = self.parser.extract_article_body()
        related_links = self.parser.extract_links()
        
        article = {
            "@type": "Article",
            "@id": f"{self.page_url}#article" if self.page_url else "#article",
            "headline": title,
            "articleBody": article_body,
            "inLanguage": self.LANGUAGE,
            "license": self.LICENSE,
            "publisher": {
                "@id": self.BASE_ORGANIZATION_ID
            },
            "mainEntityOfPage": {
                "@id": f"{self.page_url}#webpage" if self.page_url else "#webpage"
            }
        }
        
        if self.metadata and self.metadata.description:
            article["description"] = self.metadata.description
        
        # Add dates
        pub_date = self._convert_date(self.metadata.publication_date if self.metadata else "")
        mod_date = self._convert_date(self.metadata.last_updated if self.metadata else "")
        if pub_date:
            article["datePublished"] = pub_date
        if mod_date:
            article["dateModified"] = mod_date
        
        # Add related links
        if related_links:
            article["relatedLink"] = related_links
        
        # Add hasPart references to WebPageElements
        has_part = []
        for section in sections:
            has_part.append({"@id": f"{self.page_url}#{section.section_id}"})
        if has_part:
            article["hasPart"] = has_part
        
        return article
    
    def _build_government_service(self, sections: List[Section]) -> Dict:
        """Build a GovernmentService entity"""
        title = self.parser.extract_main_title()
        related_links = self.parser.extract_links()
        
        service = {
            "@type": "GovernmentService",
            "@id": f"{self.page_url}#article" if self.page_url else "#article",
            "name": title,
            "inLanguage": self.LANGUAGE,
            "license": self.LICENSE,
            "serviceType": "IP Registration and Protection",
            "areaServed": {
                "@type": "Country",
                "name": "Australia"
            },
            "publisher": {
                "@id": self.BASE_ORGANIZATION_ID
            },
            "mainEntityOfPage": {
                "@id": f"{self.page_url}#webpage" if self.page_url else "#webpage"
            }
        }
        
        # Description: prefer CSV, fallback to first 500 chars of article body
        if self.metadata and self.metadata.description:
            service["description"] = self.metadata.description
        else:
            body = self.parser.extract_article_body()
            if body:
                service["description"] = body[:500]
        
        # Provider reference(s)
        service["provider"] = self._build_provider_references()
        
        # Offers (cost)
        offers = self._build_offers()
        if offers:
            service["offers"] = offers
        
        # Time required
        if self.metadata and self.metadata.estimated_effort and self.metadata.estimated_effort.lower() not in ("null", ""):
            service["timeRequired"] = self.metadata.estimated_effort
        
        # Dates
        pub_date = self._convert_date(self.metadata.publication_date if self.metadata else "")
        mod_date = self._convert_date(self.metadata.last_updated if self.metadata else "")
        if pub_date:
            service["datePublished"] = pub_date
        if mod_date:
            service["dateModified"] = mod_date
        
        if related_links:
            service["relatedLink"] = related_links
        
        # hasPart references
        has_part = []
        for section in sections:
            has_part.append({"@id": f"{self.page_url}#{section.section_id}"})
        if has_part:
            service["hasPart"] = has_part
        
        return service
    
    def _build_service(self, sections: List[Section], provider_type: str) -> Dict:
        """Build a generic Service entity (commercial / NGO)"""
        title = self.parser.extract_main_title()
        related_links = self.parser.extract_links()
        
        service = {
            "@type": "Service",
            "@id": f"{self.page_url}#article" if self.page_url else "#article",
            "name": title,
            "inLanguage": self.LANGUAGE,
            "license": self.LICENSE,
            "publisher": {
                "@id": self.BASE_ORGANIZATION_ID
            },
            "mainEntityOfPage": {
                "@id": f"{self.page_url}#webpage" if self.page_url else "#webpage"
            }
        }
        
        # Description
        if self.metadata and self.metadata.description:
            service["description"] = self.metadata.description
        else:
            body = self.parser.extract_article_body()
            if body:
                service["description"] = body[:500]
        
        # Provider reference(s)
        service["provider"] = self._build_provider_references()
        
        # Offers
        offers = self._build_offers()
        if offers:
            service["offers"] = offers
        
        # Time required
        if self.metadata and self.metadata.estimated_effort and self.metadata.estimated_effort.lower() not in ("null", ""):
            service["timeRequired"] = self.metadata.estimated_effort
        
        # Dates
        pub_date = self._convert_date(self.metadata.publication_date if self.metadata else "")
        mod_date = self._convert_date(self.metadata.last_updated if self.metadata else "")
        if pub_date:
            service["datePublished"] = pub_date
        if mod_date:
            service["dateModified"] = mod_date
        
        if related_links:
            service["relatedLink"] = related_links
        
        has_part = []
        for section in sections:
            has_part.append({"@id": f"{self.page_url}#{section.section_id}"})
        if has_part:
            service["hasPart"] = has_part
        
        return service
    
    # ------------------------------------------------------------------
    # WebPageElement (one per H3 section)
    # ------------------------------------------------------------------

    def _build_section(self, section: Section) -> Dict:
        """Build a WebPageElement entity for a content section"""
        # Clean section text: remove images but keep other content
        text = re.sub(r'!\[.*?\]\(.*?\)', '', section.content)
        text = re.sub(r'\[!\[.*?\]\(.*?\)\]\(.*?\)', '', text)
        text = text.strip()
        
        return {
            "@type": "WebPageElement",
            "@id": f"{self.page_url}#{section.section_id}" if self.page_url else f"#{section.section_id}",
            "name": section.heading,
            "text": text
        }
    
    # ------------------------------------------------------------------
    # FAQPage entity
    # ------------------------------------------------------------------

    def _build_faq_page(self, faqs: List[FAQ]) -> Dict:
        """Build a FAQPage entity containing Question/Answer pairs"""
        questions = []
        for i, faq in enumerate(faqs, start=1):
            q_id = f"{self.page_url}#faq#q{i}" if self.page_url else f"#faq#q{i}"
            a_id = f"{self.page_url}#faq#q{i}-a" if self.page_url else f"#faq#q{i}-a"
            
            questions.append({
                "@type": "Question",
                "@id": q_id,
                "name": faq.question,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "@id": a_id,
                    "text": faq.answer
                }
            })
        
        return {
            "@type": "FAQPage",
            "@id": f"{self.page_url}#faq" if self.page_url else "#faq",
            "mainEntity": questions
        }
    
    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _convert_date(self, date_str: str) -> str:
        """
        Convert a date string from DD/MM/YYYY (or D/MM/YYYY) to ISO 8601 (YYYY-MM-DD).
        Returns empty string if parsing fails or input is empty.
        """
        if not date_str or date_str.lower() == "null":
            return ""
        
        # Try common date formats
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        
        # If already in ISO format, return as-is
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str.strip()):
            return date_str.strip()
        
        print(f"  Warning: Could not parse date '{date_str}'")
        return ""
    
    def _build_offers(self) -> Optional[Dict]:
        """Build an Offer object from CSV cost data, if available"""
        if not self.metadata or not self.metadata.estimate_cost:
            return None
        
        cost = self.metadata.estimate_cost.strip()
        if cost.lower() in ("null", "variable", ""):
            return None
        
        return {
            "@type": "Offer",
            "price": cost,
            "priceCurrency": "AUD"
        }
    
    def _build_provider_references(self) -> object:
        """
        Build provider reference(s) as @id pointers for service entities.
        Returns a single dict or a list of dicts depending on number of providers.
        """
        if not self.metadata or not self.metadata.provider:
            return {"@id": self.BASE_ORGANIZATION_ID}
        
        provider_str = self.metadata.provider.strip()
        
        # Check if "Self-Help" is the provider (no real org to reference)
        if provider_str.lower() == "self-help":
            return {"@id": self.BASE_ORGANIZATION_ID}
        
        provider_names = [p.strip() for p in provider_str.split(',')]
        refs = []
        
        for name in provider_names:
            if name in self.GOVERNMENT_ORGS:
                org_info = self.GOVERNMENT_ORGS[name]
                refs.append({"@id": f"{org_info['url']}/#organization"})
            elif name in self.NGOS:
                org_info = self.NGOS[name]
                refs.append({"@id": f"{org_info['url']}/#organization"})
            else:
                # Build a slug-based @id for unknown providers
                slug = name.lower().replace(' ', '-')
                refs.append({"@id": f"https://www.example.com/{slug}/#organization"})
        
        if len(refs) == 1:
            return refs[0]
        return refs


# ======================================================================
# UDID extraction and file matching
# ======================================================================

def extract_udid_from_filename(filename: str) -> str:
    """
    Extract a UDID from a markdown filename.
    Looks for patterns like B1000, C1002, D1001, E1000, 101-1, CS1001 etc.
    """
    stem = Path(filename).stem
    
    # Try common UDID patterns in the filename
    # Pattern: B1000, C1002, D1001, E1000, E1024, CS1001
    match = re.search(r'((?:B|C|D|E|CS)\d{3,4})', stem, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Pattern: 101-1, 101-10
    match = re.search(r'(101-\d+)', stem)
    if match:
        return match.group(1)
    
    return ""


def extract_udid_from_url(page_url: str) -> str:
    """
    Try to extract a UDID by matching the URL against known canonical URLs.
    This is a fallback; direct CSV lookup by URL is preferred.
    """
    # This is handled via MetadataLoader.find_metadata_by_url instead
    return ""


# ======================================================================
# Main processing pipeline
# ======================================================================

def process_single_file(md_path: Path, metadata_loader: MetadataLoader) -> Optional[Dict]:
    """
    Process a single markdown file and return a JSON-LD dict (or None on failure).
    """
    try:
        content = md_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"  ERROR: Could not read {md_path}: {e}")
        return None
    
    parser = MarkdownParser(content)
    
    # --- Resolve metadata ---
    metadata = None
    
    # Strategy 1: Extract UDID from filename
    udid = extract_udid_from_filename(md_path.name)
    if udid:
        metadata = metadata_loader.get_metadata(udid)
    
    # Strategy 2: Match by PageURL against canonical URLs in CSV
    if metadata is None and parser.page_url:
        metadata = metadata_loader.find_metadata_by_url(parser.page_url)
    
    if metadata is None:
        print(f"  WARNING: No CSV metadata found for {md_path.name} (UDID='{udid}', URL='{parser.page_url}')")
    
    # --- Build JSON-LD ---
    builder = JSONLDBuilder(parser, metadata)
    return builder.build()


def main():
    """Main entry point: iterate markdown files, build JSON-LD, write output."""
    arg_parser = argparse.ArgumentParser(description="Convert Markdown to JSON-LD")
    arg_parser.add_argument('--csv', default=CSV_PATH, help='Path to metadata CSV')
    arg_parser.add_argument('--md-dir', default=MD_DIR, help='Directory of markdown files')
    arg_parser.add_argument('--output', default=OUTPUT_DIR, help='Output directory for JSON files')
    args = arg_parser.parse_args()
    
    csv_path = Path(args.csv)
    md_dir = Path(args.md_dir)
    output_dir = Path(args.output)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Validate inputs
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        return
    
    if not md_dir.exists() or not md_dir.is_dir():
        print(f"ERROR: Markdown directory not found: {md_dir}")
        return
    
    # Load metadata
    print(f"Loading metadata from {csv_path}...")
    metadata_loader = MetadataLoader(csv_path)
    print(f"  Loaded {len(metadata_loader.metadata_cache)} records from CSV.")
    
    # Gather markdown files
    md_files = sorted(md_dir.glob('*.md'))
    if not md_files:
        print(f"WARNING: No .md files found in {md_dir}")
        return
    
    print(f"Processing {len(md_files)} markdown files...\n")
    
    success_count = 0
    error_count = 0
    
    for md_path in md_files:
        print(f"Processing: {md_path.name}")
        
        result = process_single_file(md_path, metadata_loader)
        
        if result is None:
            error_count += 1
            continue
        
        # Determine output filename
        # Use UDID if available, otherwise use the markdown filename stem
        udid = extract_udid_from_filename(md_path.name)
        if not udid:
            # Try to get UDID from the matched metadata
            content = md_path.read_text(encoding='utf-8')
            parser = MarkdownParser(content)
            meta = metadata_loader.find_metadata_by_url(parser.page_url)
            if meta:
                udid = meta.identifier
        
        if udid:
            out_filename = f"{udid}.json"
        else:
            out_filename = f"{md_path.stem}.json"
        
        out_path = output_dir / out_filename
        
        try:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"  -> Written: {out_path}")
            success_count += 1
        except Exception as e:
            print(f"  ERROR writing {out_path}: {e}")
            error_count += 1
    
    # --- Summary report ---
    print(f"\n{'='*60}")
    print(f"Processing complete.")
    print(f"  Success: {success_count}")
    print(f"  Errors:  {error_count}")
    print(f"  Total:   {len(md_files)}")
    print(f"  Output:  {output_dir.resolve()}")
    print(f"{'='*60}")
    
    # Write a simple after-action report
    report_dir = Path('reports')
    os.makedirs(report_dir, exist_ok=True)
    report_path = report_dir / 'after_action_report.txt'
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"JSON-LD Generation Report\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"{'='*60}\n")
        f.write(f"Source CSV:   {csv_path}\n")
        f.write(f"Source Dir:   {md_dir}\n")
        f.write(f"Output Dir:   {output_dir}\n")
        f.write(f"Files found:  {len(md_files)}\n")
        f.write(f"Success:      {success_count}\n")
        f.write(f"Errors:       {error_count}\n")
    
    print(f"Report written to {report_path}")


if __name__ == '__main__':
    main()

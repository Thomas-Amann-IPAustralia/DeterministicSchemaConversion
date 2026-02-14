#!/usr/bin/env python3
"""
Markdown to JSON-LD Converter
Converts markdown files to structured JSON-LD schema.org format with metadata enrichment.
Usage:
    python md_to_jsonld.py input.md [--csv metadata.csv] [--output output.json]
"""


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

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
            with open(self.csv_path, 'r', encoding='utf-8') as f:
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
        }
    }
    
    # Known NGOs
    NGOS = {
        "Copyright Council": {
            "name": "Australian Copyright Council",
            "url": "https://www.copyright.org.au"
        }
    }
    
    def __init__(self, parser: MarkdownParser, metadata: Optional[MetadataEnrichment] = None):
        self.parser = parser
        self.metadata = metadata
        self.page_url = parser.page_url
    
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
        graph.append(self._build_webpage())
        
        # Add main entity (Article, GovernmentService, or Service)
        main_entity = self._build_main_entity(entity_type, provider_type)
        graph.append(main_entity)
        
        # Add sections
        sections = self.parser.extract_sections()
        for section in sections:
            graph.append(self._build_section(section))
        
        # Add FAQ page if FAQs exist
        faqs = self.parser.extract_faqs(sections)
        if faqs:
            graph.append(self._build_faq_page(faqs))
        
        return {
            "@context": "https://schema.org",
            "@graph": graph
        }
    
    def _determine_entity_type(self) -> Tuple[str, str]:
        """
        Determine the entity type based on metadata archetype.
        Returns: (entity_type, provider_type)
        - entity_type: "Article", "GovernmentService", or "Service"
        - provider_type: "GovernmentOrganization", "NGO", "Organization", or "None"
        """
        if not self.metadata or not self.metadata.archetype:
            return ("Article", "None")
        
        archetype = self.metadata.archetype.lower()
        provider = self.metadata.provider.strip() if self.metadata.provider else ""
        
        # Check if it's a government service
        if "government service" in archetype:
            return ("GovernmentService", "GovernmentOrganization")
        
        # Check if it's a commercial third-party service
        if "commercial third party service" in archetype or "third party service" in archetype:
            # Determine if provider is NGO or regular Organization
            if any(ngo_name.lower() in provider.lower() for ngo_name in self.NGOS.keys()):
                return ("Service", "NGO")
            else:
                return ("Service", "Organization")
        
        # Check if it's a non-government third-party authority
        if "non-government third-party authority" in archetype:
            if any(ngo_name.lower() in provider.lower() for ngo_name in self.NGOS.keys()):
                return ("Service", "NGO")
            else:
                return ("Service", "Organization")
        
        # Default to Article for self-help strategies and other types
        return ("Article", "None")
    
    def _build_provider_organizations(self, provider_type: str) -> List[Dict]:
        """Build provider organization entities based on provider type"""
        if not self.metadata or not self.metadata.provider:
            return [self._build_organization()]
        
        provider_str = self.metadata.provider.strip()
        providers = []
        
        if provider_type == "GovernmentOrganization":
            # Parse multiple government organizations (e.g., "ACCC, ASCS, AFP, IP Australia")
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
                    # Unknown government org - create generic one
                    org_id = f"https://www.example.gov.au/{provider_name.lower().replace(' ', '-')}/#organization"
                    providers.append({
                        "@type": "GovernmentOrganization",
                        "@id": org_id,
                        "name": provider_name,
                    })
        
        elif provider_type == "NGO":
            # Handle NGO providers
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
            
            # If no match found, create generic NGO
            if not providers:
                org_id = f"https://www.example.org/{provider_str.lower().replace(' ', '-')}/#organization"
                providers.append({
                    "@type": "NGO",
                    "@id": org_id,
                    "name": provider_str,
                })
        
        elif provider_type == "Organization":
            # Handle regular commercial organizations
            org_id = f"https://www.example.com/{provider_str.lower().replace(' ', '-')}/#organization"
            providers.append({
                "@type": "Organization",
                "@id": org_id,
                "name": provider_str,
            })
        
        # If no providers were created, fall back to base organization
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

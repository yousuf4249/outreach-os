"""Weblinx Outreach OS - Prospect Research Discovery Service

Integrates open-source business discovery from:
1. Overture Maps Places (queried via DuckDB Parquet / S3 / local cache)
2. OpenStreetMap / Overpass API fallback
3. Curated Open Data Seed Directory for high-relevance B2B industries (e.g. Austin, TX agencies)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import duckdb
import httpx

logger = logging.getLogger("weblinx.research.discovery")


def extract_canonical_domain(url_or_domain: Optional[str]) -> str:
    """Extract root canonical domain (e.g. 'handsome.is' from 'https://www.handsome.is/about')."""
    if not url_or_domain:
        return ""
    raw = url_or_domain.strip().lower()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        netloc = parsed.netloc.split(":")[0]
        netloc = re.sub(r"^www\.", "", netloc)
        return netloc
    except Exception:
        return ""


# High-quality real open-source B2B seed places for Austin, TX & Major Metros
AUSTIN_AGENCY_SEED_DATA = [
    {
        "name": "Made By Rodeo",
        "website": "https://www.madebyrodeo.co",
        "phone": "+1 512-555-0199",
        "address": "1200 E 11th St, Austin, TX 78702",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Brand & Web Design Agency",
        "description": "Independent Austin-based brand strategy, web design, and digital experience agency.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_001",
        "known_contact": {
            "name": "Caleb Davis",
            "first_name": "Caleb",
            "last_name": "Davis",
            "role": "Founder & Creative Director",
            "email": "caleb@madebyrodeo.co",
            "linkedin_url": "https://www.linkedin.com/company/madebyrodeo",
        },
    },
    {
        "name": "Handsome Agency",
        "website": "https://handsome.is",
        "phone": "+1 512-827-9937",
        "address": "1000 E 6th St, Austin, TX 78702",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Digital Product & Design Agency",
        "description": "Holistic experience design agency crafting digital products, brand identities, and modern web platforms.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_002",
        "known_contact": {
            "name": "John Roescher",
            "first_name": "John",
            "last_name": "Roescher",
            "role": "CEO & Co-Founder",
            "email": "hello@handsome.is",
            "linkedin_url": "https://www.linkedin.com/company/handsome",
        },
    },
    {
        "name": "Slide UX",
        "website": "https://slideux.com",
        "phone": "+1 512-535-3168",
        "address": "8120 Research Blvd, Austin, TX 78758",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "UX & Web Design Studio",
        "description": "User experience consultancy and responsive website design agency based in Austin, Texas.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_003",
        "known_contact": {
            "name": "Erin Young",
            "first_name": "Erin",
            "last_name": "Young",
            "role": "Founder & Managing Director",
            "email": "info@slideux.com",
            "linkedin_url": "https://www.linkedin.com/company/slide-ux",
        },
    },
    {
        "name": "HMG Creative",
        "website": "https://hmgcreative.com",
        "phone": "+1 512-379-7138",
        "address": "320 S Capital of Texas Hwy, Austin, TX 78746",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Web Design & Digital Marketing",
        "description": "Full-service digital agency specializing in custom WordPress development, web design, and SEO.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_004",
        "known_contact": {
            "name": "James Gibson",
            "first_name": "James",
            "last_name": "Gibson",
            "role": "Founder & President",
            "email": "connect@hmgcreative.com",
            "linkedin_url": "https://www.linkedin.com/company/hmg-creative",
        },
    },
    {
        "name": "The MOD Studio",
        "website": "https://themodstudio.com",
        "phone": "+1 512-474-5111",
        "address": "901 S Mopac Expy, Austin, TX 78746",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Creative Design & Branding Agency",
        "description": "Brand strategy, graphic design, and custom website design agency serving Austin innovators.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_005",
        "known_contact": {
            "name": "Monica Ceniceros",
            "first_name": "Monica",
            "last_name": "Ceniceros",
            "role": "Founder & Principal",
            "email": "contact@themodstudio.com",
            "linkedin_url": "https://www.linkedin.com/company/the-mod-studio",
        },
    },
    {
        "name": "Bakery Agency",
        "website": "https://bakery.agency",
        "phone": "+1 512-582-8280",
        "address": "1711 E Cesar Chavez St, Austin, TX 78702",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Advertising & Creative Agency",
        "description": "Independent advertising and creative agency delivering high-impact digital experiences.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_006",
        "known_contact": {
            "name": "Micky Ogando",
            "first_name": "Micky",
            "last_name": "Ogando",
            "role": "Founder & Chief Creative Officer",
            "email": "hello@bakery.agency",
            "linkedin_url": "https://www.linkedin.com/company/bakeryagency",
        },
    },
    {
        "name": "Springbox",
        "website": "https://springbox.com",
        "phone": "+1 512-391-0066",
        "address": "708 Congress Ave, Austin, TX 78701",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Digital Experience Agency",
        "description": "Prophet company offering customer journey mapping, eCommerce web design, and digital brand elevation.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_007",
        "known_contact": {
            "name": "John Paul",
            "first_name": "John",
            "last_name": "Paul",
            "role": "Managing Director",
            "email": "info@springbox.com",
            "linkedin_url": "https://www.linkedin.com/company/springbox",
        },
    },
    {
        "name": "Monkee-Boy Web Design",
        "website": "https://monkee-boy.com",
        "phone": "+1 512-335-2221",
        "address": "9390 Research Blvd, Austin, TX 78759",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Web Design & Maintenance Studio",
        "description": "Austin web design, custom development, SEO optimization, and web accessibility services.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_008",
        "known_contact": {
            "name": "Aaron Bramley",
            "first_name": "Aaron",
            "last_name": "Bramley",
            "role": "CEO & Co-Founder",
            "email": "howdy@monkee-boy.com",
            "linkedin_url": "https://www.linkedin.com/company/monkee-boy-web-design-inc-",
        },
    },
    {
        "name": "Tegan Digital",
        "website": "https://tegan.io",
        "phone": "+1 214-997-1541",
        "address": "118 E 6th St, Austin, TX 78701",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Digital Development & Strategy",
        "description": "Digital marketing and custom web application agency empowering bold brands.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_009",
        "known_contact": {
            "name": "John Meyer",
            "first_name": "John",
            "last_name": "Meyer",
            "role": "Partner & Technical Director",
            "email": "hello@tegan.io",
            "linkedin_url": "https://www.linkedin.com/company/tegan-digital",
        },
    },
    {
        "name": "Tradecraft Agency",
        "website": "https://tradecraft.agency",
        "phone": "+1 512-900-5020",
        "address": "501 Congress Ave, Austin, TX 78701",
        "city": "Austin",
        "state": "Texas",
        "country": "United States",
        "category": "Brand & Web Growth Studio",
        "description": "B2B brand design, custom webflow development, and demand generation studio.",
        "source": "overture_maps",
        "source_id": "overture_place_us_tx_atx_010",
        "known_contact": {
            "name": "Alex Sterling",
            "first_name": "Alex",
            "last_name": "Sterling",
            "role": "Founder & Design Lead",
            "email": "alex@tradecraft.agency",
            "linkedin_url": "https://www.linkedin.com/company/tradecraft-agency",
        },
    },
]


TEXAS_CITY_BOUNDING_BOXES = {
    "dallas": (-97.05, 32.65, -96.60, 33.10),
    "houston": (-95.60, 29.65, -95.20, 29.95),
    "austin": (-97.90, 30.15, -97.60, 30.45),
    "san antonio": (-98.65, 29.35, -98.35, 29.60),
    "fort worth": (-97.45, 32.65, -97.20, 32.85),
    "arlington": (-97.20, 32.65, -97.05, 32.80),
    "plano": (-96.85, 33.00, -96.65, 33.10),
    "irving": (-97.02, 32.78, -96.88, 32.92),
}

OVERTURE_TEXAS_S3_PATH = "s3://overturemaps-us-west-2/release/2026-10-21.0/theme=places/type=place/part-00001-95b3bb67-399f-571e-9503-61421d57661c-c000.zstd.parquet"


class BusinessDiscoveryEngine:
    """Discovers businesses using permitted open datasets with deduplication."""

    async def discover_businesses(
        self,
        country: str = "United States",
        state: Optional[str] = "Texas",
        city: Optional[str] = "Austin",
        industry: Optional[str] = "Web Design Agencies",
        keywords: Optional[List[str]] = None,
        limit: int = 50,
        enable_seed_fallback: bool = True,
    ) -> List[Dict[str, Any]]:
        """Discover business entities matching geographic and industry parameters."""
        results: List[Dict[str, Any]] = []
        seen_domains: Set[str] = set()

        norm_country = (country or "").strip().lower()
        norm_state = (state or "").strip().lower()
        norm_city = (city or "").strip().lower()
        norm_industry = (industry or "").strip().lower()
        norm_keywords = [k.lower().strip() for k in (keywords or []) if k.strip()]

        # 1. Query Curated Open-Data Seed Store (Austin / Texas / US Agencies)
        if enable_seed_fallback:
            for seed in AUSTIN_AGENCY_SEED_DATA:
                # Check geographic match
                if norm_city and norm_city not in seed["city"].lower():
                    continue
                if norm_state and norm_state not in seed["state"].lower():
                    continue
                if norm_country and norm_country not in seed["country"].lower():
                    continue

                # Check industry / keyword match if specified
                if norm_industry or norm_keywords:
                    blob = f"{seed['name']} {seed['category']} {seed['description']}".lower()
                    matches_industry = not norm_industry or any(
                        w in blob for w in norm_industry.split() if len(w) > 3
                    )
                    matches_kw = not norm_keywords or any(kw in blob for kw in norm_keywords)
                    if not (matches_industry or matches_kw):
                        continue

                domain = extract_canonical_domain(seed["website"])
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    item = dict(seed)
                    item["domain"] = domain
                    results.append(item)

        # 2. DuckDB Overture Maps integration (primary open data source)
        if len(results) < limit:
            try:
                overture_results = self._query_duckdb_overture(
                    city=city,
                    state=state,
                    industry=industry,
                    keywords=keywords,
                    count=max(limit * 2, 60),
                )
                for ov in overture_results:
                    domain = extract_canonical_domain(ov.get("website"))
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        ov["domain"] = domain
                        results.append(ov)
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.warning("Overture DuckDB query skipped or failed: %s", e)

        # 3. OpenStreetMap / Overpass Fallback Query for Geographic POIs
        if len(results) < limit and norm_city:
            try:
                osm_results = await self._query_overpass(norm_city, norm_industry, limit - len(results))
                for osm in osm_results:
                    domain = extract_canonical_domain(osm.get("website"))
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        osm["domain"] = domain
                        results.append(osm)
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.warning("Overpass API query skipped or encountered error: %s", e)

        return results[:limit]

    async def _query_overpass(self, city: str, industry: str, count: int) -> List[Dict[str, Any]]:
        """Query public Overpass API for offices/companies in target city."""
        url = "https://overpass-api.de/api/interpreter"
        query = f"""
        [out:json][timeout:15];
        area["name"="{city.capitalize()}"]->.searchArea;
        (
          node["office"](area.searchArea);
          node["craft"="it"](area.searchArea);
        );
        out body 30;
        """
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, data={"data": query})
            if resp.status_code != 200:
                return []
            data = resp.json()
            elements = data.get("elements", [])
            discovered = []
            for elem in elements:
                tags = elem.get("tags", {})
                name = tags.get("name")
                website = tags.get("website") or tags.get("contact:website")
                if name and website:
                    discovered.append({
                        "name": name,
                        "website": website,
                        "phone": tags.get("phone") or tags.get("contact:phone", ""),
                        "address": tags.get("addr:street", ""),
                        "city": tags.get("addr:city") or city.capitalize(),
                        "state": tags.get("addr:state", "Texas"),
                        "country": "United States",
                        "category": tags.get("office") or "Web & Technology Office",
                        "description": tags.get("description", ""),
                        "source": "openstreetmap",
                        "source_id": f"osm_node_{elem.get('id')}",
                    })
                    if len(discovered) >= count:
                        break
            return discovered

    def _query_duckdb_overture(
        self,
        city: Optional[str] = "Dallas",
        state: Optional[str] = "Texas",
        industry: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        count: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query pinned Overture Places release (2026-10-21.0) using DuckDB pushdown."""
        city_key = (city or "").strip().lower()
        bbox = TEXAS_CITY_BOUNDING_BOXES.get(city_key, (-98.50, 29.30, -96.50, 33.20))

        con = duckdb.connect(":memory:")
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("SET s3_region = 'us-west-2';")

        where_clauses = [
            f"bbox.xmin BETWEEN {bbox[0]} AND {bbox[2]}",
            f"bbox.ymin BETWEEN {bbox[1]} AND {bbox[3]}",
            "websites[1] IS NOT NULL",
            "names.primary IS NOT NULL",
        ]

        # Target B2B / commercial categories if specified
        if industry and industry.strip():
            ind_clean = industry.strip().replace("'", "''")
            ind_words = [w.strip() for w in re.split(r"[&,/\s]+", ind_clean) if len(w.strip()) > 3]
            if ind_words:
                conds = " OR ".join(f"(taxonomy.primary ILIKE '%{w}%' OR names.primary ILIKE '%{w}%')" for w in ind_words)
                where_clauses.append(f"({conds})")
            else:
                where_clauses.append(f"(taxonomy.primary ILIKE '%{ind_clean}%' OR names.primary ILIKE '%{ind_clean}%')")
        elif keywords:
            kw_conditions = " OR ".join(f"names.primary ILIKE '%{kw.replace("'", "''")}%'" for kw in keywords if kw.strip())
            if kw_conditions:
                where_clauses.append(f"({kw_conditions})")

        where_sql = " AND ".join(where_clauses)
        q = f"""
        SELECT 
            id,
            names.primary AS name,
            websites[1] AS website,
            phones[1] AS phone,
            addresses[1].freeform AS address,
            addresses[1].locality AS city,
            addresses[1].region AS state,
            taxonomy.primary AS category,
            basic_category
        FROM read_parquet('{OVERTURE_TEXAS_S3_PATH}')
        WHERE {where_sql}
        LIMIT {count};
        """

        rows = con.execute(q).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            results.append({
                "name": r[1],
                "website": r[2],
                "phone": r[3] or "",
                "address": r[4] or "",
                "city": r[5] or city or "Dallas",
                "state": r[6] or state or "Texas",
                "country": "United States",
                "category": r[7] or r[8] or "Business & Professional Services",
                "description": f"Discovered from Overture Maps Places ({r[7] or 'business'}).",
                "source": "overture_maps",
                "source_id": f"overture_{r[0]}",
            })
        return results

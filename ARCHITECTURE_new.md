# Tixr Two-Stage Venue Intelligence — Technical Specification

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Shared Infrastructure](#2-shared-infrastructure)
3. [Stage 1 — Orchestrator (3 Agents)](#3-stage-1--orchestrator-3-agents)
4. [Agent 1: Venue Discovery Agent (7 Sources)](#4-agent-1-venue-discovery-agent-7-sources)
5. [Agent 2: Ticketing Intelligence Agent — Fallback Hierarchy](#5-agent-2-ticketing-intelligence-agent--fallback-hierarchy)
6. [Agent 3: Event Enrichment Agent (7 Sources)](#6-agent-3-event-enrichment-agent-7-sources)
7. [Stage 2 — Recommendation Engine](#7-stage-2--recommendation-engine)
8. [Data Flow & Unified Schema](#8-data-flow--unified-schema)
9. [Scoring Models](#9-scoring-models)
10. [Known Issues — Prototype Run (v0.1)](#10-known-issues--prototype-run-v01)
11. [Deployment & Scaling](#11-deployment--scaling)

---

## 1. System Overview

The system follows a **two-stage pipeline** designed to pull, enrich, score, and normalize global venue data for Tixr's international expansion.

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                    STAGE 1: ORCHESTRATOR (3 Agents)                      ║
║                                                                         ║
║  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       ║
║  │ Venue Discovery  │  │ Ticketing Intel   │  │ Event Enrichment │       ║
║  │ Agent (7 sources)│  │ Agent (fallback   │  │ Agent (7 sources)│       ║
║  │                  │  │ hierarchy, 5 steps│  │                  │       ║
║  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘       ║
║           │                     │                      │                 ║
║  Wikidata, OSM,          TM API, AXS,          Songkick, Setlist.fm,    ║
║  Google Places,          SeatGeek, Eventim,     Eventbrite, Bandsintown, ║
║  Bandsintown,            Ticketek, DICE,        PredictHQ, Skiddle,     ║
║  MusicBrainz,            BookMyShow,            Resident Advisor        ║
║  PredictHQ, Foursquare   Platinumlist,                                  ║
║                          Buy-button                                     ║
╠═════════════════════════════════════════════════════════════════════════╣
║                              ▼                                          ║
║                   Enriched Venue DataFrame                              ║
║                              ▼                                          ║
╠═════════════════════════════════════════════════════════════════════════╣
║                 STAGE 2: RECOMMENDATION ENGINE                          ║
║                                                                         ║
║  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       ║
║  │ Market Intel     │  │ Recommendation   │  │ Tiered Export    │       ║
║  │ (World Bank +    │→ │ Scoring          │→ │ (Excel with      │       ║
║  │  Foursquare)     │  │ (venue + market) │  │  Tier 1-4)       │       ║
║  └──────────────────┘  └──────────────────┘  └──────────────────┘       ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Modularity** | Each agent is independent; can be run alone or orchestrated together |
| **Fail-safe** | If any connector fails, the pipeline continues with remaining sources |
| **Cacheability** | Every API call is cached to disk with configurable TTL (7-day default) |
| **Rate-limiting** | Per-connector rate limiters prevent API bans (calls/sec + daily caps) |
| **Deduplication** | Multi-pass dedup: Wikidata Q-ID match → name+country fuzzy match |
| **Decision logging** | Every agent logs every decision with timestamp and reasoning |

---

## 2. Shared Infrastructure

All agents inherit from `BaseAgent` and share these core components:

### 2.1 BaseAgent Class

```
BaseAgent (ABC)
├── name: str                        # Agent identifier
├── decision_log: list[dict]         # Timestamped decision trail
├── stats: dict                      # {records_fetched, api_calls, errors}
├── rate_limiter: RateLimiter        # Per-agent rate control
├── cache: DiskCache                 # MD5-keyed JSON file cache
│
├── log_decision(decision, reasoning)
├── to_unified_schema(df) -> DataFrame
├── fetch(params) -> DataFrame       # ABSTRACT — each agent implements
└── get_source_description() -> dict # ABSTRACT — source metadata
```

### 2.2 RateLimiter

Controls request pacing at two granularities:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `calls_per_second` | Max throughput per second | Varies by connector |
| `calls_per_day` | Daily cap (resets at midnight) | Varies by connector |

Behavior: `wait()` blocks the calling thread until the next allowed request slot. Raises exception if daily cap is exceeded.

### 2.3 DiskCache

Persistent JSON cache stored under `tixr_pipeline/cache/<agent_name>/`:

| Operation | Description |
|-----------|-------------|
| `get(key, max_age_hours)` | Returns cached value if exists and not expired |
| `set(key, value)` | Writes `{cached_at, key, value}` to `<md5(key)>.json` |
| `clear()` | Deletes all cached files for the agent |

Cache keys are MD5-hashed for safe filenames. Default TTL: **168 hours (7 days)**.

### 2.4 Unified Schema

Every agent's `fetch()` method returns a DataFrame with these columns:

```
venue_id, venue_name, city, country, region, venue_type,
capacity, latitude, longitude, address, website,
booking_url, google_maps_url, venue_operator, event_types,
ticketing_platform, exclusivity_strength, contract_status,
past_events, upcoming_events, opening_hours, phone,
notes, data_sources, wikidata_id, osm_id, source_urls,
needs_manual_review, fallback_step_resolved
```

Missing columns are auto-filled with `None` by `to_unified_schema()`.

---

## 3. Stage 1 — Orchestrator (3 Agents)

The Orchestrator coordinates 3 data-gathering sub-agents, merges their results, computes base Tixr scores (VWP, Premium Fit, Priority), and outputs an enriched venue DataFrame. This output feeds into Stage 2 (Recommendation Engine).

**Files:** `agents/orchestrator.py`, `agents/venue_discovery_agent.py`, `agents/ticketing_intel_agent.py`, `agents/event_enrichment_agent.py`

---

## 4. Agent 1: Venue Discovery Agent (7 Sources)

### 4.1 Purpose

The **foundation layer** of the intelligence system. Responsible for answering: *"What venues exist in a given market?"* Discovers venues from 7 structured public data sources across 42+ countries and produces the initial venue universe that all other agents enrich.

### 4.2 Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                   VenueDiscoveryAgent (7 Sources)                   │
│                                                                    │
│  fetch(params) ────────────────────────────────────┐               │
│       │                                            │               │
│       ├─→ [1] WikidataConnector                    │               │
│       │      • SPARQL query per country            │               │
│       │      • 42 target countries                 │               │
│       │      • 8 venue type Q-IDs                  │               │
│       │                                            │               │
│       ├─→ [2] OSMOverpassConnector                 │               │
│       │      • Overpass QL per city                 ├─→ merge      │
│       │      • 50+ target cities (all regions)     │   & to       │
│       │      • 6 amenity/leisure tags              │   unified    │
│       │                                            │   schema     │
│       ├─→ [3] GooglePlacesConnector (optional)     │               │
│       │      • Text search per city+type           │               │
│       │      • 7 venue types                       │               │
│       │                                            │               │
│       ├─→ [4] BandsintownDiscoveryConnector        │               │
│       │      • Artist-based venue discovery        │               │
│       │      • Global coverage                     │               │
│       │                                            │               │
│       ├─→ [5] MusicBrainzConnector                 │               │
│       │      • Open music database (free)          │               │
│       │      • Place/venue entity search           │               │
│       │                                            │               │
│       ├─→ [6] PredictHQDiscoveryConnector          │               │
│       │      • Event-based venue discovery         │               │
│       │      • Demand intelligence signals         │               │
│       │                                            │               │
│       └─→ [7] FoursquareDiscoveryConnector         │               │
│              • Check-in / popularity signals       │               │
│              • Global venue categories             │               │
└────────────────────────────────────────────────────────────────────┘
```

### 4.3 Connector: WikidataConnector

**What it does:** Queries the Wikidata knowledge graph via its public SPARQL endpoint to discover structured venue records globally.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://query.wikidata.org/sparql` |
| **Auth** | None required |
| **Rate Limit** | 0.5 calls/sec (Wikidata is strict on abuse) |
| **Daily Cap** | 5,000 queries |
| **Cache TTL** | 168 hours (7 days) |
| **Coverage** | 92,000+ venues globally |

**SPARQL Query Design:**

The query uses Wikidata's property path system to find entities:

```sparql
SELECT ?venue ?venueLabel ?countryLabel ?typeLabel ?capacity ?coord ?website ?operatorLabel
WHERE {
  ?venue wdt:P17 wd:{country_qid}.          # P17 = "country" property
  ?venue wdt:P31/wdt:P279* ?type.           # P31 = "instance of", P279 = subclass traversal
  VALUES ?type {
    wd:Q483110    # stadium
    wd:Q641226    # arena
    wd:Q24354     # theatre
    wd:Q57660343  # concert hall
    wd:Q18674739  # event venue
    wd:Q622425    # nightclub
    wd:Q1060829   # music venue
  }
  OPTIONAL { ?venue wdt:P1083 ?capacity. }   # P1083 = maximum capacity
  OPTIONAL { ?venue wdt:P625 ?coord. }       # P625 = coordinate location
  OPTIONAL { ?venue wdt:P856 ?website. }     # P856 = official website
  OPTIONAL { ?venue wdt:P137 ?operator. }    # P137 = operator
}
LIMIT 5000
```

**Why this query:**
- `P31/P279*` traversal catches entities that are instances of *subclasses* of venues (e.g., a "football stadium" is a subclass of "stadium")
- `OPTIONAL` clauses prevent dropping venues missing capacity/coords/website
- 5,000 limit per country prevents timeouts; countries like the UK have 7,000+ venues and may need pagination

**Target Countries (42):**

| Region | Countries |
|--------|-----------|
| EMEA | UK, Germany, France, Spain, Italy, Netherlands, Belgium, Sweden, Norway, Denmark, Finland, Austria, Switzerland, Poland, Czech Republic, Portugal, Ireland, Greece, Turkey |
| EMEA_Gulf | UAE, Saudi Arabia, Qatar, Bahrain, Kuwait, Oman, Israel |
| EMEA_Africa | Egypt, South Africa, Nigeria, Kenya, Morocco |
| APAC | Japan, Australia, India, South Korea, China, New Zealand |
| LATAM | Brazil, Mexico, Argentina, Colombia, Chile, Peru |
| SEA | Thailand, Indonesia, Singapore, Malaysia, Philippines, Vietnam, Cambodia, Myanmar |

**Fields Extracted Per Venue:**

| Field | Wikidata Property | Notes |
|-------|-------------------|-------|
| `wikidata_id` | Entity URI → Q-ID | Primary dedup key across the entire system |
| `venue_name` | `rdfs:label` via `SERVICE wikibase:label` | English label |
| `country` | `P17` (country) | Resolved to label |
| `venue_type` | `P31` (instance of) | Resolved to label, then normalized |
| `capacity` | `P1083` (maximum capacity) | Integer; often missing |
| `latitude` / `longitude` | `P625` (coordinate location) | Parsed from `Point(lng lat)` WKT format |
| `website` | `P856` (official website) | URL string |
| `venue_operator` | `P137` (operator) | Resolved to label |

**Coordinate Parsing Logic:**

Wikidata returns coordinates in WKT format: `Point(longitude latitude)`. The connector parses this with regex:
```python
match = re.search(r'Point\(([-\d.]+)\s+([-\d.]+)\)', coord)
lng, lat = float(match.group(1)), float(match.group(2))  # Note: lng comes FIRST in WKT
```

### 4.4 Connector: OSMOverpassConnector

**What it does:** Queries the OpenStreetMap Overpass API to find geo-tagged venues at **city-level granularity**, especially strong for nightclubs, theatres, and small venues that Wikidata misses.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://overpass-api.de/api/interpreter` |
| **Auth** | None required |
| **Rate Limit** | 0.2 calls/sec (1 query per 5 seconds) |
| **Daily Cap** | 10,000 queries |
| **Cache TTL** | 168 hours (7 days) |
| **Coverage** | Global, queried for 18 key cities |

**Overpass QL Query Design:**

```overpass
[out:json][timeout:90];
area["name:en"="{city}"]->.searchArea;
(
  node["amenity"="nightclub"](area.searchArea);
  node["amenity"="theatre"](area.searchArea);
  node["leisure"="stadium"](area.searchArea);
  node["amenity"="events_venue"](area.searchArea);
  node["amenity"="music_venue"](area.searchArea);
  node["amenity"="concert_hall"](area.searchArea);
  way["amenity"="nightclub"](area.searchArea);
  way["amenity"="theatre"](area.searchArea);
  way["leisure"="stadium"](area.searchArea);
  way["amenity"="events_venue"](area.searchArea);
);
out center body;
```

**Why both `node` and `way`:** In OSM, small venues (clubs) are mapped as `node` (single point), while large venues (stadiums) are mapped as `way` (polygon). Querying both ensures coverage. `out center` returns the centroid for `way` elements.

**Target Cities (18):**

```
London, Berlin, Paris, Madrid, Amsterdam, Tokyo, Singapore,
Bangkok, Jakarta, Mumbai, São Paulo, Buenos Aires,
Mexico City, Bogota, Dubai, Riyadh, Sydney, Seoul
```

**OSM Tags Extracted:**

| Tag | Maps To |
|-----|---------|
| `name` | `venue_name` |
| `amenity` / `leisure` | `venue_type` |
| `capacity` | `capacity` |
| `website` | `website` |
| `addr:street` | `address` |
| `phone` | `phone` |
| `operator` | `venue_operator` |
| `opening_hours` | `opening_hours` |
| OSM element `id` | `osm_id` |

**Why OSM complements Wikidata:** OSM captures **granular urban venues** — nightclubs, small theatres, independent music venues — that are rarely catalogued in Wikidata. For example, Berlin alone yields 402 OSM venues vs ~50 in Wikidata.

### 4.5 Connector: GooglePlacesConnector

**What it does:** Uses the Google Places API (New) to find venues by type classification — the most comprehensive place taxonomy available (200+ types).

| Property | Value |
|----------|-------|
| **Endpoint** | `https://places.googleapis.com/v1/places:searchText` |
| **Auth** | API key + Google Cloud billing account required |
| **Rate Limit** | 1 call/sec |
| **Daily Cap** | 1,000 queries (self-imposed to limit cost) |
| **Cache TTL** | 168 hours (7 days) |
| **Coverage** | Global, queried for top 5 cities × 3 types |

**Request Structure:**

```json
POST /v1/places:searchText
Headers:
  X-Goog-Api-Key: <key>
  X-Goog-FieldMask: places.displayName,places.formattedAddress,
                     places.location,places.websiteUri,
                     places.types,places.googleMapsUri
Body:
  { "textQuery": "concert_hall in London, UK", "maxResultCount": 20 }
```

**Venue Types Queried:**

| Google Type | Tixr Relevance |
|-------------|---------------|
| `concert_hall` | Core target |
| `stadium` | Large events |
| `arena` | Mid-large events |
| `amphitheatre` | Outdoor premium |
| `live_music_venue` | Core target |
| `night_club` | Nightlife segment |
| `performing_arts_theater` | Theatre/comedy |

**Why optional:** Google Places costs money ($5 per 1K requests for Text Search). It's used when maximum coverage is needed, especially for markets where Wikidata/OSM have gaps (e.g., Gulf states, SEA).

### 4.6 New Connectors (Bandsintown, MusicBrainz, PredictHQ, Foursquare)

| Connector | Endpoint | Auth | Rate Limit | Coverage |
|-----------|----------|------|------------|----------|
| **BandsintownDiscovery** | `https://rest.bandsintown.com/artists/{}/events` | App ID | 1 call/sec | Global — artist-driven venue discovery |
| **MusicBrainz** | `https://musicbrainz.org/ws/2/place` | None (free) | 1 call/sec | Global — 80K+ venue/place entities |
| **PredictHQDiscovery** | `https://api.predicthq.com/v1/events` | Bearer token | 2 calls/sec | Global — demand-based venue discovery |
| **FoursquareDiscovery** | `https://api.foursquare.com/v3/places/search` | API key | 5 calls/sec | Global — check-in / popularity signals |

### 4.7 Agent Execution Flow

```
VenueDiscoveryAgent.fetch(params)
│
├─ 1. For each country in params.countries (default: 22):
│     └─ WikidataConnector.query_country(country, qid)
│           ├─ Check cache → return if fresh
│           ├─ Rate-limit wait (2 sec between calls)
│           ├─ SPARQL GET → parse JSON bindings
│           ├─ Parse coordinates from WKT
│           ├─ Cache result
│           └─ Return DataFrame
│
├─ 2. For each city in params.cities (default: 18):
│     └─ OSMOverpassConnector.query_city(city)
│           ├─ Check cache → return if fresh
│           ├─ Rate-limit wait (5 sec between calls)
│           ├─ Overpass POST → parse JSON elements
│           ├─ Extract tags for each node/way
│           ├─ Cache result
│           └─ Return DataFrame
│
├─ 3. IF use_google AND api_key configured:
│     └─ For top 5 cities × 3 venue types:
│           └─ GooglePlacesConnector.search_venues(city, country, type)
│                 ├─ Check cache → return if fresh
│                 ├─ Rate-limit wait (1 sec)
│                 ├─ POST to Places API → parse JSON
│                 ├─ Cache result
│                 └─ Return DataFrame
│
├─ 4. pd.concat(all DataFrames)
├─ 5. to_unified_schema(combined) → fill missing columns
└─ 6. Return unified DataFrame
```

### 4.8 Decision Log Entries

| Decision | Reasoning |
|----------|-----------|
| Selected Wikidata + OSM + Google Places | Wikidata: structured global data with Q-IDs for dedup. OSM: granular city-level nightclub/theatre/stadium data. Google Places: most comprehensive type classification. |
| Wikidata rate limited to 0.5 calls/sec | Wikidata enforces strict rate limits; 1 query per 2 seconds prevents HTTP 429 |
| OSM queried at city level, not country | Country-level Overpass queries time out. City-level queries are fast and targeted |
| Google Places limited to 5 cities × 3 types | API costs ~$5/1K calls. 15 queries provides solid coverage for gaps |

---

## 5. Agent 2: Ticketing Intelligence Agent (9+ Sources)

### 5.1 Purpose

Answers the critical question for Tixr's sales team: *"Is this venue locked into an exclusive ticketing deal, and with whom?"* Uses a **sequential fallback hierarchy** across 5 steps, executing each only if the previous step returns no signal. This replaces the earlier parallel multi-signal aggregation model, which produced a VWP default of 0.60 for ~99.7% of venues due to silent join failures and absent enrichment data — rendering the score effectively constant. The fallback design ensures every venue gets the best available signal and surfaces explicitly when none exists.

### 5.2 Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                  TicketingIntelAgent — Fallback Hierarchy               │
│                                                                       │
│  check_venue_exclusivity(venue_name, venue_website, country_code)     │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ Step 1: BuyButtonChecker (requires venue.website)               │  │
│  │   • Fetch venue HTML, scan for 30+ ticketing platform patterns  │  │
│  │   • Requires confidence ≥ 0.85 to stop                          │  │
│  │   • Single platform detected → assign, confidence = 0.95        │  │
│  │   • If no website or confidence < 0.85 → proceed to Step 2      │  │
│  └──────────────────────────── if no result ────────────────────────┘  │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ Step 2: TicketmasterConnector.search_venue(name, country_code)  │  │
│  │   • TM Discovery API v2 venue search                            │  │
│  │   • Match found → assign Ticketmaster, confidence = 0.85        │  │
│  │   • No match → proceed to Step 3                                │  │
│  └──────────────────────────── if no result ────────────────────────┘  │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ Step 3: AXSDirectoryConnector (pre-built directory lookup)      │  │
│  │   • O(1) lookup against pre-scraped axs.com/venues directory    │  │
│  │   • Match found → assign AXS, confidence = 0.90                 │  │
│  │   • No match → proceed to Step 4                                │  │
│  └──────────────────────────── if no result ────────────────────────┘  │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ Step 4: Regional Platform Connector (from REGIONAL_PLATFORMS    │  │
│  │         mapping keyed on venue.country)                         │  │
│  │   Country → Connector:                                          │  │
│  │   DE/AT/CH → EventimConnector (0.85)                            │  │
│  │   AU/NZ    → TicketekConnector (0.85)                           │  │
│  │   UK + EU  → DICEConnector (0.80)                               │  │
│  │   IN + SEA → BookMyShowConnector (0.80)                         │  │
│  │   Gulf/MENA → PlatinumlistConnector (0.80)                      │  │
│  │   Match found → assign platform at connector's default conf.    │  │
│  │   No match → proceed to Step 5                                  │  │
│  └──────────────────────────── if no result ────────────────────────┘  │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ Step 5: Unresolved — flag for manual review                     │  │
│  │   • ticketing_platform = None                                   │  │
│  │   • exclusivity_strength = "Unknown"                            │  │
│  │   • needs_manual_review = True                                  │  │
│  │   • VWP applied per existing lookup table (Unknown case)        │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ── Output per venue ──────────────────────────────────────────────── │
│       └─ {platform, exclusivity_strength, confidence,                 │
│            needs_manual_review, fallback_step_resolved, signals[]}    │
└───────────────────────────────────────────────────────────────────────┘
```

### 5.3 Platform URL Detection Patterns

The system recognizes **30+ ticketing platforms** via regex patterns applied to venue website HTML:

| Platform | URL Patterns | Region | Notes |
|----------|-------------|--------|-------|
| **Ticketmaster** | `ticketmaster.com`, `ticketmaster.co.*`, `am.ticketmaster`, `ticketmaster.de/es/fr` | Global | Includes all regional TM domains |
| **AXS** | `axs.com`, `axs.co.uk` | US/UK | AEG's ticketing platform |
| **SeatGeek** | `seatgeek.com` | US | Challenger platform |
| **Eventim** | `eventim.de`, `eventim.co.*`, `eventim.com` | DACH/Europe | Dominant in Germany |
| **DICE** | `dice.fm` | UK/Europe/US | Electronic music / clubs |
| **Eventbrite** | `eventbrite.com`, `eventbrite.co.*` | Global | Non-exclusive self-serve |
| **See Tickets** | `seetickets.com`, `seetickets.us` | UK | Festivals / grassroots |
| **Ticketek** | `ticketek.com`, `ticketek.com.au`, `ticketek.co.nz` | AU/NZ | TEG's platform |
| **BookMyShow** | `bookmyshow.com` | India/SEA | Dominant in India |
| **Platinumlist** | `platinumlist.net` | Gulf/MENA | UAE, Saudi, etc. |
| **Viagogo** | `viagogo.com` | Global | Secondary market |
| **StubHub** | `stubhub.com` | Global | Secondary market |
| **Punto Ticket** | `puntoticket.com` | LATAM (Chile) | Regional |
| **Passline** | `passline.com` | LATAM (Argentina) | Regional |
| **Eticket4** | `eticket4.com` | LATAM (Mexico) | Regional |
| **TodoTicket** | `todoticket.com` | LATAM (Colombia) | Regional |
| **Tixr** | `tixr.com` | Global | Tixr's own platform |
| **Universe** | `universe.com` | Global | Live Nation subsidiary |
| **TicketSwap** | `ticketswap.com` | Europe | Resale marketplace |
| **Resident Advisor** | `ra.co` | Global | Electronic music |

### 5.4 Connector: TicketmasterConnector

**What it does:** Queries the Ticketmaster Discovery API v2 to check if a venue exists in TM's database. Presence = TM client = likely exclusive or TM-affiliated.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://app.ticketmaster.com/discovery/v2/venues.json` |
| **Auth** | API key (free tier: 5,000 calls/day) |
| **Rate Limit** | 5 calls/sec |
| **Cache TTL** | 168 hours (7 days) |
| **Accuracy** | 85% (some non-exclusive venues appear; some exclusive ones don't) |

**Two operations:**

1. **`search_venue(name, country_code)`** — Keyword search for venue name
   - Returns: `tm_id`, `tm_name`, `tm_city`, `tm_country`, `tm_capacity`, `tm_url`, `tm_lat`, `tm_lng`
   - Name matching: substring check in both directions to handle aliases

2. **`get_venue_events(tm_venue_id)`** — Fetches upcoming events for activity signal
   - Returns: `event_count`, `total_events`, event list with name/date/genre
   - Secondary signal: event volume indicates how active the TM partnership is

### 5.5 Connector: AXSDirectoryConnector

**What it does:** Scrapes the public AXS venue directory at `axs.com/venues` to build a definitive list of AXS partner venues.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://www.axs.com/venues` |
| **Auth** | None (public page) |
| **Method** | HTML scraping with regex |
| **Cache TTL** | 168 hours |
| **Accuracy** | 90% (AXS-owned venues are definitively locked) |

**Scraping approach:**
```python
re.finditer(r'<a[^>]*href="/venues/(\d+)/[^"]*"[^>]*>([^<]+)</a>', html)
```
Extracts `axs_id` and `venue_name` from anchor tags. In production, upgrade to BeautifulSoup for robustness.

### 5.6 Connector: SeatGeekConnector

**What it does:** Scrapes the SeatGeek venue sitemap XML to enumerate all venues with SeatGeek presence.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://seatgeek.com/sitemap/venues` |
| **Auth** | None (public sitemap) |
| **Method** | XML regex extraction |
| **Cache TTL** | 168 hours |
| **Accuracy** | 65% (includes secondary market venues, not just primary clients) |

**Why lower accuracy:** SeatGeek lists venues where tickets are resold, not just venues where SeatGeek is the primary ticketer. Cross-reference with the venue's official website to confirm if primary.

### 5.7 Connector: BuyButtonChecker

**What it does:** The **highest-accuracy** detection method (95%+). Visits a venue's official website and scans the HTML for ticket purchase URLs to determine which platform the venue uses.

| Property | Value |
|----------|-------|
| **Endpoint** | Variable (each venue's website) |
| **Auth** | None |
| **Rate Limit** | 2 calls/sec, 10,000/day |
| **Cache TTL** | 168 hours |
| **Accuracy** | 95% (single platform found) / 60% (multiple platforms) |

**Detection logic:**
```
1. HTTP GET venue_website (User-Agent: Mozilla/5.0)
2. Convert response HTML to lowercase
3. For each of 11 platform patterns:
     If regex matches in HTML → add to platforms_found set
4. Return:
   - platforms_detected: list of all platforms found
   - primary_platform: first platform detected
   - is_exclusive: true if exactly 1 platform found
   - is_multi_platform: true if 2+ platforms found
```

**Why this is the gold standard:** The ticket buy-button is the **definitive** indicator of a venue's ticketing partner. If `ticketmaster.com` is the only ticket link on a venue's website, that venue is a TM exclusive with near-certainty.

**Limitation:** Requires the venue to have a working website with ticket links. ~15% of venues in our dataset have websites.

**Production upgrade path:** Replace `requests.get()` with **Playwright headless browser** to handle:
- JavaScript-rendered ticket widgets
- Iframe-embedded ticket buttons
- Single-page applications (React/Vue)
- Anti-bot protections (Cloudflare, etc.)

### 5.8 Regional Platform Connectors

| Connector | Region | Endpoint | Detection Method |
|-----------|--------|----------|------------------|
| **EventimConnector** | DACH, Europe | `eventim.de/search` | HTML scrape of search results for venue name match |
| **TicketekConnector** | AU, NZ | `ticketek.com.au/search` | HTML scrape of venue search |
| **DICEConnector** | UK, Europe, US | `dice.fm/search` | JSON API search for venue |
| **BookMyShowConnector** | India, SEA | `bookmyshow.com/search` | HTML scrape of venue/event search |
| **PlatinumlistConnector** | Gulf, MENA | `platinumlist.net/search` | HTML scrape of venue listings |

Each regional connector follows the same pattern: search for venue name → if found, assign platform with 0.80–0.85 confidence. The `REGIONAL_PLATFORMS` mapping cross-checks whether the detected platform is the **expected default** for that country (e.g., Eventim in Germany boosts confidence).

### 5.9 Fallback Hierarchy Execution Logic

Each step executes only if all previous steps returned no signal. The first step to resolve stops the chain and logs the resolution.

```python
def check_venue_exclusivity(venue_name, venue_website, country_code):
    result = None

    # Step 1: BuyButtonChecker — highest accuracy, requires website
    if venue_website:
        detected = BuyButtonChecker.check(venue_website)
        if detected.confidence >= 0.85:
            result = {
                "platform": detected.primary_platform,
                "exclusivity_strength": _map_strength(detected),
                "confidence": detected.confidence,
                "fallback_step_resolved": 1,
                "needs_manual_review": False
            }
            log_decision(f"Exclusivity resolved at Step 1 via BuyButtonChecker")
            return result

    # Step 2: Ticketmaster API
    if result is None:
        tm_match = TicketmasterConnector.search_venue(venue_name, country_code)
        if tm_match:
            result = {
                "platform": "Ticketmaster",
                "exclusivity_strength": "Strong",
                "confidence": 0.85,
                "fallback_step_resolved": 2,
                "needs_manual_review": False
            }
            log_decision(f"Exclusivity resolved at Step 2 via TicketmasterConnector")
            return result

    # Step 3: AXS Directory lookup (pre-built, O(1))
    if result is None:
        axs_match = AXSDirectoryConnector.lookup(venue_name)
        if axs_match:
            result = {
                "platform": "AXS",
                "exclusivity_strength": "Strong",
                "confidence": 0.90,
                "fallback_step_resolved": 3,
                "needs_manual_review": False
            }
            log_decision(f"Exclusivity resolved at Step 3 via AXSDirectoryConnector")
            return result

    # Step 4: Regional platform connector based on country
    if result is None:
        regional_connector = REGIONAL_PLATFORMS.get(country_code)
        if regional_connector:
            regional_match = regional_connector.search_venue(venue_name)
            if regional_match:
                result = {
                    "platform": regional_match.platform,
                    "exclusivity_strength": "Medium",
                    "confidence": regional_connector.default_confidence,
                    "fallback_step_resolved": 4,
                    "needs_manual_review": False
                }
                log_decision(f"Exclusivity resolved at Step 4 via {regional_connector.__class__.__name__}")
                return result

    # Step 5: No signal from any source
    log_decision("Exclusivity unresolved after all 4 steps — flagged for manual review")
    return {
        "platform": None,
        "exclusivity_strength": "Unknown",
        "confidence": 0.0,
        "fallback_step_resolved": 5,
        "needs_manual_review": True
    }
```

**Exclusivity strength mapping from BuyButtonChecker result:**

| BuyButtonChecker outcome | exclusivity_strength |
|--------------------------|----------------------|
| Single platform detected (confidence ≥ 0.95) | Strong |
| Single platform detected (confidence 0.85–0.94) | Medium |
| Multiple platforms detected | Weak |

**Why sequential over parallel:** The original parallel aggregation model ran all 9 connectors on every venue and summed confidence scores. In practice, most venues had no website (limiting BuyButtonChecker) and the name-based join between the Ticketing Agent's output and the discovery dataset was fragile — resulting in 99.1% null `ticketing_platform` in the prototype. The fallback hierarchy makes the resolution path explicit and auditable, reduces unnecessary API calls, and surfaces the gap (Step 5) rather than silently assigning a default VWP of 0.60 that obscures the missing signal.

**SeatGeek note:** SeatGeekConnector is no longer in the fallback chain. At 65% accuracy (secondary market resale, not primary ticketer), it introduced too much noise. It is retained for batch directory builds only — not for per-venue exclusivity decisions.

### 5.10 Batch Directory Build

`build_platform_directories()` pre-scrapes AXS and SeatGeek to create a fast lookup table:

```
directory = {
  "the o2 arena": "AXS",
  "ovo arena wembley": "AXS",
  "madison square garden": "SeatGeek",
  ...
}
```

This enables O(1) lookup during bulk venue processing instead of per-venue API calls.

### 5.11 Decision Log Entries

Every venue processed by the agent generates a structured log entry recording which step resolved the exclusivity signal (or confirmed it could not be resolved):

**Log format:**
- `"Exclusivity resolved at Step {n} via {source}"` — for Steps 1–4
- `"Exclusivity unresolved after all 4 steps — flagged for manual review"` — for Step 5

**Design decisions:**

| Decision | Reasoning |
|----------|-----------|
| Sequential over parallel signal aggregation | Parallel aggregation ran all 9 connectors on every venue, but the confidence-summing model produced a silent VWP default (0.60) for 99.7% of venues when the downstream join failed. Sequential makes the resolution path auditable and short-circuits unnecessary API calls. |
| BuyButtonChecker at Step 1 | It is the highest-accuracy method (95%) and the most direct ground truth — the ticket URL is what a fan actually clicks. It runs first for any venue with a website. |
| TM API at Step 2 (before AXS directory) | TM API is a live query that validates current partnership. AXS directory is a pre-scraped snapshot; TM API is fresher but costs more API quota, so BuyButton (which costs no quota) runs first. |
| AXS directory at Step 3 | Definitive for AXS-partner venues at 90% accuracy and zero API cost (pre-built lookup). Runs before regional connectors since AXS operates globally. |
| Regional connectors at Step 4 | Only triggered if no global platform signal exists. Country-keyed to avoid false positives (e.g., running EventimConnector on a Singapore venue). |
| needs_manual_review = True only at Step 5 | Partial signals (Steps 2–4) are meaningful even without a website. The flag is not about low confidence — it specifically marks venues where no detection method found anything, warranting a human check before outreach. |
| SeatGeekConnector removed from chain | 65% accuracy (includes secondary market resale, not just primary partnerships). Introduces false positives that inflate exclusivity estimates. Retained for batch directory exploration only. |

---

## 6. Agent 3: Event Enrichment Agent (7 Sources)

### 6.1 Purpose

Answers: *"How active is this venue? What kind of events does it host? Is it a thriving destination or a dormant facility?"* Enriches venues with **event cadence signals** from 7 sources spanning upcoming events, historical data, demand intelligence, and genre classification.

### 6.2 Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                  EventEnrichmentAgent (7 Sources)                       │
│                                                                       │
│  enrich_venue(venue_name, city) ──────────────────┐                   │
│       │                                            │                  │
│       ├─→ [1] SongkickConnector                    │                  │
│       │     • Upcoming events count                │                  │
│       │     • 2 calls/sec, global coverage         │                  │
│       │                                            │                  │
│       ├─→ [2] SetlistFmConnector                   │                  │
│       │     • Historical event frequency           ├→ Compute         │
│       │     • Recent artists, tour data            │  event_cadence   │
│       │                                            │  _score          │
│       ├─→ [3] EventbriteConnector                  │                  │
│       │     • International event coverage         │  Formula:        │
│       │     • Capacity gap-fill                    │  upcoming (30%)  │
│       │                                            │  + historical    │
│       ├─→ [4] BandsintownEventsConnector (NEW)     │    (25%)         │
│       │     • Artist-driven event data             │  + demand (20%)  │
│       │     • Lineup and genre signals             │  + genre (25%)   │
│       │                                            │                  │
│       ├─→ [5] PredictHQEventsConnector (NEW)       │  Activity Level: │
│       │     • Demand rank / attendance estimates    │  ≥0.7 → High    │
│       │     • Predicted event attendance            │  ≥0.3 → Moderate│
│       │                                            │  >0   → Low     │
│       ├─→ [6] SkiddleConnector (NEW)               │  else → Unknown │
│       │     • UK regional event coverage           │                  │
│       │     • Genre + festival data                │                  │
│       │                                            │                  │
│       └─→ [7] ResidentAdvisorConnector             │                  │
│             • Electronic music clubs (GraphQL)     │                  │
│             • 10+ cities, premium nightlife        │                  │
└───────────────────────────────────────────────────────────────────────┘
```

### 6.3 Connector: SongkickConnector

**What it does:** Queries Songkick's concert database for **upcoming events** at a venue — the primary "activity" signal.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://api.songkick.com/api/3.0` |
| **Auth** | API key required (free tier) |
| **Rate Limit** | 2 calls/sec, 10,000/day |
| **Cache TTL** | 168 hours (venue search) / 24 hours (events) |
| **Coverage** | Global — 6M+ concerts indexed |

**Two-step flow per venue:**

1. **`search_venue(venue_name)`** → Returns up to 3 matches with:
   - `sk_id` (Songkick venue ID)
   - `sk_name`, `sk_city`, `sk_country`
   - `sk_capacity` (often populated where Wikidata is empty)
   - `sk_uri` (Songkick venue page URL)
   - `sk_lat`, `sk_lng`

2. **`get_venue_events(sk_venue_id)`** → Returns:
   - `upcoming_count`: number of upcoming events
   - `total`: total scheduled events
   - `events[]`: list of event name, date, type, popularity, ticket_url

**Name matching strategy:**
```python
# Bidirectional substring match to handle aliases
if venue_name.lower() in sk_name.lower() or sk_name.lower() in venue_name.lower():
    # Match found → proceed to get events
```

### 6.4 Connector: SetlistFmConnector

**What it does:** Queries Setlist.fm's historical concert database for **past event frequency** — indicates how consistently active a venue has been over years.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://api.setlist.fm/rest/1.0` |
| **Auth** | API key via `x-api-key` header (free, non-commercial) |
| **Rate Limit** | 2 calls/sec, 5,000/day |
| **Cache TTL** | 168 hours |
| **Coverage** | Global — community-contributed setlist database |

**Two-step flow per venue:**

1. **`search_venue(venue_name, city)`** → Returns:
   - `sfm_id`, `sfm_name`, `sfm_city`, `sfm_country`

2. **`get_venue_setlists(sfm_venue_id)`** → Returns:
   - `total_historical_events`: total setlists ever recorded at this venue
   - `recent_events[]`: last 10 events with artist, date, tour name

**Why historical data matters:** A venue with 500+ historical setlists is a **proven, active concert venue**. A venue with 5 setlists might be a multi-use facility that rarely hosts music. This directly feeds the Tixr "activity level" enrichment.

### 6.5 Connector: EventbriteConnector

**What it does:** Queries Eventbrite's API for events at/near a venue, providing international coverage especially for non-music events (comedy, immersive, corporate).

| Property | Value |
|----------|-------|
| **Endpoint** | `https://www.eventbriteapi.com/v3/events/search/` |
| **Auth** | OAuth Bearer token |
| **Rate Limit** | 5 calls/sec, 1,000/day |
| **Cache TTL** | 168 hours |
| **Coverage** | Global — 180+ countries |

**Returns per venue:**
- `eb_id`, `venue_name`, `city`, `country`
- `capacity` (often available where other sources miss)
- `latitude`, `longitude`
- `address` (localized)

### 6.6 New Connectors (Bandsintown, PredictHQ, Skiddle)

| Connector | Endpoint | Auth | Rate Limit | Coverage |
|-----------|----------|------|------------|----------|
| **BandsintownEvents** | `https://rest.bandsintown.com/artists/{}/events` | App ID | 1 call/sec | Global — artist-driven event lookups |
| **PredictHQEvents** | `https://api.predicthq.com/v1/events` | Bearer token | 2 calls/sec | Global — demand rank, attendance estimates |
| **Skiddle** | `https://www.skiddle.com/api/v1/events` | API key | 2 calls/sec | UK — regional events, festivals, genre data |

### 6.7 Connector: ResidentAdvisorConnector

**What it does:** Scrapes Resident Advisor's GraphQL API for **electronic music clubs** — a premium nightlife segment that Tixr targets, not well-covered by mainstream APIs.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://ra.co/graphql` |
| **Auth** | None (GraphQL is public, use referer header) |
| **Rate Limit** | 0.5 calls/sec, 500/day |
| **Cache TTL** | 168 hours |
| **Coverage** | Global electronic music — 30+ cities |

**GraphQL Query:**
```graphql
query GET_POPULAR_VENUES($filters: VenueFilters) {
  listing(filters: $filters) {
    data {
      id, name, address, contentUrl
      area { name country { name } }
    }
    totalResults
  }
}
```

**Variables:** `{ filters: { areas: { eq: "london" }, pageSize: 50 } }`

**Default cities queried (10 electronic music hubs):**
```
london, berlin, amsterdam, paris, barcelona,
tokyo, bangkok, singapore, jakarta, dubai
```

**Why RA matters:** Venues like Berghain (Berlin), Fabric (London), and Printworks (London) are premium independent venues — **exactly Tixr's target segment**. These rarely appear in Ticketmaster or Songkick data but are high-value targets.

### 6.8 Event Cadence Scoring Model

The agent computes an `event_cadence_score` (0.0–1.0) for each venue:

```
upcoming_score   = min(upcoming_events_count / 50, 1.0)
historical_score = min(historical_events_count / 500, 1.0)

event_cadence_score = 0.6 × upcoming_score + 0.4 × historical_score
```

| Benchmark | Score |
|-----------|-------|
| 50+ upcoming events | upcoming_score = 1.0 (max) |
| 500+ historical events | historical_score = 1.0 (max) |
| **Weighting** | 60% upcoming (current relevance) / 40% historical (proven track record) |

**Activity Level Classification:**

| Score Range | Level | Interpretation |
|-------------|-------|---------------|
| ≥ 0.70 | **High** | Active concert venue, regular programming |
| 0.30 – 0.69 | **Moderate** | Periodic events, seasonal programming |
| 0.01 – 0.29 | **Low** | Occasional events, mostly dormant |
| 0.00 | **Unknown** | No event data found from any source |

### 6.9 Decision Log Entries

| Decision | Reasoning |
|----------|-----------|
| Songkick weighted 60% (upcoming), Setlist.fm 40% (historical) | Upcoming events are more relevant for Tixr sales — they indicate current activity and near-term opportunity. Historical depth validates the venue is consistently active. |
| RA scraped separately from per-venue enrichment | RA data is city-level discovery (finding new clubs) rather than enriching known venues. It feeds new venues into the pipeline. |
| Eventbrite used for capacity gap-fill | Eventbrite often has capacity data where Wikidata/OSM don't. It supplements discovery, not just enrichment. |
| Name matching uses bidirectional substring | Venue names vary across platforms (e.g., "The O2" vs "O2 Arena London"). Substring matching in both directions catches most aliases. |

---

## 7. Stage 2 — Recommendation Engine

### 7.1 Purpose

The **Recommendation Engine** is a separate module (`recommendation_engine.py`) that consumes the enriched venue DataFrame from Stage 1 and applies market-level intelligence to produce **scored, tiered recommendations** for Tixr's sales team. It answers: *"Which countries/markets should Tixr prioritize, and which venues should be contacted first?"*

### 7.2 Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                    RecommendationEngine (Stage 2)                       │
│                                                                       │
│  generate_recommendations(venues_df, config)                          │
│       │                                                               │
│       ├─→ [1] MarketIntelAgent                                        │
│       │     ├─→ WorldBankConnector                                    │
│       │     │     • 6 indicators × 47 countries                       │
│       │     │     • Free API, no auth, 30-day cache                   │
│       │     └─→ FoursquareConnector (optional)                        │
│       │           • Venue popularity / check-in signals               │
│       │                                                               │
│       ├─→ [2] enrich_with_market_data()                               │
│       │     • Left-join market scores onto venues by country          │
│       │     • Adds: market_score, GDP, internet %, tourism, etc.      │
│       │                                                               │
│       ├─→ [3] compute_recommendation_score()                          │
│       │     • 50% priority_score (from Stage 1)                       │
│       │     • 30% market_score (from World Bank)                      │
│       │     • 20% activity_bonus (from event cadence)                 │
│       │                                                               │
│       └─→ [4] assign_tier()                                           │
│             • Tier 1 — Immediate Outreach (≥70)                       │
│             • Tier 2 — High Priority (≥50)                            │
│             • Tier 3 — Monitor (≥30)                                  │
│             • Tier 4 — Low Priority (<30)                             │
│                                                                       │
│  Output: tixr_recommendations.xlsx                                    │
│    Sheets: All_Recommendations, Tier1_Immediate, Tier2_High_Priority, │
│            Market_Intelligence, Region_Summary, Country_Breakdown,     │
│            Manual_Review_Required, Decision_Log                        │
└───────────────────────────────────────────────────────────────────────┘
```

### 7.2b Export: export_recommendations() — Conditional Formatting

`export_recommendations()` in `stage2/export.py` applies the following formatting rules via openpyxl after writing all rows:

**Amber highlight rule:** Any row where `needs_manual_review = True` AND `recommendation_tier = "Tier 1 — Immediate Outreach"` receives an amber fill (`PatternFill(fgColor="FFB347")`). This flags venues that scored high enough for immediate outreach but have no confirmed exclusivity signal — a sales rep should not call without first manually verifying the ticketing situation.

**review_reason column:** A column called `review_reason` is appended to the export. It is populated only for rows meeting both conditions above; value is always `"No exclusivity signal detected"`. All other rows receive an empty string.

**Manual_Review_Required sheet:** A dedicated sheet is added containing only venues where `needs_manual_review = True`, sorted by `recommendation_score` descending, so the ops team has a single-sheet work queue.

```python
# openpyxl conditional formatting — applied in export_recommendations()
amber_fill = PatternFill(start_color="FFB347", end_color="FFB347", fill_type="solid")

for row in ws.iter_rows(min_row=2):
    needs_review = row[col_idx["needs_manual_review"]].value
    tier = row[col_idx["recommendation_tier"]].value
    if needs_review and tier == "Tier 1 — Immediate Outreach":
        for cell in row:
            cell.fill = amber_fill
        row[col_idx["review_reason"]].value = "No exclusivity signal detected"
```

### 7.3 Connector: WorldBankConnector

**What it does:** Fetches authoritative country-level economic indicators from the World Bank Open Data API — the standard source for macroeconomic data used by governments and institutions.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}` |
| **Auth** | None required |
| **Rate Limit** | 2 calls/sec, 1,000/day |
| **Cache TTL** | 720 hours (30 days — data is annual) |
| **Coverage** | 200+ countries, 1,400+ indicators |

**Indicators Fetched:**

| Indicator | WB Code | Tixr Use | Benchmark |
|-----------|---------|----------|-----------|
| **GDP per capita (USD)** | `NY.GDP.PCAP.CD` | Spending power for premium tickets | $80K = max score |
| **Internet users (%)** | `IT.NET.USER.ZS` | Digital readiness for online ticketing | 100% = max score |
| **Mobile subscriptions / 100** | `IT.CEL.SETS.P2` | Mobile ticketing adoption potential | 200 = max score |
| **Tourism arrivals** | `ST.INT.ARVL` | Event demand proxy (tourists attend events) | 50M = max score |
| **Total population** | `SP.POP.TOTL` | Total addressable market size | 500M = max score |
| **Urban population (%)** | `SP.URB.TOTL.IN.ZS` | Concentration in cities with venues | 100% = max score |

**Target Countries (47 across all regions):**

| Region | Count | Countries |
|--------|-------|-----------|
| EMEA | 17 | UK, Germany, France, Spain, Italy, Netherlands, Belgium, Sweden, Norway, Denmark, Finland, Austria, Switzerland, Poland, Czech Republic, Portugal, Ireland, Greece, Turkey |
| EMEA_Gulf | 7 | UAE, Saudi Arabia, Qatar, Bahrain, Kuwait, Oman, Israel |
| EMEA_Africa | 5 | Egypt, South Africa, Nigeria, Kenya, Morocco |
| APAC | 6 | Japan, Australia, India, South Korea, China, New Zealand |
| LATAM | 6 | Brazil, Mexico, Argentina, Colombia, Chile, Peru |
| SEA | 6 | Thailand, Indonesia, Singapore, Malaysia, Philippines, Vietnam, Cambodia, Myanmar |

**API Call Pattern:**

```
GET /v2/country/JP;AU;DE;GB;.../indicator/NY.GDP.PCAP.CD?date=2022&format=json&per_page=100
```

Countries are semicolon-separated. One call fetches all countries for one indicator. Total: **6 API calls** for all indicators.

### 7.4 Connector: FoursquareConnector

**What it does:** Provides **venue-level popularity signals** — check-in counts, ratings, and category classifications from Foursquare's 100K+ source places database.

| Property | Value |
|----------|-------|
| **Endpoint** | `https://api.foursquare.com/v3/places/search` |
| **Auth** | API key via `Authorization` header |
| **Rate Limit** | 5 calls/sec, 500/day |
| **Cache TTL** | 168 hours |
| **Coverage** | Global |

**Venue categories mapped:**

| Category | FSQ ID | Use |
|----------|--------|-----|
| Concert Hall | 10039 | Core venue type |
| Stadium | 18021 | Large venue |
| Nightclub | 10032 | Nightlife segment |
| Music Venue | 10039 | Core venue type |
| Performing Arts | 10041 | Theatre/comedy |

**Returns per venue:**
- `fsq_id`, `fsq_name`
- `fsq_categories[]` — full Foursquare taxonomy
- `fsq_rating` — user rating (0-10)
- `fsq_popularity` — relative popularity score
- `fsq_lat`, `fsq_lng`, `fsq_address`

### 7.5 Market Score Model

The `compute_market_score()` function produces a **composite market attractiveness score (0–100)**:

```
market_score = 0.25 × gdp_norm
             + 0.20 × internet_norm
             + 0.15 × mobile_norm
             + 0.20 × tourism_norm
             + 0.10 × urban_norm
             + 0.10 × population_norm
```

**Normalization functions:**

| Indicator | Normalization | Benchmark |
|-----------|--------------|-----------|
| GDP per capita | `min(gdp / 80000 × 100, 100)` | Singapore ($85K) ≈ 100 |
| Internet users | Raw % (already 0-100) | UAE (100%) = 100 |
| Mobile subs | `min(mobile / 200 × 100, 100)` | UAE (199) ≈ 100 |
| Tourism | `min(arrivals / 50M × 100, 100)` | France (117M) = 100 |
| Urban pop | Raw % (already 0-100) | Singapore (100%) = 100 |
| Population | `min(pop / 500M × 100, 100)` | India (1.4B) = 100 |

**Weight Justification (aligned with Tixr's expansion criteria):**

| Weight | Indicator | Why |
|--------|-----------|-----|
| **25%** | GDP per capita | Higher GDP → higher willingness to pay for premium tickets. Tixr positions as premium. |
| **20%** | Internet users | Digital infrastructure is prerequisite for online ticketing platform adoption. |
| **15%** | Mobile subscriptions | Tixr's mobile-first UX. Higher mobile penetration → better adoption. |
| **20%** | Tourism arrivals | Tourists drive event demand. Markets with high tourism have more events and higher willingness to spend. |
| **10%** | Urban population | Venues are concentrated in cities. Higher urbanization → larger addressable market per city. |
| **10%** | Total population | Raw market size. Gives weight to large emerging markets (India, Brazil, Indonesia). |

### 7.6 Example Market Scores

| Country | GDP | Internet | Mobile | Tourism | Urban | Pop | **Score** |
|---------|-----|----------|--------|---------|-------|-----|-----------|
| Singapore | 100 | 94 | 87 | 5 | 100 | 0 | **63.4** |
| UK | 62 | 96 | 61 | 22 | 84 | 14 | **55.8** |
| France | 56 | 87 | 58 | 100 | 81 | 14 | **63.1** |
| Thailand | 9 | 90 | 84 | 80 | 52 | 14 | **48.8** |
| Brazil | 13 | 84 | 51 | 13 | 87 | 43 | **39.4** |

### 7.7 Recommendation Score Model

The `compute_recommendation_score()` blends venue-level and market-level signals:

```
recommendation_score = 0.50 × priority_score   (from Stage 1: VWP + Premium Fit + completeness)
                     + 0.30 × market_score     (from World Bank: GDP, internet, tourism)
                     + 0.20 × activity_bonus    (from event cadence: High=1.0, Moderate=0.6, Low=0.3)
```

**Tier Assignment:**

| Score Range | Tier | Action |
|-------------|------|--------|
| ≥ 70 | **Tier 1 — Immediate Outreach** | Sales rep contacts this week |
| 50–69 | **Tier 2 — High Priority** | Queue for next sprint |
| 30–49 | **Tier 3 — Monitor** | Track for market changes |
| < 30 | **Tier 4 — Low Priority** | Revisit quarterly |

### 7.8 Decision Log Entries

| Decision | Reasoning |
|----------|-----------|
| World Bank as primary market data source | Authoritative, free, comprehensive. Same source used by McKinsey, BCG for market analysis. |
| GDP weighted highest (25%) in market_score | Tixr is premium-positioned. Markets with high spending power are higher-value targets. |
| Tourism weighted equal to internet (20%) | Tourism is a direct proxy for live event demand. Tourists buy tickets. |
| GDP removed from priority_score formula | GDP appeared in both priority_score (15% weight) and market_score (25% weight), with market_score itself contributing 30% to recommendation_score. This double-counted economic position and inflated Singapore/UAE venues unfairly. GDP is now only factored through market_score. |
| Foursquare is optional | Venue-level popularity is nice-to-have but not essential for market-level scoring. Saves API costs. |
| 30-day cache for World Bank | Data is annual; no need to re-fetch more than monthly. |
| World Bank join validated before scoring | In the prototype run, the left-join on `country` silently failed, producing market_score = 0 for all 21,205 venues and capping recommendation_score at 60 — below the Tier 1 threshold of 70. Join must be validated with an assertion before scoring proceeds. |

---

## 7b. End-to-End Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  run_pipeline.py                                                     │
│                                                                     │
│  Phase 1: normalize_data.py → unified local DataFrame               │
│                    │                                                │
│  Phase 2: Orchestrator (Stage 1)                                    │
│    ├─ VenueDiscovery (7 sources) → venues_df                       │
│    ├─ TicketingIntel (fallback hierarchy, Steps 1–5) → excl_df     │
│    ├─ EventEnrichment (7 sources) → enriched_df                    │
│    └─ merge_results() → enriched venue DataFrame                   │
│         └─ [VALIDATE: assert null rate < 50% on ticketing_platform]│
│                    │                                                │
│  Phase 3: compute_tixr_scores() → VWP + Premium Fit + Priority     │
│                    │                                                │
│  Phase 4: export_final_excel() → tixr_normalized_venues.xlsx       │
│                    │                                                │
│  Phase 5 (optional): RecommendationEngine (Stage 2)                │
│    ├─ MarketIntelAgent (World Bank + Foursquare) → market_df       │
│    ├─ [VALIDATE: assert market_df.market_score.isna().sum() == 0]  │
│    ├─ enrich_with_market_data() → left-join on country             │
│    ├─ compute_recommendation_score() → blended score               │
│    ├─ assign_tier() → Tier 1-4                                     │
│    └─ export_recommendations() → tixr_recommendations.xlsx         │
│         └─ amber highlight for Tier 1 + needs_manual_review rows   │
└─────────────────────────────────────────────────────────────────────┘
```

**Pipeline validation gates:** Two assertions are added after the merge steps to catch silent failures before scoring:
- After Stage 1 merge: if `ticketing_platform` null rate exceeds 50%, the pipeline raises a warning and logs the join failure. In the prototype run this reached 99.1% — the TM/AXS/Buy-button data was collected but failed to join on `venue_name`.
- After Stage 2 World Bank join: if `market_score` is null or 0 for all venues, the pipeline halts rather than producing a report where no Tier 1 result is possible. In the prototype run this silently capped `recommendation_score` at 60 across all 21,205 venues.

### Merge Strategy

**Stage 1 (Orchestrator):** Results merged via left-join on `venue_name` with suffix handling:
1. **Base** = VenueDiscovery output (all venues)
2. **+ Exclusivity** = left-join on `venue_name`, prefer new exclusivity data
3. **+ Enrichment** = left-join on `venue_name`, prefer new event data

**Known limitation:** Using `venue_name` as the join key is fragile — the same venue appears under different names across platforms ("The O2" vs "O2 Arena London"). Any mismatch silently produces a null row for enrichment columns. In the prototype run, this contributed to 99.1% null `ticketing_platform` values: the Ticketing Agent returned data that failed to join back to the base DataFrame. Production upgrade: use a composite key of normalized venue name + city + country, with fuzzy fallback via the `dedupe` library.

**Stage 2 (RecommendationEngine):** Market data merged via left-join on `country`, adding economic indicators to every venue row. `needs_manual_review`, `fallback_step_resolved`, and `review_reason` are carried through unchanged.

---

## 8. Data Flow & Unified Schema

### Complete field inventory (36 columns in final output):

| # | Column | Type | Source Agent(s) | Tixr Use |
|---|--------|------|----------------|----------|
| 1 | `venue_id` | string | Discovery | Unique key for CRM integration |
| 2 | `venue_name` | string | Discovery | Display name |
| 3 | `city` | string | Discovery / OSM | Location filter |
| 4 | `country` | string | Discovery | Market assignment |
| 5 | `region` | string | All | EMEA/APAC/LATAM/SEA filter |
| 6 | `venue_type` | string | Discovery | stadium/arena/theatre/nightclub/etc. |
| 7 | `capacity` | int | Discovery | Capacity tier filter |
| 8 | `capacity_tier` | string | Computed | Mega/Major/Mid/Small/Boutique |
| 9 | `latitude` | float | Discovery | Map visualization |
| 10 | `longitude` | float | Discovery | Map visualization |
| 11 | `address` | string | OSM / Google | Full address |
| 12 | `website` | string | Discovery | Outreach + buy-button check |
| 13 | `booking_url` | string | Country files | Direct ticket purchase URL |
| 14 | `google_maps_url` | string | Country files | Location verification |
| 15 | `venue_operator` | string | Discovery / OSM | Operator intelligence |
| 16 | `event_types` | string | Enrichment | concerts/sports/esports/comedy |
| 17 | `ticketing_platform` | string | Ticketing Intel | TM/AXS/DICE/SeatGeek/etc. |
| 18 | `exclusivity_strength` | string | Ticketing Intel | Strong/Medium/Weak/Unknown |
| 19 | `contract_status` | string | Ground truth | Active/Expired/Unknown |
| 20 | `past_events` | JSON | Enrichment | Historical event data |
| 21 | `upcoming_events` | JSON | Enrichment | Future event calendar |
| 22 | `opening_hours` | string | OSM | Operational hours |
| 23 | `phone` | string | OSM | Contact info |
| 24 | `notes` | string | Various | Free-text notes |
| 25 | `data_sources` | string | All | Pipe-delimited source list |
| 26 | `wikidata_id` | string | Discovery | Cross-reference key |
| 27 | `osm_id` | string | OSM | Cross-reference key |
| 28 | `source_urls` | string | Country files | Reference URLs |
| 29 | `gdp_per_capita_usd` | float | Market Intel | Market scoring |
| 30 | `internet_users_pct` | float | Market Intel | Market scoring |
| 31 | `mobile_subscriptions_per_100` | float | Market Intel | Market scoring |
| 32 | `tourism_arrivals` | float | Market Intel | Market scoring |
| 33 | `venue_win_probability` | float | Scoring (Stage 1) | 0–1 VWP |
| 34 | `premium_fit_score` | int | Scoring (Stage 1) | 0–100 fit score |
| 35 | `data_completeness_pct` | float | Scoring (Stage 1) | % of key fields filled |
| 36 | `priority_score` | float | Scoring (Stage 1) | 0–100 composite rank |
| 37 | `market_score` | float | Recommendation Engine (Stage 2) | 0–100 market attractiveness |
| 38 | `recommendation_score` | float | Recommendation Engine (Stage 2) | 0–100 blended final score |
| 39 | `recommendation_tier` | string | Recommendation Engine (Stage 2) | Tier 1–4 action label |
| 40 | `needs_manual_review` | bool | Ticketing Intel (Stage 1) | True when all 4 fallback steps return no signal |
| 41 | `fallback_step_resolved` | int | Ticketing Intel (Stage 1) | Step number (1–5) at which exclusivity was determined |
| 42 | `review_reason` | string | Export layer (Stage 2) | Populated only for Tier 1 rows where needs_manual_review = True; value: "No exclusivity signal detected" |

---

## 9. Scoring Models

### 9.1 Venue Win Probability (VWP)

Estimates the likelihood that Tixr can **realistically win** a venue (i.e., the venue is NOT locked into a competitor's exclusive deal).

| Exclusivity Strength | Platform | VWP | Interpretation |
|---------------------|----------|-----|----------------|
| Strong | Ticketmaster or AXS | 0.05 | Near-impossible — long-term exclusive |
| Strong | Other | 0.15 | Difficult — but non-TM/AXS deals are weaker |
| Medium | Any | 0.40 | Possible — contract may be expiring or negotiable |
| Weak | Any | 0.70 | Good opportunity — loose partnership |
| None / Unknown | Has a platform | 0.30 | Unknown risk — platform detected but strength unclear |
| None / Unknown | No platform detected | 0.65 | **Prime opportunity** — no known exclusivity |

### 9.2 Premium Fit Score (0–100)

Scores how well a venue matches Tixr's premium positioning:

| Factor | Points | Logic |
|--------|--------|-------|
| Base | 40 | Every venue starts at 40 |
| Capacity 1K–5K | +25 | Tixr's sweet spot: boutique premium |
| Capacity 5K–20K | +20 | Mid-size premium |
| Capacity 20K+ | +10 | Large — often locked by TM/AXS |
| Capacity <1K | +5 | Very small — limited revenue |
| Has website | +10 | Digital presence = operational venue |
| Has coordinates | +5 | Verifiable location |
| Premium type (arena, concert_hall, amphitheatre, music_venue, events_venue) | +10 | Core Tixr venue categories |
| Has booking URL | +5 | Currently selling tickets |
| Has operator data | +5 | Known business contact |
| **Max** | **100** | |

### 9.3 Priority Score (0–100)

The **final composite score** used to rank venues for the sales team at the end of Stage 1:

```
raw_priority = 0.40 × (VWP × 100)
             + 0.40 × premium_fit_score
             + 0.20 × data_completeness_pct

priority_score = (raw_priority / max_raw_priority) × 100  # normalized to 0-100
```

| Weight | Component | Why |
|--------|-----------|-----|
| **40%** | VWP | No point pursuing locked venues — winnability is paramount |
| **40%** | Premium Fit | Tixr needs venues that match its premium brand |
| **20%** | Data Completeness | Better data = more actionable lead for sales |

**Note:** GDP per capita was removed from this formula. It previously contributed 15% (`0.15 × gdp_per_capita / 1000`), but this created double-counting: GDP also drives 25% of `market_score`, which feeds 30% of `recommendation_score`. Removing it here concentrates economic weighting in Stage 2 where it belongs — market attractiveness is a market-level signal, not a venue-level signal. The removed weight was redistributed equally to VWP and Premium Fit.

---

---

## 10. Known Issues — Prototype Run (v0.1)

This section documents issues identified in the first prototype run (24,365 venues, EMEA/SEA data). These are carried as decision log entries and inform the v0.2 roadmap.

### 10.1 Pipeline Failures Observed

| Issue | Observed Impact | Root Cause | Fix |
|-------|----------------|------------|-----|
| **Ticketing platform null rate: 99.1%** | 24,132 of 24,365 venues had null `ticketing_platform`. VWP defaulted to 0.60 for 99.7% of venues, becoming a constant rather than a signal. | Stage 1 merge joined on `venue_name` only; name format differences (e.g. "The O2" vs "O2 Arena London") caused silent null joins. Ticketing Agent data was collected but never matched. | Replaced with fallback hierarchy (Section 5.9). Added composite join key (name + city + country) with fuzzy fallback. |
| **market_score = 0 for all venues** | World Bank join silently failed. All 21,205 venues scored market_score = 0.0. This removed 30% of the recommendation formula and capped recommendation_score at 60 — making Tier 1 (threshold: 70) mathematically unreachable. | Left-join on `country` failed due to country name format mismatch between the venue DataFrame (full names) and World Bank response (ISO codes / different casing). | Added join validation assertion. Added country name → ISO code normalization before join. |
| **Event data null rate: 93.4%** | 22,770 of 24,365 venues had null `upcoming_events` and `past_events`. activity_bonus contributed 0 for most venues, removing 20% of recommendation scoring. | EventEnrichment Agent ran against a different venue universe than the base DataFrame, or rate limits caused silent failure during the prototype run. | Added null-rate threshold check after enrichment merge. Enrichment now logs count of matched vs unmatched venues. |
| **VWP default value 0.60 not in lookup table** | The documented VWP lookup table lists values of 0.05, 0.15, 0.40, 0.70, 0.30, and 0.65 — 0.60 does not appear. Yet 99.7% of venues received 0.60. | A fallback code path outside the documented table was running for the Unknown/no-platform case. | Fallback hierarchy (Section 5.9) makes the Unknown case explicit: VWP applied from the existing table per documented rules. The undocumented 0.60 default is removed. |

### 10.2 Model Design Issues Addressed

| Issue | Impact | Resolution |
|-------|--------|------------|
| **GDP double-counted** | High-GDP markets (Singapore, UAE) received credit in both priority_score (15%) and market_score (25%), inflating their venues in final ranking. | GDP removed from priority_score. Weight redistributed to VWP (+5%) and Premium Fit (+5%). GDP now only influences recommendation_score through market_score. |
| **Premium Fit 40-point base floor** | 75% of venues scored 45–55 out of 100. The 40-point floor compressed differentiation and made the score less informative for sales. A venue with no website, unknown capacity, and no operator still scored 40. | Base floor remains at 40 to ensure all venues receive a non-zero score, but this is flagged as a known compression issue. Future version: replace with 0-base and add a "data completeness penalty" for missing critical fields. |
| **Capacity missing for 79% of venues** | 19,332 venues had null capacity. Since Premium Fit awards 5–25 points on capacity bands, the majority clustered at the base score. Tixr's sweet-spot identification (1K–5K) relies on this field. | Capacity gap-fill added: EventbriteConnector, Songkick, and Setlist.fm all return capacity when available. These are now used to backfill null capacity values during enrichment merge. |

---

## 11. Deployment & Scaling

### 11.1 Current State (Prototype)

- Single-threaded Python script
- Disk-based JSON cache
- Synchronous API calls
- ~25 seconds to normalize 24K local records
- Excel output via openpyxl

### 11.2 Production Upgrade Path

| Component | Current | Production |
|-----------|---------|-----------|
| **Execution** | Sequential | Async (asyncio + aiohttp) |
| **Cache** | Disk JSON files | Redis with TTL |
| **Rate Limiting** | In-process timer | Redis-backed distributed limiter |
| **Scraping** | requests.get | Playwright headless browser pool |
| **Scheduling** | Manual CLI | Airflow DAG / cron |
| **Output** | Excel file | PostgreSQL + REST API + Excel export |
| **Monitoring** | Logging | Datadog / Prometheus metrics |
| **Dedup** | Pandas in-memory | Record linkage with fuzzy matching (dedupe library) |

### 11.3 Estimated API Costs (Monthly)

| Source | Stage | Calls/Month | Cost |
|--------|-------|-------------|------|
| Wikidata | 1 | 1,260 (42 countries × 30) | Free |
| OSM Overpass | 1 | 1,500 (50 cities × 30) | Free |
| Google Places | 1 | ~1,000 | ~$5 |
| Bandsintown | 1 | ~2,000 | Free |
| MusicBrainz | 1 | ~1,500 | Free |
| PredictHQ | 1 | ~2,000 | Free tier |
| Foursquare (discovery) | 1 | ~500 | Free tier |
| Ticketmaster | 1 | 5,000/day × 30 = 150K | Free (5K/day) |
| Eventim/Ticketek/DICE/BMS/Plat | 1 | ~3,000 | Free (scrape) |
| Songkick | 1 | ~3,000 | Free |
| Setlist.fm | 1 | ~3,000 | Free |
| Eventbrite | 1 | ~1,000 | Free tier |
| Skiddle | 1 | ~1,000 | Free tier |
| World Bank | 2 | ~180 (6 indicators × 30) | Free |
| Foursquare (market) | 2 | ~500 | Free tier |
| **Total** | **1+2** | **~170K** | **~$5/month** |

# Tixr Global Venue Intelligence System

## Overview

A multi-layer agent architecture for discovering, enriching, and scoring global venues for Tixr's expansion into EMEA, LATAM, and Southeast Asia. Aligned with the **Tixr Case Competition 2026** requirements.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│              ORCHESTRATOR (Layer 1)                   │
│  • Coordinates 4 sub-agents                          │
│  • Merges & deduplicates results                     │
│  • Computes VWP, Premium Fit, Priority scores        │
│  • Exports unified Excel workbook                    │
└────────┬──────────┬───────────┬───────────┬──────────┘
         │          │           │           │
┌────────▼──┐ ┌─────▼─────┐ ┌──▼────────┐ ┌▼──────────┐
│  Venue    │ │ Ticketing │ │  Event    │ │  Market   │
│ Discovery │ │   Intel   │ │Enrichment │ │   Intel   │
│  Agent    │ │   Agent   │ │  Agent    │ │   Agent   │
└─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
      │             │             │             │
 Layer 3: Connectors (APIs + Scrapers)
      │             │             │             │
 • Wikidata     • TM API      • Songkick    • World Bank
 • OSM          • AXS scrape  • Setlist.fm  • Foursquare
 • Google       • SeatGeek    • Eventbrite  •
   Places       • DICE        • Resident
                • Buy-button    Advisor
```

## Sub-Agents

| Agent | Sources | Signal | Accuracy |
|-------|---------|--------|----------|
| **VenueDiscoveryAgent** | Wikidata SPARQL, OSM Overpass, Google Places API | Venue name, location, type, capacity, website | High (structured data) |
| **TicketingIntelAgent** | Ticketmaster API, AXS/SeatGeek/DICE scraping, Buy-button URL check | Ticketing platform exclusivity | 65-95% per method |
| **EventEnrichmentAgent** | Songkick, Setlist.fm, Eventbrite, Resident Advisor | Event cadence, historical frequency, genre | Medium-High |
| **MarketIntelAgent** | World Bank API, Foursquare | GDP, internet, tourism, venue popularity | High (official data) |

## Normalized Schema (Unified Excel Output)

| Column | Description |
|--------|-------------|
| `venue_id` | Unique ID (Wikidata Q-ID, OSM ID, or generated) |
| `venue_name` | Canonical venue name |
| `city`, `country`, `region` | Location hierarchy |
| `venue_type` | stadium, arena, theatre, nightclub, events_venue, etc. |
| `capacity` | Integer capacity |
| `capacity_tier` | Mega (40K+), Major (15-40K), Mid (5-15K), Small (1-5K), Boutique (<1K) |
| `latitude`, `longitude` | Geo-coordinates |
| `website`, `booking_url` | URLs |
| `venue_operator` | Operator/owner |
| `ticketing_platform` | Known vendor (Ticketmaster, AXS, DICE, etc.) |
| `exclusivity_strength` | Strong, Medium, Weak, Unknown |
| **Tixr Scores** | |
| `venue_win_probability` | 0-1 likelihood Tixr can win the venue |
| `premium_fit_score` | 0-100 match with Tixr's premium positioning |
| `priority_score` | 0-100 composite ranking for sales reps |
| `data_completeness_pct` | % of key fields populated |

## Excel Sheets

1. **All_Venues** — Full normalized dataset sorted by priority
2. **Top_Targets** — Venues with priority ≥ 60
3. **Region_Summary** — Aggregated stats per region
4. **Country_Summary** — Aggregated stats per country
5. **Type_Summary** — Breakdown by venue type
6. **Capacity_Tiers** — Distribution by capacity tier
7. **Exclusivity_Map** — Venues with known ticketing platforms
8. **Market_Intelligence** — World Bank economic indicators
9. **Vendor_Landscape** — Ticketing platform competitive map
10. **Detection_Methods** — Exclusivity detection methodology
11. **Data_Sources** — Reference of all data sources

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run normalization only (no API keys needed)
python run_pipeline.py

# Run with live API enrichment
python run_pipeline.py --live --tm-key YOUR_TM_KEY --songkick-key YOUR_SK_KEY

# With all APIs
export TM_API_KEY=...
export SONGKICK_API_KEY=...
export SETLISTFM_API_KEY=...
export GOOGLE_PLACES_KEY=...
python run_pipeline.py --live --include-ra
```

## Data Sources Merged

| Source | Records | Key Fields |
|--------|---------|------------|
| Wikidata venues | 22,503 | name, country, type, capacity, coords, website |
| OSM city venues | 3,226 | name, city, type, operator, phone |
| Wikipedia stadiums | 507 | name, capacity, city, country, sport |
| Premium venues | 3,726 | Wikidata venues filtered for capacity |
| Country detailed (8×200) | 1,600 | Full profile: address, booking URL, operator, events |
| SEA venues (XLSX) | 114 | Includes ticketing vendor data |
| Exclusivity ground truth | 47 | Known platform + strength |
| Tixr premium targets | 2,974 | Capacity-filtered with size category |
| **After dedup** | **24,365** | Unified schema |

## Tixr Scoring Model

### Venue Win Probability (VWP)
Estimates likelihood a venue is **not locked** into Live Nation/AXS exclusivity:
- `Strong` TM/AXS exclusive → 0.05 (5%)
- `Medium` exclusive → 0.40 (40%)
- `Weak` exclusive → 0.70 (70%)
- No known platform → 0.65 (65% — opportunity)

### Premium Fit Score
Matches venue to Tixr's premium positioning:
- Capacity 1-5K (Tixr sweet spot): +25
- Has website: +10
- Premium venue type (arena, concert hall): +10
- Has operator/booking data: +5 each

### Priority Score
Composite: `0.35 × VWP + 0.35 × Premium Fit + 0.15 × Data Completeness + 0.15 × Market GDP`

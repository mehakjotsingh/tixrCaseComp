"""
Orchestrator Agent (Layer 1)
==============================
Coordinates 3 sub-agents (Discovery, Ticketing Intel, Event Enrichment)
to produce a complete venue dataset. The output is then passed to the
separate Recommendation Engine (Market Intelligence) for scoring.

Architecture:
  ┌──────────────────────────────────────────────────────────────┐
  │                   ORCHESTRATOR (Layer 1)                     │
  │  - Coordinates 3 data-gathering sub-agents                  │
  │  - Merges & deduplicates venue results                      │
  │  - Outputs enriched venue list → Recommendation Engine      │
  └────────┬──────────────┬──────────────┬──────────────────────┘
           │              │              │
  ┌────────▼──────┐ ┌─────▼──────┐ ┌────▼──────────┐
  │ Venue         │ │ Ticketing  │ │ Event         │
  │ Discovery     │ │ Intel      │ │ Enrichment    │
  │ Agent (7 src) │ │ Agent (9+) │ │ Agent (7 src) │
  └────┬──────────┘ └─────┬──────┘ └──────┬────────┘
       │                  │               │
       ▼                  ▼               ▼
  Wikidata, OSM,     TM, AXS, DICE,   Songkick, Setlist,
  MusicBrainz,       Eventim, Ticketek Eventbrite, Skiddle,
  Google Places,     BookMyShow,       PredictHQ, Bandsintown,
  Bandsintown,       Platinumlist,     Resident Advisor
  PredictHQ, FSQ     Buy-button
"""

import os
import json
import logging
import hashlib
from datetime import datetime

import pandas as pd
import numpy as np

from .venue_discovery_agent import VenueDiscoveryAgent
from .ticketing_intel_agent import TicketingIntelAgent
from .event_enrichment_agent import EventEnrichmentAgent

logger = logging.getLogger('tixr_agents')


class Orchestrator:
    """
    Layer 1: Orchestrator Agent
    Coordinates 3 data-gathering sub-agents and produces a unified venue
    dataset. Market Intelligence is handled separately by RecommendationEngine.
    """

    def __init__(self, output_dir=None):
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'output'
        )
        os.makedirs(self.output_dir, exist_ok=True)

        # Initialize 3 data-gathering sub-agents
        self.venue_agent = VenueDiscoveryAgent()
        self.ticketing_agent = TicketingIntelAgent()
        self.enrichment_agent = EventEnrichmentAgent()

        self.decision_log = []
        self.run_stats = {}

        self._log("Orchestrator initialized",
                  "3-agent data pipeline: "
                  "VenueDiscovery (7 sources: Wikidata/OSM/Google/Bandsintown/MusicBrainz/PredictHQ/Foursquare), "
                  "TicketingIntel (9+ sources: TM/AXS/SeatGeek/Eventim/Ticketek/DICE/BookMyShow/Platinumlist/Buy-button), "
                  "EventEnrichment (7 sources: Songkick/Setlist.fm/Eventbrite/Bandsintown/PredictHQ/Skiddle/RA). "
                  "Output feeds into separate RecommendationEngine for market scoring.")

    def _log(self, decision, reasoning):
        self.decision_log.append({
            'layer': 'orchestrator',
            'timestamp': datetime.now().isoformat(),
            'decision': decision,
            'reasoning': reasoning,
        })
        logger.info(f"[Orchestrator] {decision}")

    def configure_api_keys(self, keys):
        """
        Configure API keys for all sub-agents.
        keys: dict with possible keys:
          - ticketmaster_key
          - songkick_key
          - setlistfm_key
          - eventbrite_token
          - google_places_key
          - foursquare_key
        """
        if keys.get('ticketmaster_key'):
            self.ticketing_agent.configure(tm_api_key=keys['ticketmaster_key'])
            self._log("Ticketmaster API configured", "5K calls/day for venue exclusivity detection")

        if keys.get('songkick_key'):
            self.enrichment_agent.configure(songkick_key=keys['songkick_key'])
            self._log("Songkick API configured", "Event cadence enrichment enabled")

        if keys.get('setlistfm_key'):
            self.enrichment_agent.configure(setlistfm_key=keys['setlistfm_key'])
            self._log("Setlist.fm API configured", "Historical event frequency enabled")

        if keys.get('eventbrite_token'):
            self.enrichment_agent.configure(eventbrite_token=keys['eventbrite_token'])
            self._log("Eventbrite API configured", "International event data enabled")

        if keys.get('google_places_key'):
            self.venue_agent.configure_google_places(keys['google_places_key'])
            self._log("Google Places API configured", "Comprehensive venue type classification")

        if keys.get('bandsintown_app_id'):
            self.venue_agent.configure(bandsintown_app_id=keys['bandsintown_app_id'])
            self.enrichment_agent.configure(bandsintown_app_id=keys['bandsintown_app_id'])
            self._log("Bandsintown API configured", "Venue discovery + event enrichment")

        if keys.get('predicthq_token'):
            self.enrichment_agent.configure(predicthq_token=keys['predicthq_token'])
            self._log("PredictHQ API configured", "Demand intelligence enabled")

        if keys.get('skiddle_key'):
            self.enrichment_agent.configure(skiddle_key=keys['skiddle_key'])
            self._log("Skiddle API configured", "UK event data enabled")

    def run_discovery(self, countries=None, cities=None, use_google=False):
        """
        Phase 1: Venue Discovery
        Pull venue data from Wikidata, OSM, and Google Places.
        """
        self._log("Starting Phase 1: Venue Discovery",
                  f"Countries: {len(countries or [])}, Cities: {len(cities or [])}")

        params = {}
        if countries:
            params['countries'] = countries
        if cities:
            params['cities'] = cities
        params['use_google'] = use_google

        venues_df = self.venue_agent.fetch(params)
        self.run_stats['discovery'] = {
            'records': len(venues_df),
            'stats': self.venue_agent.get_stats(),
        }

        self._log(f"Discovery complete: {len(venues_df)} venues found",
                  f"Sources: {venues_df['data_sources'].value_counts().to_dict() if len(venues_df) > 0 else 'none'}")

        return venues_df

    def run_exclusivity_check(self, venues_df, max_venues=100):
        """
        Phase 2: Ticketing Exclusivity Detection
        Check venues against ticketing platform databases.
        """
        self._log("Starting Phase 2: Exclusivity Detection",
                  f"Checking up to {max_venues} venues against TM/AXS/SeatGeek/buy-button")

        excl_df = self.ticketing_agent.fetch({
            'venues_df': venues_df,
            'max_venues': max_venues,
        })

        self.run_stats['exclusivity'] = {
            'records': len(excl_df),
            'stats': self.ticketing_agent.get_stats(),
        }

        return excl_df

    def run_enrichment(self, venues_df, max_venues=50, include_ra=False):
        """
        Phase 3: Event Enrichment
        Add event cadence, genre, and activity signals.
        """
        self._log("Starting Phase 3: Event Enrichment",
                  f"Enriching up to {max_venues} venues with Songkick/Setlist.fm/RA signals")

        enriched_df = self.enrichment_agent.fetch({
            'venues_df': venues_df,
            'max_venues': max_venues,
            'include_ra': include_ra,
        })

        self.run_stats['enrichment'] = {
            'records': len(enriched_df),
            'stats': self.enrichment_agent.get_stats(),
        }

        return enriched_df

    def merge_results(self, base_df, exclusivity_df=None, enrichment_df=None):
        """
        Merge all agent results into the base venue dataset.
        Uses venue_name + country as join key (plus wikidata_id where available).
        """
        self._log("Merging agent results",
                  f"Base: {len(base_df)}, Exclusivity: {len(exclusivity_df) if exclusivity_df is not None else 0}, "
                  f"Enrichment: {len(enrichment_df) if enrichment_df is not None else 0}")

        result = base_df.copy()

        # Merge exclusivity data
        if exclusivity_df is not None and len(exclusivity_df) > 0:
            excl_cols = ['venue_name', 'ticketing_platform', 'exclusivity_strength']
            excl_subset = exclusivity_df[excl_cols].dropna(subset=['venue_name'])
            if len(excl_subset) > 0:
                excl_subset = excl_subset.drop_duplicates(subset='venue_name', keep='first')
                result = result.merge(
                    excl_subset,
                    on='venue_name',
                    how='left',
                    suffixes=('', '_excl')
                )
                # Prefer new exclusivity data over existing
                for col in ['ticketing_platform', 'exclusivity_strength']:
                    excl_col = f'{col}_excl'
                    if excl_col in result.columns:
                        mask = result[col].isna() & result[excl_col].notna()
                        result.loc[mask, col] = result.loc[mask, excl_col]
                        result = result.drop(columns=[excl_col])

        # Merge enrichment data
        if enrichment_df is not None and len(enrichment_df) > 0:
            enrich_cols = ['venue_name', 'upcoming_events', 'past_events', 'notes']
            enrich_subset = enrichment_df[enrich_cols].dropna(subset=['venue_name'])
            if len(enrich_subset) > 0:
                enrich_subset = enrich_subset.drop_duplicates(subset='venue_name', keep='first')
                result = result.merge(
                    enrich_subset,
                    on='venue_name',
                    how='left',
                    suffixes=('', '_enrich')
                )
                for col in ['upcoming_events', 'past_events', 'notes']:
                    enrich_col = f'{col}_enrich'
                    if enrich_col in result.columns:
                        mask = result[col].isna() & result[enrich_col].notna()
                        result.loc[mask, col] = result.loc[mask, enrich_col]
                        result = result.drop(columns=[enrich_col])

        return result

    def compute_tixr_scores(self, df):
        """
        Compute Tixr-specific scoring columns:
        1. Venue Win Probability (VWP): likelihood venue is NOT locked into exclusivity
        2. Premium Fit Score: how well venue matches Tixr's premium positioning
        3. Priority Score: combined ranking for sales team
        """
        self._log("Computing Tixr scoring columns",
                  "VWP (exclusivity likelihood), Premium Fit, Priority Score")

        # 1. Venue Win Probability (VWP)
        # Higher = more likely Tixr can win the venue
        def compute_vwp(row):
            strength = str(row.get('exclusivity_strength', 'Unknown')).lower()
            platform = str(row.get('ticketing_platform', '')).lower()

            if strength == 'strong':
                if 'ticketmaster' in platform or 'axs' in platform:
                    return 0.05  # Very unlikely
                return 0.15
            elif strength == 'medium':
                return 0.40
            elif strength == 'weak':
                return 0.70
            elif strength == 'none':
                return 0.90
            elif platform and platform != 'nan':
                return 0.30  # Has a platform but unknown strength
            else:
                return 0.60  # Unknown = neutral (could go either way)

        df['venue_win_probability'] = df.apply(compute_vwp, axis=1)

        # 2. Premium Fit Score (0-100)
        # Based on: capacity (prefer 1K-20K), has website, has coordinates, type
        def compute_premium_fit(row):
            score = 50  # Base score

            cap = row.get('capacity')
            if pd.notna(cap):
                cap = float(cap)
                if 1000 <= cap <= 5000:
                    score += 25  # Boutique premium - Tixr sweet spot
                elif 5000 <= cap <= 20000:
                    score += 20  # Mid-size premium
                elif cap > 20000:
                    score += 10  # Large - often locked
                elif cap > 0:
                    score += 5   # Very small

            if pd.notna(row.get('website')):
                score += 10  # Has web presence

            if pd.notna(row.get('latitude')):
                score += 5   # Has geo data (operational)

            vtype = str(row.get('venue_type', '')).lower()
            premium_types = ['arena', 'concert_hall', 'amphitheatre', 'music_venue', 'events_venue']
            if any(t in vtype for t in premium_types):
                score += 10

            return min(score, 100)

        df['premium_fit_score'] = df.apply(compute_premium_fit, axis=1)

        # 3. Priority Score (composite)
        # = VWP * 40% + Premium Fit * 40% + Data Completeness * 20%
        def compute_priority(row):
            vwp = row.get('venue_win_probability', 0.5) * 100
            pf = row.get('premium_fit_score', 50)

            # Data completeness score
            fields = ['venue_name', 'city', 'country', 'capacity', 'website',
                      'latitude', 'longitude', 'venue_type']
            completeness = sum(1 for f in fields if pd.notna(row.get(f))) / len(fields) * 100

            return round(0.4 * vwp + 0.4 * pf + 0.2 * completeness, 1)

        df['priority_score'] = df.apply(compute_priority, axis=1)

        return df

    def export_results(self, df, filename='tixr_normalized_venues.xlsx'):
        """Export final results to Excel with multiple sheets."""
        output_path = os.path.join(self.output_dir, filename)
        self._log(f"Exporting results to {output_path}", f"{len(df)} venues")

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Main venues sheet - sorted by priority
            df_sorted = df.sort_values('priority_score', ascending=False) if 'priority_score' in df.columns else df
            df_sorted.to_excel(writer, sheet_name='All_Venues', index=False)

            # Top targets (priority > 60)
            if 'priority_score' in df.columns:
                top_targets = df_sorted[df_sorted['priority_score'] >= 60]
                top_targets.to_excel(writer, sheet_name='Top_Targets', index=False)

            # By region summary
            if 'region' in df.columns:
                region_summary = df.groupby('region').agg(
                    total_venues=('venue_id', 'count'),
                    avg_priority=('priority_score', 'mean') if 'priority_score' in df.columns else ('venue_id', 'count'),
                    with_capacity=('capacity', lambda x: x.notna().sum()),
                    with_website=('website', lambda x: x.notna().sum()),
                    avg_capacity=('capacity', 'mean'),
                ).reset_index()
                region_summary.to_excel(writer, sheet_name='Region_Summary', index=False)

            # Exclusivity landscape
            excl = df[df['ticketing_platform'].notna() & (df['ticketing_platform'] != '')]
            if len(excl) > 0:
                excl_cols = ['venue_name', 'city', 'country', 'capacity', 'venue_type',
                             'ticketing_platform', 'exclusivity_strength', 'venue_win_probability']
                available = [c for c in excl_cols if c in excl.columns]
                excl[available].to_excel(writer, sheet_name='Exclusivity_Map', index=False)

            # Decision log
            all_logs = (
                self.decision_log +
                self.venue_agent.decision_log +
                self.ticketing_agent.decision_log +
                self.enrichment_agent.decision_log
            )
            log_df = pd.DataFrame(all_logs)
            log_df.to_excel(writer, sheet_name='Decision_Log', index=False)

            # Data sources reference
            sources = {
                'VenueDiscovery': self.venue_agent.get_source_description(),
                'TicketingIntel': self.ticketing_agent.get_source_description(),
                'EventEnrichment': self.enrichment_agent.get_source_description(),
            }
            source_rows = []
            for agent_name, desc in sources.items():
                for src in desc.get('sources', []):
                    source_rows.append({
                        'agent': agent_name,
                        'source_name': src.get('name'),
                        'url': src.get('url'),
                        'type': src.get('type'),
                        'coverage': src.get('coverage', ''),
                        'signal': src.get('signal', ''),
                        'accuracy': src.get('accuracy', ''),
                    })
            pd.DataFrame(source_rows).to_excel(writer, sheet_name='Data_Sources', index=False)

        logger.info(f"Results exported to {output_path}")
        return output_path

    def run_full_pipeline(self, config=None):
        """
        Run the 3-agent data-gathering pipeline end-to-end.
        Returns the enriched venue DataFrame for the RecommendationEngine.

        config: dict with:
          - countries: list (default: all target countries)
          - cities: list (default: all target cities)
          - api_keys: dict of API keys
          - max_exclusivity_check: int
          - max_enrichment: int
          - include_ra: bool
          - export: bool (write intermediate Excel, default True)
        """
        config = config or {}
        start_time = datetime.now()

        self._log("Starting 3-agent data pipeline", json.dumps({
            'countries': len(config.get('countries', [])),
        }))

        # Configure API keys
        if config.get('api_keys'):
            self.configure_api_keys(config['api_keys'])

        # Phase 1: Discovery
        venues_df = self.run_discovery(
            countries=config.get('countries'),
            cities=config.get('cities'),
            use_google=bool(config.get('api_keys', {}).get('google_places_key')),
        )

        # Phase 2: Exclusivity
        excl_df = None
        if len(venues_df) > 0:
            excl_df = self.run_exclusivity_check(
                venues_df,
                max_venues=config.get('max_exclusivity_check', 100),
            )

        # Phase 3: Enrichment
        enriched_df = None
        if len(venues_df) > 0:
            enriched_df = self.run_enrichment(
                venues_df,
                max_venues=config.get('max_enrichment', 50),
                include_ra=config.get('include_ra', False),
            )

        # Merge all data-gathering results
        final_df = self.merge_results(venues_df, excl_df, enriched_df)

        # Compute base Tixr scores
        final_df = self.compute_tixr_scores(final_df)

        # Optionally export intermediate results
        output_path = None
        if config.get('export', True):
            output_path = self.export_results(final_df)

        elapsed = (datetime.now() - start_time).total_seconds()
        self._log(f"Data pipeline complete in {elapsed:.1f}s",
                  f"Dataset: {len(final_df)} venues. "
                  f"Ready for RecommendationEngine.")

        return final_df, output_path

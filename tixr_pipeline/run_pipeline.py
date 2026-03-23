"""
Tixr Global Venue Intelligence - Main Pipeline Runner
=======================================================
Two-stage pipeline:
  Stage 1: Orchestrator (3 agents) → enriched venue dataset
    - VenueDiscovery (7 sources), TicketingIntel (9+), EventEnrichment (7)
  Stage 2: RecommendationEngine → scored + tiered recommendations
    - Market Intelligence (World Bank + Foursquare)

Usage:
  # Basic: normalize local data only (no API keys needed)
  python run_pipeline.py

  # With API enrichment (set env vars first):
  python run_pipeline.py --live

  # With specific API keys:
  python run_pipeline.py --live --tm-key YOUR_KEY --songkick-key YOUR_KEY

  # Full pipeline with recommendations:
  python run_pipeline.py --live --recommend

Environment Variables (optional):
  TM_API_KEY          - Ticketmaster Discovery API key
  SONGKICK_API_KEY    - Songkick API key
  SETLISTFM_API_KEY   - Setlist.fm API key
  EVENTBRITE_TOKEN    - Eventbrite OAuth token
  GOOGLE_PLACES_KEY   - Google Places API key
  FOURSQUARE_KEY      - Foursquare Places API key
  BANDSINTOWN_APP_ID  - Bandsintown API app ID
  PREDICTHQ_TOKEN     - PredictHQ API token
  SKIDDLE_KEY         - Skiddle API key
"""

import os
import sys
import argparse
import logging
from datetime import datetime

import pandas as pd
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('tixr_pipeline')

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalize_data import main as run_normalization
from agents.orchestrator import Orchestrator
from recommendation_engine import RecommendationEngine


def parse_args():
    parser = argparse.ArgumentParser(description='Tixr Venue Intelligence Pipeline')
    parser.add_argument('--live', action='store_true',
                        help='Enable live API fetching (requires API keys)')
    parser.add_argument('--tm-key', type=str, default=os.environ.get('TM_API_KEY'),
                        help='Ticketmaster API key')
    parser.add_argument('--songkick-key', type=str, default=os.environ.get('SONGKICK_API_KEY'),
                        help='Songkick API key')
    parser.add_argument('--setlistfm-key', type=str, default=os.environ.get('SETLISTFM_API_KEY'),
                        help='Setlist.fm API key')
    parser.add_argument('--eventbrite-token', type=str, default=os.environ.get('EVENTBRITE_TOKEN'),
                        help='Eventbrite OAuth token')
    parser.add_argument('--google-key', type=str, default=os.environ.get('GOOGLE_PLACES_KEY'),
                        help='Google Places API key')
    parser.add_argument('--foursquare-key', type=str, default=os.environ.get('FOURSQUARE_KEY'),
                        help='Foursquare API key')
    parser.add_argument('--bandsintown-id', type=str, default=os.environ.get('BANDSINTOWN_APP_ID'),
                        help='Bandsintown app ID')
    parser.add_argument('--predicthq-token', type=str, default=os.environ.get('PREDICTHQ_TOKEN'),
                        help='PredictHQ API token')
    parser.add_argument('--skiddle-key', type=str, default=os.environ.get('SKIDDLE_KEY'),
                        help='Skiddle API key')
    parser.add_argument('--recommend', action='store_true',
                        help='Run Stage 2: RecommendationEngine after data gathering')
    parser.add_argument('--max-exclusivity', type=int, default=200,
                        help='Max venues to check for exclusivity')
    parser.add_argument('--max-enrichment', type=int, default=100,
                        help='Max venues to enrich with event data')
    parser.add_argument('--include-ra', action='store_true',
                        help='Include Resident Advisor club scraping')
    parser.add_argument('--output', type=str, default=None,
                        help='Output filename (default: tixr_normalized_venues.xlsx)')
    return parser.parse_args()


def compute_tixr_scores(df):
    """
    Compute Tixr-specific scoring columns on the normalized dataset.
    These scores help sales reps prioritize venues.
    """
    logger.info("Computing Tixr scoring columns...")

    # 1. Venue Win Probability (VWP)
    def compute_vwp(row):
        strength = str(row.get('exclusivity_strength', '')).lower().strip()
        platform = str(row.get('ticketing_platform', '')).lower().strip()

        if strength == 'strong':
            if 'ticketmaster' in platform or 'axs' in platform:
                return 0.05
            return 0.15
        elif strength == 'medium':
            return 0.40
        elif strength == 'weak':
            return 0.70
        elif strength in ['none', '']:
            if platform and platform not in ['nan', 'none', '']:
                return 0.30
            return 0.65  # No known platform = opportunity
        return 0.60

    df['venue_win_probability'] = df.apply(compute_vwp, axis=1)

    # 2. Premium Fit Score (0-100)
    def compute_premium_fit(row):
        score = 40

        cap = row.get('capacity')
        if pd.notna(cap):
            try:
                cap = float(cap)
                if 1000 <= cap <= 5000:
                    score += 25
                elif 5000 <= cap <= 20000:
                    score += 20
                elif cap > 20000:
                    score += 10
                elif cap > 0:
                    score += 5
            except (ValueError, TypeError):
                pass

        if pd.notna(row.get('website')) and str(row.get('website', '')).strip():
            score += 10

        if pd.notna(row.get('latitude')):
            score += 5

        vtype = str(row.get('venue_type', '')).lower()
        premium_types = ['arena', 'concert_hall', 'amphitheatre', 'music_venue', 'events_venue']
        if any(t in vtype for t in premium_types):
            score += 10

        if pd.notna(row.get('booking_url')) and str(row.get('booking_url', '')).strip():
            score += 5

        if pd.notna(row.get('venue_operator')) and str(row.get('venue_operator', '')).strip():
            score += 5

        return min(score, 100)

    df['premium_fit_score'] = df.apply(compute_premium_fit, axis=1)

    # 3. Data Completeness Score
    key_fields = ['venue_name', 'city', 'country', 'capacity', 'website',
                  'latitude', 'longitude', 'venue_type', 'address',
                  'booking_url', 'venue_operator']

    def data_completeness(row):
        filled = sum(
            1 for f in key_fields
            if pd.notna(row.get(f)) and str(row.get(f, '')).strip() not in ['', 'nan']
        )
        return round(filled / len(key_fields) * 100, 1)

    df['data_completeness_pct'] = df.apply(data_completeness, axis=1)

    # 4. Priority Score (composite)
    df['priority_score'] = (
        0.35 * df['venue_win_probability'] * 100 +
        0.35 * df['premium_fit_score'] +
        0.15 * df['data_completeness_pct'] +
        0.15 * df.get('gdp_per_capita_usd', pd.Series(0, index=df.index)).fillna(0).clip(0, 100000) / 1000
    ).round(1)

    # Normalize priority to 0-100
    if df['priority_score'].max() > 0:
        df['priority_score'] = (
            df['priority_score'] / df['priority_score'].max() * 100
        ).round(1)

    logger.info(f"  VWP range: {df['venue_win_probability'].min():.2f} - {df['venue_win_probability'].max():.2f}")
    logger.info(f"  Premium Fit range: {df['premium_fit_score'].min()} - {df['premium_fit_score'].max()}")
    logger.info(f"  Priority range: {df['priority_score'].min()} - {df['priority_score'].max()}")

    return df


def export_final_excel(df, output_dir, filename='tixr_normalized_venues.xlsx'):
    """Export the final normalized + scored dataset to a multi-sheet Excel workbook."""
    output_path = os.path.join(output_dir, filename)
    logger.info(f"Exporting to {output_path}...")

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:

        # Sheet 1: All Venues (sorted by priority)
        df_sorted = df.sort_values('priority_score', ascending=False)
        df_sorted.to_excel(writer, sheet_name='All_Venues', index=False)

        # Sheet 2: Top Targets (priority >= 60)
        if 'priority_score' in df.columns:
            top = df_sorted[df_sorted['priority_score'] >= 60].copy()
            top.to_excel(writer, sheet_name='Top_Targets', index=False)
            logger.info(f"  Top Targets: {len(top)} venues with priority >= 60")

        # Sheet 3: Region Summary
        agg_dict = {
            'venue_id': 'count',
            'capacity': [lambda x: x.notna().sum(), 'mean'],
            'website': lambda x: x.notna().sum(),
        }
        # Build region summary manually for cleaner output
        region_groups = df.groupby('region')
        region_rows = []
        for region, group in region_groups:
            region_rows.append({
                'region': region,
                'total_venues': len(group),
                'with_capacity': group['capacity'].notna().sum(),
                'avg_capacity': round(group['capacity'].mean(), 0) if group['capacity'].notna().any() else 0,
                'with_website': group['website'].notna().sum(),
                'with_coordinates': group['latitude'].notna().sum(),
                'avg_priority_score': round(group['priority_score'].mean(), 1) if 'priority_score' in group.columns else 0,
                'avg_vwp': round(group['venue_win_probability'].mean(), 2) if 'venue_win_probability' in group.columns else 0,
            })
        pd.DataFrame(region_rows).to_excel(writer, sheet_name='Region_Summary', index=False)

        # Sheet 4: Country Summary
        country_groups = df.groupby(['region', 'country'])
        country_rows = []
        for (region, country), group in country_groups:
            country_rows.append({
                'region': region,
                'country': country,
                'total_venues': len(group),
                'with_capacity': group['capacity'].notna().sum(),
                'avg_capacity': round(group['capacity'].mean(), 0) if group['capacity'].notna().any() else 0,
                'with_website': group['website'].notna().sum(),
                'avg_priority': round(group['priority_score'].mean(), 1) if 'priority_score' in group.columns else 0,
            })
        pd.DataFrame(country_rows).sort_values('total_venues', ascending=False).to_excel(
            writer, sheet_name='Country_Summary', index=False)

        # Sheet 5: Venue Type Summary
        type_groups = df.groupby('venue_type')
        type_rows = []
        for vtype, group in type_groups:
            type_rows.append({
                'venue_type': vtype,
                'count': len(group),
                'avg_capacity': round(group['capacity'].mean(), 0) if group['capacity'].notna().any() else 0,
                'with_website_pct': round(group['website'].notna().mean() * 100, 1),
            })
        pd.DataFrame(type_rows).sort_values('count', ascending=False).to_excel(
            writer, sheet_name='Type_Summary', index=False)

        # Sheet 6: Capacity Tier Distribution
        if 'capacity_tier' in df.columns:
            tier_groups = df.groupby('capacity_tier')
            tier_rows = []
            for tier, group in tier_groups:
                tier_rows.append({
                    'capacity_tier': tier,
                    'count': len(group),
                    'pct': round(len(group) / len(df) * 100, 1),
                    'avg_priority': round(group['priority_score'].mean(), 1) if 'priority_score' in group.columns else 0,
                })
            pd.DataFrame(tier_rows).to_excel(writer, sheet_name='Capacity_Tiers', index=False)

        # Sheet 7: Known Exclusivity Map
        excl = df[df['ticketing_platform'].notna()].copy()
        if len(excl) > 0:
            excl_cols = [c for c in ['venue_name', 'city', 'country', 'capacity', 'venue_type',
                                      'ticketing_platform', 'exclusivity_strength',
                                      'contract_status', 'venue_win_probability'] if c in excl.columns]
            excl[excl_cols].to_excel(writer, sheet_name='Exclusivity_Map', index=False)

        # Sheet 8: Market Intelligence
        wb_path = os.path.join(data_dir, '5_world_bank_market_intelligence.csv')
        if os.path.exists(wb_path):
            wb = pd.read_csv(wb_path)
            wb.to_excel(writer, sheet_name='Market_Intelligence', index=False)

        # Sheet 9: Vendor Landscape
        v1_path = os.path.join(data_dir, 'V1_ticketing_vendor_exclusivity_map.csv')
        if os.path.exists(v1_path):
            v1 = pd.read_csv(v1_path)
            v1.to_excel(writer, sheet_name='Vendor_Landscape', index=False)

        # Sheet 10: Detection Methods
        v3_path = os.path.join(data_dir, 'V3_exclusivity_detection_methods.csv')
        if os.path.exists(v3_path):
            v3 = pd.read_csv(v3_path)
            v3.to_excel(writer, sheet_name='Detection_Methods', index=False)

        # Sheet 11: Data Source Reference
        ds_path = os.path.join(data_dir, '8_data_source_reference.csv')
        if os.path.exists(ds_path):
            ds = pd.read_csv(ds_path)
            ds.to_excel(writer, sheet_name='Data_Sources', index=False)

    logger.info(f"✅ Final Excel saved: {output_path}")
    logger.info(f"   11 sheets covering venues, scores, summaries, exclusivity, market intel")
    return output_path


def main():
    args = parse_args()

    print("=" * 70)
    print("TIXR GLOBAL VENUE INTELLIGENCE SYSTEM")
    print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
    os.makedirs(output_dir, exist_ok=True)

    # ── Phase 1: Normalize all local data ─────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 1: LOCAL DATA NORMALIZATION")
    print("=" * 70)
    normalized_df = run_normalization()

    # ── Phase 2: (Optional) Live API enrichment ───────────────────────────
    if args.live:
        print("\n" + "=" * 70)
        print("PHASE 2: LIVE API ENRICHMENT (Agent System)")
        print("=" * 70)

        orchestrator = Orchestrator(output_dir=output_dir)

        api_keys = {}
        if args.tm_key:
            api_keys['ticketmaster_key'] = args.tm_key
        if args.songkick_key:
            api_keys['songkick_key'] = args.songkick_key
        if args.setlistfm_key:
            api_keys['setlistfm_key'] = args.setlistfm_key
        if args.eventbrite_token:
            api_keys['eventbrite_token'] = args.eventbrite_token
        if args.google_key:
            api_keys['google_places_key'] = args.google_key
        if args.bandsintown_id:
            api_keys['bandsintown_app_id'] = args.bandsintown_id
        if args.predicthq_token:
            api_keys['predicthq_token'] = args.predicthq_token
        if args.skiddle_key:
            api_keys['skiddle_key'] = args.skiddle_key

        if api_keys:
            orchestrator.configure_api_keys(api_keys)

        # Run exclusivity checks on venues with websites
        venues_with_sites = normalized_df[normalized_df['website'].notna()].head(args.max_exclusivity)
        if len(venues_with_sites) > 0:
            logger.info(f"Running exclusivity checks on {len(venues_with_sites)} venues...")
            excl_df = orchestrator.run_exclusivity_check(venues_with_sites, args.max_exclusivity)

            # Merge exclusivity results back
            if len(excl_df) > 0:
                normalized_df = orchestrator.merge_results(
                    normalized_df, exclusivity_df=excl_df
                )

        # Run event enrichment on top venues
        top_venues = normalized_df.nlargest(args.max_enrichment, 'capacity', 'first') \
            if 'capacity' in normalized_df.columns and normalized_df['capacity'].notna().any() \
            else normalized_df.head(args.max_enrichment)

        if len(top_venues) > 0:
            logger.info(f"Running event enrichment on {len(top_venues)} venues...")
            enriched_df = orchestrator.run_enrichment(top_venues, args.max_enrichment, args.include_ra)

            if len(enriched_df) > 0:
                normalized_df = orchestrator.merge_results(
                    normalized_df, enrichment_df=enriched_df
                )

        print(f"\n  Stage 1 (Data Gathering) complete. Agent stats:")
        for agent_name, agent in [
            ('VenueDiscovery', orchestrator.venue_agent),
            ('TicketingIntel', orchestrator.ticketing_agent),
            ('EventEnrichment', orchestrator.enrichment_agent),
        ]:
            stats = agent.get_stats()
            print(f"    {agent_name}: {stats['stats']}")

    # ── Phase 3: Compute Tixr Scores ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 3: TIXR SCORING")
    print("=" * 70)
    normalized_df = compute_tixr_scores(normalized_df)

    # ── Phase 4: Export Stage 1 Results ──────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 4: EXPORT STAGE 1 RESULTS")
    print("=" * 70)

    filename = args.output or 'tixr_normalized_venues.xlsx'
    output_path = export_final_excel(normalized_df, output_dir, filename)

    # ── Phase 5 (Optional): Stage 2 — Recommendation Engine ─────────────
    rec_output_path = None
    if args.recommend or args.foursquare_key:
        print("\n" + "=" * 70)
        print("PHASE 5: STAGE 2 — RECOMMENDATION ENGINE")
        print("=" * 70)

        rec_engine = RecommendationEngine(output_dir=output_dir)

        rec_config = {
            'use_live_api': args.live,
            'export': True,
        }
        if args.foursquare_key:
            rec_config['foursquare_key'] = args.foursquare_key

        scored_df, market_df, rec_output_path = rec_engine.generate_recommendations(
            normalized_df, config=rec_config
        )

        if 'recommendation_tier' in scored_df.columns:
            tier_counts = scored_df['recommendation_tier'].value_counts()
            print(f"\n  Recommendation tiers:")
            for tier, count in tier_counts.items():
                print(f"    {tier}: {count}")

        normalized_df = scored_df  # Use scored version for summary

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"Total venues:        {len(normalized_df)}")
    print(f"With capacity:       {normalized_df['capacity'].notna().sum()}")
    print(f"With website:        {normalized_df['website'].notna().sum()}")
    print(f"With coordinates:    {normalized_df['latitude'].notna().sum()}")
    print(f"With exclusivity:    {normalized_df['ticketing_platform'].notna().sum()}")
    print(f"Countries:           {normalized_df['country'].nunique()}")
    print(f"Regions:             {normalized_df['region'].nunique() if 'region' in normalized_df.columns else 'N/A'}")
    print(f"\nStage 1 Output: {output_path}")
    if rec_output_path:
        print(f"Stage 2 Output: {rec_output_path}")
    print(f"\nTo enrich with live APIs: python run_pipeline.py --live --tm-key YOUR_KEY")
    print(f"To add recommendations:  python run_pipeline.py --live --recommend")


if __name__ == '__main__':
    main()

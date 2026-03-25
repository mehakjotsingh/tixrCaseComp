"""
Recommendation Engine (Stage 2)
=================================
Separate from the Orchestrator, this engine takes the enriched venue dataset
produced by the 3-agent pipeline and applies Market Intelligence scoring
to generate prioritized recommendations for Tixr's sales team.

Pipeline Flow:
  Stage 1: Orchestrator (3 agents) → enriched venue DataFrame
  Stage 2: RecommendationEngine    → scored + ranked recommendations

Sources:
  - World Bank Open Data API (GDP, internet, mobile, tourism, population)
  - Foursquare Places API (venue popularity / check-in signals)
"""

import os
import json
import logging
from datetime import datetime

import pandas as pd
import numpy as np

from agents.market_intel_agent import MarketIntelAgent

logger = logging.getLogger('tixr_agents')


class RecommendationEngine:
    """
    Stage 2: Market Intelligence + Recommendation Scoring.
    Consumes the venue DataFrame from the Orchestrator and produces
    ranked venue recommendations with market context.
    """

    # Region mapping for countries
    REGION_MAP = {
        'Japan': 'APAC', 'Australia': 'APAC', 'India': 'APAC',
        'South Korea': 'APAC', 'China': 'APAC', 'New Zealand': 'APAC',
        'United Kingdom': 'EMEA', 'Germany': 'EMEA', 'France': 'EMEA',
        'Spain': 'EMEA', 'Italy': 'EMEA', 'Netherlands': 'EMEA',
        'Belgium': 'EMEA', 'Sweden': 'EMEA', 'Norway': 'EMEA',
        'Denmark': 'EMEA', 'Finland': 'EMEA', 'Austria': 'EMEA',
        'Switzerland': 'EMEA', 'Poland': 'EMEA', 'Czech Republic': 'EMEA',
        'Portugal': 'EMEA', 'Ireland': 'EMEA', 'Greece': 'EMEA',
        'Turkey': 'EMEA',
        'United Arab Emirates': 'EMEA_Gulf', 'Saudi Arabia': 'EMEA_Gulf',
        'Qatar': 'EMEA_Gulf', 'Bahrain': 'EMEA_Gulf',
        'Kuwait': 'EMEA_Gulf', 'Oman': 'EMEA_Gulf', 'Israel': 'EMEA_Gulf',
        'Egypt': 'EMEA_Africa', 'South Africa': 'EMEA_Africa',
        'Nigeria': 'EMEA_Africa', 'Kenya': 'EMEA_Africa', 'Morocco': 'EMEA_Africa',
        'Brazil': 'LATAM', 'Mexico': 'LATAM', 'Argentina': 'LATAM',
        'Colombia': 'LATAM', 'Chile': 'LATAM', 'Peru': 'LATAM',
        'Thailand': 'SEA', 'Indonesia': 'SEA', 'Singapore': 'SEA',
        'Malaysia': 'SEA', 'Philippines': 'SEA', 'Vietnam': 'SEA',
        'Cambodia': 'SEA', 'Myanmar': 'SEA',
    }

    def __init__(self, output_dir=None):
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'output'
        )
        os.makedirs(self.output_dir, exist_ok=True)

        self.market_agent = MarketIntelAgent()
        self.decision_log = []
        self.run_stats = {}

        self._log("RecommendationEngine initialized",
                  "Stage 2 engine: takes enriched venue data from Orchestrator, "
                  "applies World Bank market scores + Foursquare popularity, "
                  "produces ranked recommendations.")

    def _log(self, decision, reasoning):
        self.decision_log.append({
            'layer': 'recommendation_engine',
            'timestamp': datetime.now().isoformat(),
            'decision': decision,
            'reasoning': reasoning,
        })
        logger.info(f"[RecommendationEngine] {decision}")

    def configure(self, foursquare_key=None):
        """Configure API keys for market intelligence sources."""
        if foursquare_key:
            self.market_agent.configure_foursquare(foursquare_key)
            self._log("Foursquare API configured", "Venue popularity signals enabled")

    # ─── Market Data Fetching ─────────────────────────────────────────────────

    def fetch_market_data(self, countries=None, use_live_api=False):
        """
        Fetch market intelligence data for target countries.
        Returns a DataFrame with country-level indicators + market_score.
        """
        self._log("Fetching market intelligence",
                  f"Countries: {len(countries or [])}, Live API: {use_live_api}")

        market_df = self.market_agent.fetch({
            'countries': countries,
            'use_live_api': use_live_api,
        })

        self.run_stats['market_records'] = len(market_df)
        return market_df

    # ─── Venue-Market Merge ───────────────────────────────────────────────────

    def enrich_with_market_data(self, venues_df, market_df):
        """
        Merge market-level data into the venue dataset at the country level.
        """
        if market_df is None or len(market_df) == 0:
            return venues_df

        market_cols = ['country', 'region', 'market_score',
                       'gdp_per_capita_usd', 'internet_users_pct',
                       'mobile_subscriptions_per_100', 'tourism_arrivals']
        available_cols = [c for c in market_cols if c in market_df.columns]

        if not available_cols or 'country' not in available_cols:
            return venues_df

        market_subset = market_df[available_cols].drop_duplicates(
            subset='country', keep='first'
        )

        result = venues_df.merge(
            market_subset,
            on='country',
            how='left',
            suffixes=('', '_market')
        )

        # Resolve conflicts
        for col in market_cols:
            if col == 'country':
                continue
            market_col = f'{col}_market'
            if market_col in result.columns:
                mask = result[col].isna() & result[market_col].notna()
                result.loc[mask, col] = result.loc[mask, market_col]
                result = result.drop(columns=[market_col])

        # Fill region from our map if still missing
        if 'region' not in result.columns:
            result['region'] = result['country'].map(self.REGION_MAP)
        else:
            mask = result['region'].isna()
            result.loc[mask, 'region'] = result.loc[mask, 'country'].map(self.REGION_MAP)

        return result

    # ─── Recommendation Scoring ───────────────────────────────────────────────

    def compute_recommendation_score(self, df):
        """
        Compute a final recommendation score that combines:
        - priority_score from Orchestrator (venue-level signals)
        - market_score from Market Intelligence (country-level signals)
        - activity signals (event cadence, if available)

        Formula:
          recommendation_score = (
              0.50 * priority_score +    # venue quality + winability
              0.30 * market_score +      # country attractiveness
              0.20 * activity_bonus      # event activity level
          )
        """
        self._log("Computing recommendation scores",
                  "Blending venue priority (50%), market score (30%), activity (20%)")

        def compute_rec(row):
            priority = row.get('priority_score', 50) / 100.0
            market = row.get('market_score', 0) / 100.0

            # Parse activity level from notes if available
            activity_bonus = 0.5  # default neutral
            notes = row.get('notes')
            if notes and isinstance(notes, str):
                try:
                    n = json.loads(notes)
                    level = n.get('activity_level', 'Unknown')
                    if level == 'High':
                        activity_bonus = 1.0
                    elif level == 'Moderate':
                        activity_bonus = 0.6
                    elif level == 'Low':
                        activity_bonus = 0.3
                except (json.JSONDecodeError, TypeError):
                    pass

            score = (0.50 * priority + 0.30 * market + 0.20 * activity_bonus) * 100
            return round(score, 1)

        df['recommendation_score'] = df.apply(compute_rec, axis=1)

        # Assign tiers
        def assign_tier(score):
            if score >= 65:
                return 'Tier 1 — Immediate Outreach'
            elif score >= 61:
                return 'Tier 2 — High Priority'
            elif score >= 48:
                return 'Tier 3 — Monitor'
            else:
                return 'Tier 4 — Low Priority'

        df['recommendation_tier'] = df['recommendation_score'].apply(assign_tier)

        return df

    # ─── Export ───────────────────────────────────────────────────────────────

    def export_recommendations(self, df, market_df=None,
                                filename='tixr_recommendations.xlsx'):
        """Export final recommendations to Excel with analysis sheets."""
        output_path = os.path.join(self.output_dir, filename)
        self._log(f"Exporting recommendations to {output_path}", f"{len(df)} venues")

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # All venues sorted by recommendation score
            df_sorted = df.sort_values('recommendation_score', ascending=False)
            df_sorted.to_excel(writer, sheet_name='All_Recommendations', index=False)

            # Tier 1 targets
            if 'recommendation_tier' in df.columns:
                tier1 = df_sorted[df_sorted['recommendation_tier'].str.contains('Tier 1')]
                tier1.to_excel(writer, sheet_name='Tier1_Immediate', index=False)

                tier2 = df_sorted[df_sorted['recommendation_tier'].str.contains('Tier 2')]
                tier2.to_excel(writer, sheet_name='Tier2_High_Priority', index=False)

            # Market intelligence sheet
            if market_df is not None and len(market_df) > 0:
                market_sorted = market_df.sort_values('market_score', ascending=False)
                market_sorted.to_excel(writer, sheet_name='Market_Intelligence', index=False)

            # Regional summary
            if 'region' in df.columns and 'recommendation_score' in df.columns:
                region_summary = df.groupby('region').agg(
                    total_venues=('venue_name', 'count'),
                    avg_rec_score=('recommendation_score', 'mean'),
                    tier1_count=('recommendation_tier',
                                 lambda x: (x.str.contains('Tier 1')).sum()),
                    avg_market_score=('market_score', 'mean'),
                ).reset_index().sort_values('avg_rec_score', ascending=False)
                region_summary.to_excel(writer, sheet_name='Region_Summary', index=False)

            # Country breakdown
            if 'country' in df.columns and 'recommendation_score' in df.columns:
                country_summary = df.groupby('country').agg(
                    total_venues=('venue_name', 'count'),
                    avg_rec_score=('recommendation_score', 'mean'),
                    tier1_count=('recommendation_tier',
                                 lambda x: (x.str.contains('Tier 1')).sum()),
                    top_platform=('ticketing_platform',
                                  lambda x: x.value_counts().index[0] if x.notna().any() else 'Unknown'),
                ).reset_index().sort_values('avg_rec_score', ascending=False)
                country_summary.to_excel(writer, sheet_name='Country_Breakdown', index=False)

            # Decision log
            log_df = pd.DataFrame(
                self.decision_log + self.market_agent.decision_log
            )
            log_df.to_excel(writer, sheet_name='Decision_Log', index=False)

        logger.info(f"Recommendations exported to {output_path}")
        return output_path

    # ─── Main Entry Point ────────────────────────────────────────────────────

    def generate_recommendations(self, venues_df, config=None):
        """
        Main entry point: takes the enriched venue DataFrame from the
        Orchestrator and produces scored, tiered recommendations.

        config: dict with:
          - countries: list (for market data fetch)
          - use_live_api: bool
          - foursquare_key: str
          - export: bool (default True)
        """
        config = config or {}
        start_time = datetime.now()

        self._log("Starting recommendation generation",
                  f"Input: {len(venues_df)} venues")

        # Configure
        if config.get('foursquare_key'):
            self.configure(foursquare_key=config['foursquare_key'])

        # Extract unique countries from venue data
        countries = config.get('countries')
        if not countries and 'country' in venues_df.columns:
            countries = venues_df['country'].dropna().unique().tolist()

        # Fetch market data
        market_df = self.fetch_market_data(
            countries=countries,
            use_live_api=config.get('use_live_api', False),
        )

        # Merge market data into venues
        enriched_df = self.enrich_with_market_data(venues_df, market_df)

        # Compute recommendation scores
        scored_df = self.compute_recommendation_score(enriched_df)

        # Export
        output_path = None
        if config.get('export', True):
            output_path = self.export_recommendations(scored_df, market_df)

        elapsed = (datetime.now() - start_time).total_seconds()
        tier_counts = scored_df['recommendation_tier'].value_counts().to_dict() \
            if 'recommendation_tier' in scored_df.columns else {}

        self._log(f"Recommendations complete in {elapsed:.1f}s",
                  f"Tiers: {tier_counts}. Output: {output_path}")

        return scored_df, market_df, output_path

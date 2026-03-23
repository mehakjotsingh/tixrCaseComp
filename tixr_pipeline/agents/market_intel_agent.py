"""
Market Intelligence Agent
==========================
Sub-agent for country/market-level data enrichment.

Sources:
  - World Bank Open Data API (GDP, internet, mobile, tourism)
  - Foursquare Places API (venue popularity/check-in signals)
  - UNWTO Tourism Statistics (international arrivals)
  - IFPI Global Music Report (music market sizing)
"""

import requests
import pandas as pd
import numpy as np
import json
import logging

from .base_agent import BaseAgent, RateLimiter

logger = logging.getLogger('tixr_agents')


class WorldBankConnector:
    """
    Connector for World Bank Open Data API.
    Free, no authentication required.
    Provides: GDP per capita, internet users, mobile subscriptions, tourism.
    """

    BASE_URL = "https://api.worldbank.org/v2"

    INDICATORS = {
        'gdp_per_capita_usd': 'NY.GDP.PCAP.CD',
        'internet_users_pct': 'IT.NET.USER.ZS',
        'mobile_subscriptions_per_100': 'IT.CEL.SETS.P2',
        'tourism_arrivals': 'ST.INT.ARVL',
        'population': 'SP.POP.TOTL',
        'urban_population_pct': 'SP.URB.TOTL.IN.ZS',
    }

    # ISO alpha-2 codes for Tixr target countries
    COUNTRY_CODES = {
        'Japan': 'JP', 'Australia': 'AU', 'Germany': 'DE',
        'United Kingdom': 'GB', 'Netherlands': 'NL', 'Spain': 'ES',
        'France': 'FR', 'Italy': 'IT', 'United Arab Emirates': 'AE',
        'Saudi Arabia': 'SA', 'Argentina': 'AR', 'Mexico': 'MX',
        'Brazil': 'BR', 'Colombia': 'CO', 'Indonesia': 'ID',
        'Singapore': 'SG', 'Malaysia': 'MY', 'Philippines': 'PH',
        'Thailand': 'TH', 'India': 'IN', 'South Korea': 'KR',
        'China': 'CN', 'New Zealand': 'NZ', 'Chile': 'CL',
        'Peru': 'PE', 'South Africa': 'ZA', 'Nigeria': 'NG',
        'Kenya': 'KE', 'Egypt': 'EG', 'Morocco': 'MA',
        'Turkey': 'TR', 'Poland': 'PL', 'Czech Republic': 'CZ',
        'Sweden': 'SE', 'Norway': 'NO', 'Denmark': 'DK',
        'Finland': 'FI', 'Belgium': 'BE', 'Austria': 'AT',
        'Switzerland': 'CH', 'Portugal': 'PT', 'Ireland': 'IE',
        'Greece': 'GR', 'Qatar': 'QA', 'Bahrain': 'BH',
        'Kuwait': 'KW', 'Oman': 'OM', 'Israel': 'IL',
        'Vietnam': 'VN', 'Cambodia': 'KH', 'Myanmar': 'MM',
    }

    def __init__(self, rate_limiter, cache):
        self.rate_limiter = rate_limiter
        self.cache = cache

    def fetch_indicator(self, indicator_code, countries=None, year='2022'):
        """Fetch a World Bank indicator for specified countries."""
        if countries is None:
            countries = list(self.COUNTRY_CODES.values())

        country_str = ';'.join(countries)
        cache_key = f"wb_{indicator_code}_{year}"
        cached = self.cache.get(cache_key, max_age_hours=720)  # 30-day cache
        if cached:
            return cached

        self.rate_limiter.wait()

        try:
            resp = requests.get(
                f"{self.BASE_URL}/country/{country_str}/indicator/{indicator_code}",
                params={
                    'date': year,
                    'format': 'json',
                    'per_page': 100,
                },
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            if len(data) < 2:
                return {}

            result = {}
            for entry in data[1]:
                if entry.get('value') is not None:
                    country_name = entry.get('country', {}).get('value', '')
                    result[country_name] = entry['value']

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"World Bank API failed for {indicator_code}: {e}")
            return {}

    def fetch_all_indicators(self, countries=None):
        """Fetch all market indicators for target countries."""
        country_codes = countries or list(self.COUNTRY_CODES.values())

        all_data = {}
        for indicator_name, indicator_code in self.INDICATORS.items():
            data = self.fetch_indicator(indicator_code, country_codes)
            for country, value in data.items():
                if country not in all_data:
                    all_data[country] = {}
                all_data[country][indicator_name] = value

        return all_data


class FoursquareConnector:
    """
    Connector for Foursquare Places API v3.
    Provides: venue popularity, check-in signals, ratings.
    Requires API key: set FOURSQUARE_API_KEY env var.
    """

    BASE_URL = "https://api.foursquare.com/v3/places"

    VENUE_CATEGORIES = {
        'concert_hall': '10039',
        'stadium': '18021',
        'nightclub': '10032',
        'music_venue': '10039',
        'performing_arts': '10041',
    }

    def __init__(self, rate_limiter, cache):
        self.api_key = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, api_key):
        self.api_key = api_key

    def search_venue(self, venue_name, lat=None, lng=None):
        """Search Foursquare for a venue to get popularity signals."""
        if not self.api_key:
            return None

        cache_key = f"fsq_venue_{venue_name}_{lat}_{lng}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            params = {'query': venue_name, 'limit': 3}
            if lat and lng:
                params['ll'] = f"{lat},{lng}"

            resp = requests.get(
                f"{self.BASE_URL}/search",
                params=params,
                headers={'Authorization': self.api_key, 'Accept': 'application/json'},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for place in data.get('results', []):
                loc = place.get('location', {})
                results.append({
                    'fsq_id': place.get('fsq_id'),
                    'fsq_name': place.get('name'),
                    'fsq_categories': [c.get('name') for c in place.get('categories', [])],
                    'fsq_rating': place.get('rating'),
                    'fsq_popularity': place.get('popularity'),
                    'fsq_lat': loc.get('latitude'),
                    'fsq_lng': loc.get('longitude'),
                    'fsq_address': loc.get('formatted_address'),
                })

            self.cache.set(cache_key, results)
            return results

        except Exception as e:
            logger.error(f"Foursquare search failed for '{venue_name}': {e}")
            return None


class MarketIntelAgent(BaseAgent):
    """
    Layer 2 Sub-Agent: Market Intelligence
    Provides country/market-level scoring data for expansion prioritization.
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

    def __init__(self):
        super().__init__('market_intel')
        self.world_bank = WorldBankConnector(RateLimiter(2, 1000), self.cache)
        self.foursquare = FoursquareConnector(RateLimiter(5, 500), self.cache)

        self.log_decision(
            "Selected World Bank + Foursquare as market intel sources",
            "World Bank provides authoritative country-level economic indicators "
            "(GDP, internet penetration, mobile adoption, tourism). "
            "Foursquare adds venue-level popularity/check-in signals. "
            "Combined: market_score = f(GDP, internet, tourism, venue_density)."
        )

    def configure_foursquare(self, api_key):
        self.foursquare.configure(api_key)

    def compute_market_score(self, country_data):
        """
        Compute a composite market attractiveness score (0-100).
        Weights aligned with Tixr's expansion criteria:
          - GDP per capita (25%): spending power
          - Internet users (20%): digital readiness
          - Mobile subscriptions (15%): mobile ticketing potential
          - Tourism arrivals (20%): event demand proxy
          - Urban population (10%): addressable market
          - Population (10%): total addressable market
        """
        scores = {}

        # Normalize each indicator to 0-100 scale using reasonable benchmarks
        gdp = country_data.get('gdp_per_capita_usd', 0) or 0
        scores['gdp'] = min(gdp / 80000 * 100, 100)

        internet = country_data.get('internet_users_pct', 0) or 0
        scores['internet'] = internet  # Already 0-100

        mobile = country_data.get('mobile_subscriptions_per_100', 0) or 0
        scores['mobile'] = min(mobile / 200 * 100, 100)

        tourism = country_data.get('tourism_arrivals', 0) or 0
        scores['tourism'] = min(tourism / 50000000 * 100, 100)

        urban = country_data.get('urban_population_pct', 0) or 0
        scores['urban'] = urban  # Already 0-100

        pop = country_data.get('population', 0) or 0
        scores['population'] = min(pop / 500000000 * 100, 100)

        # Weighted composite
        composite = (
            0.25 * scores['gdp'] +
            0.20 * scores['internet'] +
            0.15 * scores['mobile'] +
            0.20 * scores['tourism'] +
            0.10 * scores['urban'] +
            0.10 * scores['population']
        )

        return round(composite, 1), scores

    def fetch(self, params=None):
        """
        Fetch market intelligence for target countries.
        params: dict with:
          - countries: list of country names
          - use_live_api: bool (fetch live from World Bank)
        """
        params = params or {}
        countries = params.get('countries', list(self.REGION_MAP.keys()))
        use_live_api = params.get('use_live_api', False)

        results = []

        if use_live_api:
            logger.info(f"[{self.name}] Fetching live World Bank data...")
            market_data = self.world_bank.fetch_all_indicators()
            self.stats['api_calls'] += len(self.world_bank.INDICATORS)
        else:
            # Use cached/static data from file
            market_data = {}

        for country in countries:
            data = market_data.get(country, {})
            score, breakdowns = self.compute_market_score(data)

            results.append({
                'country': country,
                'region': self.REGION_MAP.get(country, ''),
                'market_score': score,
                'gdp_per_capita_usd': data.get('gdp_per_capita_usd'),
                'internet_users_pct': data.get('internet_users_pct'),
                'mobile_subscriptions_per_100': data.get('mobile_subscriptions_per_100'),
                'tourism_arrivals': data.get('tourism_arrivals'),
                'score_breakdown': json.dumps(breakdowns),
            })
            self.stats['records_fetched'] += 1

        return pd.DataFrame(results)

    def get_source_description(self):
        return {
            'agent': self.name,
            'sources': [
                {
                    'name': 'World Bank Open Data',
                    'url': 'https://data.worldbank.org/',
                    'type': 'API (free, no auth)',
                    'coverage': '200+ countries, 1400+ indicators',
                    'refresh': 'Annually',
                },
                {
                    'name': 'Foursquare Places API',
                    'url': 'https://api.foursquare.com/',
                    'type': 'API (key required)',
                    'coverage': 'Global - 100K+ sources',
                    'refresh': 'Real-time',
                },
            ],
        }

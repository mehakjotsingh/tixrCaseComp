"""
Venue Discovery Agent
======================
Sub-agent responsible for discovering venues from public data sources.

Sources:
  - Wikidata SPARQL endpoint (structured venue data)
  - OpenStreetMap Overpass API (geo-tagged venues)
  - Google Places API (comprehensive venue type classification)
  - Bandsintown API (artist-linked venue data)
  - MusicBrainz API (open music database with venue places)
  - Foursquare Places API (venue discovery by category)
  - PredictHQ Venues API (event-linked venue discovery)
"""

import requests
import pandas as pd
import numpy as np
import time
import json
import re
import logging

from .base_agent import BaseAgent, RateLimiter

logger = logging.getLogger('tixr_agents')


class WikidataConnector:
    """Connector for Wikidata SPARQL endpoint."""

    ENDPOINT = "https://query.wikidata.org/sparql"

    VENUE_QUERY_TEMPLATE = """
    SELECT ?venue ?venueLabel ?country ?countryLabel ?typeLabel ?capacity
           ?coord ?website ?operatorLabel
    WHERE {{
      ?venue wdt:P17 wd:{country_qid}.
      ?venue wdt:P31/wdt:P279* ?type.
      VALUES ?type {{
        wd:Q483110   # stadium
        wd:Q641226   # arena
        wd:Q24354    # theatre
        wd:Q57660343 # concert hall
        wd:Q18674739 # event venue
        wd:Q622425   # nightclub
        wd:Q1060829  # music venue
        wd:Q641226   # sports venue
        wd:Q1763828  # amphitheatre
        wd:Q1137809  # convention center
        wd:Q856584   # fairground
      }}
      OPTIONAL {{ ?venue wdt:P1083 ?capacity. }}
      OPTIONAL {{ ?venue wdt:P625 ?coord. }}
      OPTIONAL {{ ?venue wdt:P856 ?website. }}
      OPTIONAL {{ ?venue wdt:P137 ?operator. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT 5000
    """

    COUNTRY_QIDS = {
        # EMEA - Western Europe
        'United Kingdom': 'Q145', 'Germany': 'Q183', 'France': 'Q142',
        'Spain': 'Q29', 'Italy': 'Q38', 'Netherlands': 'Q55',
        'Belgium': 'Q31', 'Sweden': 'Q34', 'Norway': 'Q20',
        'Denmark': 'Q35', 'Finland': 'Q33', 'Austria': 'Q40',
        'Switzerland': 'Q39', 'Poland': 'Q36', 'Czech Republic': 'Q213',
        'Portugal': 'Q45', 'Ireland': 'Q27', 'Greece': 'Q41',
        'Turkey': 'Q43',
        # EMEA - Gulf
        'United Arab Emirates': 'Q878', 'Saudi Arabia': 'Q851',
        'Qatar': 'Q846', 'Bahrain': 'Q398', 'Kuwait': 'Q817',
        'Oman': 'Q842', 'Israel': 'Q801',
        # EMEA - Africa
        'South Africa': 'Q258', 'Nigeria': 'Q1033', 'Kenya': 'Q114',
        'Egypt': 'Q79', 'Morocco': 'Q1028',
        # APAC
        'Japan': 'Q17', 'Australia': 'Q408', 'India': 'Q668',
        'South Korea': 'Q884', 'China': 'Q148', 'New Zealand': 'Q664',
        # LATAM
        'Brazil': 'Q155', 'Mexico': 'Q96', 'Argentina': 'Q414',
        'Colombia': 'Q739', 'Chile': 'Q298', 'Peru': 'Q419',
        # SEA
        'Thailand': 'Q869', 'Indonesia': 'Q252', 'Singapore': 'Q334',
        'Malaysia': 'Q833', 'Philippines': 'Q928', 'Vietnam': 'Q881',
    }

    def __init__(self, rate_limiter, cache):
        self.rate_limiter = rate_limiter
        self.cache = cache
        self.rate_limiter.calls_per_second = 0.5

    def query_country(self, country, country_qid):
        """Query Wikidata for venues in a specific country."""
        cache_key = f"wikidata_venues_{country}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return pd.DataFrame(cached)

        self.rate_limiter.wait()
        query = self.VENUE_QUERY_TEMPLATE.format(country_qid=country_qid)

        try:
            resp = requests.get(
                self.ENDPOINT,
                params={'query': query, 'format': 'json'},
                headers={'User-Agent': 'TixrVenueIntel/1.0 (research)'},
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get('results', {}).get('bindings', []):
                venue_uri = item.get('venue', {}).get('value', '')
                qid = venue_uri.split('/')[-1] if venue_uri else None

                coord = item.get('coord', {}).get('value', '')
                lat, lng = None, None
                if coord:
                    match = re.search(r'Point\(([-\d.]+)\s+([-\d.]+)\)', coord)
                    if match:
                        lng, lat = float(match.group(1)), float(match.group(2))

                results.append({
                    'wikidata_id': qid,
                    'venue_name': item.get('venueLabel', {}).get('value', ''),
                    'country': item.get('countryLabel', {}).get('value', country),
                    'venue_type': item.get('typeLabel', {}).get('value', ''),
                    'capacity': item.get('capacity', {}).get('value', None),
                    'latitude': lat,
                    'longitude': lng,
                    'website': item.get('website', {}).get('value', ''),
                    'venue_operator': item.get('operatorLabel', {}).get('value', ''),
                })

            self.cache.set(cache_key, results)
            return pd.DataFrame(results) if results else pd.DataFrame()

        except Exception as e:
            logger.error(f"Wikidata query failed for {country}: {e}")
            return pd.DataFrame()


class OSMOverpassConnector:
    """Connector for OpenStreetMap Overpass API."""

    ENDPOINT = "https://overpass-api.de/api/interpreter"

    QUERY_TEMPLATE = """
    [out:json][timeout:90];
    area["name:en"="{city}"]->.searchArea;
    (
      node["amenity"="nightclub"](area.searchArea);
      node["amenity"="theatre"](area.searchArea);
      node["leisure"="stadium"](area.searchArea);
      node["amenity"="events_venue"](area.searchArea);
      node["amenity"="music_venue"](area.searchArea);
      node["amenity"="concert_hall"](area.searchArea);
      node["amenity"="community_centre"](area.searchArea);
      node["amenity"="arts_centre"](area.searchArea);
      node["leisure"="sports_centre"](area.searchArea);
      way["amenity"="nightclub"](area.searchArea);
      way["amenity"="theatre"](area.searchArea);
      way["leisure"="stadium"](area.searchArea);
      way["amenity"="events_venue"](area.searchArea);
      way["amenity"="music_venue"](area.searchArea);
      way["amenity"="concert_hall"](area.searchArea);
      way["leisure"="sports_centre"](area.searchArea);
    );
    out center body;
    """

    TARGET_CITIES = [
        # EMEA
        'London', 'Berlin', 'Paris', 'Madrid', 'Amsterdam', 'Barcelona',
        'Milan', 'Munich', 'Stockholm', 'Warsaw', 'Istanbul', 'Lisbon',
        'Brussels', 'Vienna', 'Prague', 'Dublin', 'Copenhagen',
        # EMEA Gulf
        'Dubai', 'Riyadh', 'Doha', 'Abu Dhabi', 'Jeddah',
        # EMEA Africa
        'Johannesburg', 'Cape Town', 'Lagos', 'Nairobi', 'Cairo',
        # APAC
        'Tokyo', 'Sydney', 'Melbourne', 'Mumbai', 'Delhi', 'Seoul',
        'Shanghai', 'Beijing', 'Hong Kong', 'Osaka',
        # LATAM
        'São Paulo', 'Buenos Aires', 'Mexico City', 'Bogota', 'Lima',
        'Santiago', 'Rio de Janeiro', 'Guadalajara', 'Medellín',
        # SEA
        'Singapore', 'Bangkok', 'Jakarta', 'Manila', 'Kuala Lumpur',
        'Ho Chi Minh City', 'Bali',
    ]

    def __init__(self, rate_limiter, cache):
        self.rate_limiter = rate_limiter
        self.cache = cache
        self.rate_limiter.calls_per_second = 0.2

    def query_city(self, city):
        """Query OSM Overpass for venues in a city."""
        cache_key = f"osm_venues_{city}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return pd.DataFrame(cached)

        self.rate_limiter.wait()
        query = self.QUERY_TEMPLATE.format(city=city)

        try:
            resp = requests.post(
                self.ENDPOINT,
                data={'data': query},
                timeout=120
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for elem in data.get('elements', []):
                tags = elem.get('tags', {})
                lat = elem.get('lat') or elem.get('center', {}).get('lat')
                lng = elem.get('lon') or elem.get('center', {}).get('lon')

                vtype = 'venue'
                for key in ['amenity', 'leisure']:
                    if key in tags:
                        vtype = tags[key]

                results.append({
                    'osm_id': str(elem.get('id', '')),
                    'venue_name': tags.get('name', ''),
                    'city': city,
                    'venue_type': vtype,
                    'capacity': tags.get('capacity'),
                    'latitude': lat,
                    'longitude': lng,
                    'website': tags.get('website', ''),
                    'address': tags.get('addr:street', ''),
                    'phone': tags.get('phone', ''),
                    'venue_operator': tags.get('operator', ''),
                    'opening_hours': tags.get('opening_hours', ''),
                })

            self.cache.set(cache_key, results)
            return pd.DataFrame(results) if results else pd.DataFrame()

        except Exception as e:
            logger.error(f"OSM query failed for {city}: {e}")
            return pd.DataFrame()


class GooglePlacesConnector:
    """
    Connector for Google Places API (New).
    Requires API key - set GOOGLE_PLACES_API_KEY env var.
    """

    ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

    VENUE_TYPES = [
        'concert_hall', 'stadium', 'arena', 'amphitheatre',
        'live_music_venue', 'night_club', 'performing_arts_theater',
        'convention_center', 'event_venue', 'banquet_hall',
    ]

    def __init__(self, rate_limiter, cache):
        self.api_key = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, api_key):
        self.api_key = api_key

    def search_venues(self, city, country, venue_type='concert_hall'):
        """Search for venues of a specific type in a city."""
        if not self.api_key:
            return pd.DataFrame()

        cache_key = f"gplaces_{city}_{country}_{venue_type}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return pd.DataFrame(cached)

        self.rate_limiter.wait()

        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': self.api_key,
            'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,'
                                'places.location,places.websiteUri,'
                                'places.types,places.googleMapsUri,'
                                'places.rating,places.userRatingCount',
        }

        body = {
            'textQuery': f'{venue_type} in {city}, {country}',
            'maxResultCount': 20,
        }

        try:
            resp = requests.post(self.ENDPOINT, headers=headers, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = []
            for place in data.get('places', []):
                loc = place.get('location', {})
                results.append({
                    'venue_name': place.get('displayName', {}).get('text', ''),
                    'city': city,
                    'country': country,
                    'venue_type': venue_type,
                    'latitude': loc.get('latitude'),
                    'longitude': loc.get('longitude'),
                    'address': place.get('formattedAddress', ''),
                    'website': place.get('websiteUri', ''),
                    'google_maps_url': place.get('googleMapsUri', ''),
                })

            self.cache.set(cache_key, results)
            return pd.DataFrame(results) if results else pd.DataFrame()

        except Exception as e:
            logger.error(f"Google Places query failed for {city}/{venue_type}: {e}")
            return pd.DataFrame()


class BandsintownConnector:
    """
    Connector for Bandsintown API.
    Returns venues linked to artist touring data — high-signal for live music venues.
    Requires app_id (free registration).
    """

    BASE_URL = "https://rest.bandsintown.com"

    def __init__(self, rate_limiter, cache):
        self.app_id = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, app_id):
        self.app_id = app_id

    def get_artist_events(self, artist_name):
        """Get upcoming events for an artist → extract unique venues."""
        if not self.app_id:
            return []

        cache_key = f"bit_artist_{artist_name}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            resp = requests.get(
                f"{self.BASE_URL}/artists/{artist_name}/events",
                params={'app_id': self.app_id},
                timeout=15
            )
            resp.raise_for_status()
            events = resp.json()

            venues = {}
            for event in events:
                venue = event.get('venue', {})
                vid = venue.get('name', '')
                if vid and vid not in venues:
                    venues[vid] = {
                        'venue_name': venue.get('name'),
                        'city': venue.get('city'),
                        'country': venue.get('country'),
                        'region': venue.get('region'),
                        'latitude': venue.get('latitude'),
                        'longitude': venue.get('longitude'),
                        'venue_type': 'music_venue',
                    }

            result = list(venues.values())
            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Bandsintown events failed for '{artist_name}': {e}")
            return []

    def discover_venues_via_artists(self, artists):
        """Discover venues by querying multiple touring artists."""
        all_venues = {}
        for artist in artists:
            venues = self.get_artist_events(artist)
            for v in venues:
                key = f"{v['venue_name']}_{v.get('city', '')}".lower()
                if key not in all_venues:
                    all_venues[key] = v
        return list(all_venues.values())


class MusicBrainzConnector:
    """
    Connector for MusicBrainz API — open music encyclopedia.
    Has a 'place' entity type for venues with geo-coordinates.
    No auth required, 1 call/sec rate limit.
    """

    BASE_URL = "https://musicbrainz.org/ws/2"

    def __init__(self, rate_limiter, cache):
        self.rate_limiter = rate_limiter
        self.cache = cache

    def search_venues(self, query, venue_type=None, limit=100):
        """Search MusicBrainz places (venues) by name or area."""
        cache_key = f"mb_place_{query}_{venue_type}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return cached

        self.rate_limiter.wait()

        try:
            params = {
                'query': query,
                'limit': limit,
                'fmt': 'json',
            }
            if venue_type:
                params['query'] += f' AND type:{venue_type}'

            resp = requests.get(
                f"{self.BASE_URL}/place",
                params=params,
                headers={'User-Agent': 'TixrVenueIntel/1.0 (research)'},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for place in data.get('places', []):
                coords = place.get('coordinates', {})
                area = place.get('area', {})
                results.append({
                    'mb_id': place.get('id'),
                    'venue_name': place.get('name'),
                    'venue_type': place.get('type', 'venue'),
                    'city': area.get('name', ''),
                    'latitude': coords.get('latitude'),
                    'longitude': coords.get('longitude'),
                    'address': place.get('address', ''),
                    'disambiguation': place.get('disambiguation', ''),
                })

            self.cache.set(cache_key, results)
            return results

        except Exception as e:
            logger.error(f"MusicBrainz search failed for '{query}': {e}")
            return []

    def search_venues_by_area(self, country):
        """Search for venues in a specific country."""
        return self.search_venues(f'area:"{country}"', limit=100)


class PredictHQVenueConnector:
    """
    Connector for PredictHQ Venues API.
    Discovers venues via event intelligence. Requires access token.
    """

    BASE_URL = "https://api.predicthq.com/v1"

    def __init__(self, rate_limiter, cache):
        self.token = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, token):
        self.token = token

    def search_venues(self, query, country=None, limit=50):
        """Search PredictHQ for venues."""
        if not self.token:
            return []

        cache_key = f"phq_venue_{query}_{country}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return cached

        self.rate_limiter.wait()

        try:
            params = {'q': query, 'limit': limit}
            if country:
                params['country'] = country

            resp = requests.get(
                f"{self.BASE_URL}/venues/",
                params=params,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for venue in data.get('results', []):
                geo = venue.get('location', [None, None])
                results.append({
                    'phq_id': venue.get('id'),
                    'venue_name': venue.get('name'),
                    'venue_type': venue.get('type', 'venue'),
                    'address': venue.get('formatted_address', ''),
                    'latitude': geo[1] if len(geo) > 1 else None,
                    'longitude': geo[0] if len(geo) > 0 else None,
                })

            self.cache.set(cache_key, results)
            return results

        except Exception as e:
            logger.error(f"PredictHQ venue search failed: {e}")
            return []


class FoursquareDiscoveryConnector:
    """
    Connector for Foursquare Places API v3 — venue discovery by category.
    Separately from MarketIntel, this is used purely for venue discovery.
    """

    BASE_URL = "https://api.foursquare.com/v3/places"

    CATEGORY_IDS = {
        'concert_hall': '10039',
        'stadium': '18021',
        'nightclub': '10032',
        'performing_arts': '10041',
        'amphitheater': '16003',
        'convention_center': '12072',
    }

    def __init__(self, rate_limiter, cache):
        self.api_key = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, api_key):
        self.api_key = api_key

    def search_by_category(self, category_id, lat, lng, radius=50000):
        """Search for venues by Foursquare category near coordinates."""
        if not self.api_key:
            return []

        cache_key = f"fsq_disc_{category_id}_{lat}_{lng}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return cached

        self.rate_limiter.wait()

        try:
            resp = requests.get(
                f"{self.BASE_URL}/search",
                params={
                    'll': f'{lat},{lng}',
                    'radius': radius,
                    'categories': category_id,
                    'limit': 50,
                },
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
                    'venue_name': place.get('name'),
                    'venue_type': [c.get('name') for c in place.get('categories', [])][0]
                        if place.get('categories') else 'venue',
                    'latitude': loc.get('latitude'),
                    'longitude': loc.get('longitude'),
                    'address': loc.get('formatted_address', ''),
                    'city': loc.get('locality', ''),
                    'country': loc.get('country', ''),
                })

            self.cache.set(cache_key, results)
            return results

        except Exception as e:
            logger.error(f"Foursquare discovery failed: {e}")
            return []


# ─── Major touring artists for Bandsintown venue discovery ───────────
DEFAULT_TOURING_ARTISTS = [
    'Coldplay', 'Ed Sheeran', 'Taylor Swift', 'Bad Bunny', 'Drake',
    'The Weeknd', 'Dua Lipa', 'BTS', 'Blackpink', 'Ado',
    'Rosalía', 'Karol G', 'Anitta', 'King', 'Atif Aslam',
    'Babymetal', 'ONE OK ROCK', 'Stray Kids', 'TWICE',
    'Rammstein', 'Iron Maiden', 'Metallica', 'Imagine Dragons',
    'Arctic Monkeys', 'Tame Impala', 'Fred Again..', 'Peggy Gou',
]

# ─── City coordinates for Foursquare category search ─────────────────
CITY_COORDS = {
    'London': (51.5074, -0.1278), 'Berlin': (52.5200, 13.4050),
    'Paris': (48.8566, 2.3522), 'Tokyo': (35.6762, 139.6503),
    'Singapore': (1.3521, 103.8198), 'Dubai': (25.2048, 55.2708),
    'São Paulo': (-23.5505, -46.6333), 'Sydney': (-33.8688, 151.2093),
    'Bangkok': (13.7563, 100.5018), 'Mumbai': (19.0760, 72.8777),
    'Seoul': (37.5665, 126.9780), 'Mexico City': (19.4326, -99.1332),
    'Buenos Aires': (-34.6037, -58.3816), 'Jakarta': (-6.2088, 106.8456),
    'Riyadh': (24.7136, 46.6753), 'Lagos': (6.5244, 3.3792),
    'Cairo': (30.0444, 31.2357), 'Johannesburg': (-26.2041, 28.0473),
}


class VenueDiscoveryAgent(BaseAgent):
    """
    Layer 2 Sub-Agent: Venue Discovery
    Pulls venue data from 7 sources: Wikidata, OSM, Google Places,
    Bandsintown, MusicBrainz, PredictHQ, and Foursquare.
    """

    def __init__(self):
        super().__init__('venue_discovery')
        self.wikidata = WikidataConnector(RateLimiter(0.5, 5000), self.cache)
        self.osm = OSMOverpassConnector(RateLimiter(0.2, 10000), self.cache)
        self.google_places = GooglePlacesConnector(RateLimiter(1, 1000), self.cache)
        self.bandsintown = BandsintownConnector(RateLimiter(1, 5000), self.cache)
        self.musicbrainz = MusicBrainzConnector(RateLimiter(1, 5000), self.cache)
        self.predicthq = PredictHQVenueConnector(RateLimiter(2, 1000), self.cache)
        self.foursquare = FoursquareDiscoveryConnector(RateLimiter(5, 500), self.cache)

        self.log_decision(
            "Selected 7 discovery sources for maximum venue coverage",
            "Wikidata: structured global data with Q-IDs. "
            "OSM: granular city-level venue tags. "
            "Google Places: comprehensive type taxonomy. "
            "Bandsintown: artist-linked venue discovery (live music). "
            "MusicBrainz: open music database with venue places. "
            "PredictHQ: event-intelligence-linked venues. "
            "Foursquare: category-based venue discovery."
        )

    def configure(self, google_places_key=None, bandsintown_app_id=None,
                  predicthq_token=None, foursquare_key=None):
        """Configure API keys for optional discovery sources."""
        if google_places_key:
            self.google_places.configure(google_places_key)
        if bandsintown_app_id:
            self.bandsintown.configure(bandsintown_app_id)
        if predicthq_token:
            self.predicthq.configure(predicthq_token)
        if foursquare_key:
            self.foursquare.configure(foursquare_key)

    def fetch(self, params=None):
        """
        Fetch venues from all discovery sources.
        params: dict with optional keys:
          - countries: list of country names
          - cities: list of city names
          - use_google: bool
          - use_bandsintown: bool
          - use_musicbrainz: bool
          - use_predicthq: bool
          - use_foursquare: bool
          - touring_artists: list of artist names for Bandsintown
        """
        params = params or {}
        countries = params.get('countries', list(WikidataConnector.COUNTRY_QIDS.keys()))
        cities = params.get('cities', OSMOverpassConnector.TARGET_CITIES)
        use_google = params.get('use_google', False)
        use_bandsintown = params.get('use_bandsintown', False)
        use_musicbrainz = params.get('use_musicbrainz', True)
        use_predicthq = params.get('use_predicthq', False)
        use_foursquare = params.get('use_foursquare', False)

        all_dfs = []

        # 1. Wikidata venues (always — free, no auth)
        logger.info(f"[{self.name}] Querying Wikidata for {len(countries)} countries...")
        for country in countries:
            qid = WikidataConnector.COUNTRY_QIDS.get(country)
            if qid:
                df = self.wikidata.query_country(country, qid)
                if len(df) > 0:
                    df['data_sources'] = 'wikidata'
                    all_dfs.append(df)
                    self.stats['records_fetched'] += len(df)
                    self.stats['api_calls'] += 1

        # 2. OSM venues (always — free, no auth)
        logger.info(f"[{self.name}] Querying OSM for {len(cities)} cities...")
        for city in cities:
            df = self.osm.query_city(city)
            if len(df) > 0:
                df['data_sources'] = 'osm'
                all_dfs.append(df)
                self.stats['records_fetched'] += len(df)
                self.stats['api_calls'] += 1

        # 3. MusicBrainz venues (always — free, no auth, 1 call/sec)
        if use_musicbrainz:
            logger.info(f"[{self.name}] Querying MusicBrainz for {len(countries)} countries...")
            for country in countries[:15]:  # Limit to top countries
                results = self.musicbrainz.search_venues_by_area(country)
                if results:
                    df = pd.DataFrame(results)
                    df['country'] = country
                    df['data_sources'] = 'musicbrainz'
                    all_dfs.append(df)
                    self.stats['records_fetched'] += len(df)
                    self.stats['api_calls'] += 1

        # 4. Google Places (requires API key)
        if use_google and self.google_places.api_key:
            logger.info(f"[{self.name}] Querying Google Places...")
            for city in cities[:10]:
                for vtype in GooglePlacesConnector.VENUE_TYPES[:4]:
                    df = self.google_places.search_venues(city, '', vtype)
                    if len(df) > 0:
                        df['data_sources'] = 'google_places'
                        all_dfs.append(df)
                        self.stats['records_fetched'] += len(df)
                        self.stats['api_calls'] += 1

        # 5. Bandsintown (requires app_id — free)
        if use_bandsintown and self.bandsintown.app_id:
            artists = params.get('touring_artists', DEFAULT_TOURING_ARTISTS)
            logger.info(f"[{self.name}] Querying Bandsintown via {len(artists)} artists...")
            venues = self.bandsintown.discover_venues_via_artists(artists)
            if venues:
                df = pd.DataFrame(venues)
                df['data_sources'] = 'bandsintown'
                all_dfs.append(df)
                self.stats['records_fetched'] += len(df)
                self.stats['api_calls'] += len(artists)

        # 6. PredictHQ (requires token)
        if use_predicthq and self.predicthq.token:
            logger.info(f"[{self.name}] Querying PredictHQ...")
            for city in cities[:10]:
                results = self.predicthq.search_venues(city)
                if results:
                    df = pd.DataFrame(results)
                    df['data_sources'] = 'predicthq'
                    all_dfs.append(df)
                    self.stats['records_fetched'] += len(df)
                    self.stats['api_calls'] += 1

        # 7. Foursquare category discovery (requires key)
        if use_foursquare and self.foursquare.api_key:
            logger.info(f"[{self.name}] Querying Foursquare category discovery...")
            for city, (lat, lng) in list(CITY_COORDS.items())[:10]:
                for cat_name, cat_id in FoursquareDiscoveryConnector.CATEGORY_IDS.items():
                    results = self.foursquare.search_by_category(cat_id, lat, lng)
                    if results:
                        df = pd.DataFrame(results)
                        df['data_sources'] = 'foursquare'
                        all_dfs.append(df)
                        self.stats['records_fetched'] += len(df)
                        self.stats['api_calls'] += 1

        if not all_dfs:
            return pd.DataFrame(columns=self.UNIFIED_SCHEMA)

        result = pd.concat(all_dfs, ignore_index=True)
        return self.to_unified_schema(result)

    def get_source_description(self):
        return {
            'agent': self.name,
            'sources': [
                {
                    'name': 'Wikidata SPARQL',
                    'url': 'https://query.wikidata.org/',
                    'type': 'API (free, no auth)',
                    'coverage': 'Global — 92K+ venues, 42 countries',
                    'refresh': 'On-demand via SPARQL',
                },
                {
                    'name': 'OpenStreetMap Overpass',
                    'url': 'https://overpass-api.de/',
                    'type': 'API (free, no auth)',
                    'coverage': 'Global — 50+ cities, granular tags',
                    'refresh': 'On-demand',
                },
                {
                    'name': 'Google Places API (New)',
                    'url': 'https://developers.google.com/maps/documentation/places/',
                    'type': 'API (requires key + billing)',
                    'coverage': 'Global — 200+ place types',
                    'refresh': 'Real-time',
                },
                {
                    'name': 'Bandsintown API',
                    'url': 'https://artists.bandsintown.com/support/api-installation',
                    'type': 'API (free app_id)',
                    'coverage': 'Global — artist touring circuit venues',
                    'refresh': 'Real-time (event-based)',
                },
                {
                    'name': 'MusicBrainz API',
                    'url': 'https://musicbrainz.org/doc/MusicBrainz_API',
                    'type': 'API (free, no auth, 1 call/sec)',
                    'coverage': 'Global — open music encyclopedia',
                    'refresh': 'Community-maintained',
                },
                {
                    'name': 'PredictHQ Venues API',
                    'url': 'https://docs.predicthq.com/resources/venues',
                    'type': 'API (requires token)',
                    'coverage': 'Global — event-intelligence-linked',
                    'refresh': 'Real-time',
                },
                {
                    'name': 'Foursquare Places API',
                    'url': 'https://docs.foursquare.com/developer/reference/place-search',
                    'type': 'API (requires key)',
                    'coverage': 'Global — 100M+ places, category-based',
                    'refresh': 'Real-time',
                },
            ],
        }

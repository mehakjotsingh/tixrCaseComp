"""
Event Enrichment Agent
=======================
Sub-agent for enriching venues with event activity signals.

Sources:
  - Songkick API (concert data, event cadence)
  - Setlist.fm API (historical concert frequency)
  - Eventbrite API (international event data)
  - Bandsintown Events API (artist touring events at venue)
  - PredictHQ Events API (demand intelligence per venue)
  - Skiddle API (UK event data — festivals, clubs, gigs)
  - Resident Advisor scraping (electronic music venues)
"""

import requests
import pandas as pd
import numpy as np
import json
import re
import logging
from datetime import datetime, timedelta

from .base_agent import BaseAgent, RateLimiter

logger = logging.getLogger('tixr_agents')


class SongkickConnector:
    """
    Connector for Songkick API.
    Provides: venue search, event listings, capacity, event cadence.
    Requires API key: set SONGKICK_API_KEY env var.
    """

    BASE_URL = "https://api.songkick.com/api/3.0"

    def __init__(self, rate_limiter, cache):
        self.api_key = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, api_key):
        self.api_key = api_key

    def search_venue(self, venue_name):
        """Search for a venue by name, return venue ID and metadata."""
        if not self.api_key:
            return None

        cache_key = f"songkick_venue_{venue_name}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            resp = requests.get(
                f"{self.BASE_URL}/search/venues.json",
                params={'apikey': self.api_key, 'query': venue_name},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            venues = data.get('resultsPage', {}).get('results', {}).get('venue', [])
            result = []
            for v in venues[:3]:
                result.append({
                    'sk_id': v.get('id'),
                    'sk_name': v.get('displayName'),
                    'sk_city': v.get('city', {}).get('displayName'),
                    'sk_country': v.get('city', {}).get('country', {}).get('displayName'),
                    'sk_capacity': v.get('capacity'),
                    'sk_uri': v.get('uri'),
                    'sk_lat': v.get('lat'),
                    'sk_lng': v.get('lng'),
                })

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Songkick venue search failed for '{venue_name}': {e}")
            return None

    def get_venue_events(self, sk_venue_id):
        """Get upcoming events for a Songkick venue."""
        if not self.api_key:
            return None

        cache_key = f"songkick_events_{sk_venue_id}"
        cached = self.cache.get(cache_key, max_age_hours=24)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            resp = requests.get(
                f"{self.BASE_URL}/venues/{sk_venue_id}/calendar.json",
                params={'apikey': self.api_key},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            events = data.get('resultsPage', {}).get('results', {}).get('event', [])
            result = {
                'upcoming_count': len(events),
                'total': data.get('resultsPage', {}).get('totalEntries', 0),
                'events': [
                    {
                        'name': e.get('displayName'),
                        'date': e.get('start', {}).get('date'),
                        'type': e.get('type'),
                        'popularity': e.get('popularity', 0),
                        'ticket_url': None,
                    }
                    for e in events[:20]
                ],
            }

            # Extract ticket URLs for platform detection
            for i, e in enumerate(events[:20]):
                if e.get('uri'):
                    result['events'][i]['ticket_url'] = e['uri']

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Songkick events failed for venue {sk_venue_id}: {e}")
            return None


class SetlistFmConnector:
    """
    Connector for Setlist.fm API.
    Provides: historical concert data, venue activity scoring.
    Requires API key: set SETLISTFM_API_KEY env var.
    """

    BASE_URL = "https://api.setlist.fm/rest/1.0"

    def __init__(self, rate_limiter, cache):
        self.api_key = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, api_key):
        self.api_key = api_key

    def search_venue(self, venue_name, city=None):
        """Search for a venue and get historical event count."""
        if not self.api_key:
            return None

        cache_key = f"setlistfm_venue_{venue_name}_{city or 'any'}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            params = {'name': venue_name, 'p': 1}
            if city:
                params['cityName'] = city

            resp = requests.get(
                f"{self.BASE_URL}/search/venues",
                params=params,
                headers={
                    'x-api-key': self.api_key,
                    'Accept': 'application/json',
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            venues = data.get('venue', [])
            result = []
            for v in venues[:3]:
                result.append({
                    'sfm_id': v.get('id'),
                    'sfm_name': v.get('name'),
                    'sfm_city': v.get('city', {}).get('name'),
                    'sfm_country': v.get('city', {}).get('country', {}).get('name'),
                })

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Setlist.fm venue search failed: {e}")
            return None

    def get_venue_setlists(self, sfm_venue_id):
        """Get historical setlists for event frequency scoring."""
        if not self.api_key:
            return None

        cache_key = f"setlistfm_setlists_{sfm_venue_id}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            resp = requests.get(
                f"{self.BASE_URL}/venue/{sfm_venue_id}/setlists",
                params={'p': 1},
                headers={
                    'x-api-key': self.api_key,
                    'Accept': 'application/json',
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            total = data.get('total', 0)
            setlists = data.get('setlist', [])

            result = {
                'total_historical_events': total,
                'recent_events': [
                    {
                        'artist': s.get('artist', {}).get('name'),
                        'date': s.get('eventDate'),
                        'tour': s.get('tour', {}).get('name'),
                    }
                    for s in setlists[:10]
                ],
            }

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Setlist.fm setlists failed for venue {sfm_venue_id}: {e}")
            return None


class EventbriteConnector:
    """
    Connector for Eventbrite API v3.
    Provides: venue search, capacity, events, international coverage.
    Requires OAuth token: set EVENTBRITE_TOKEN env var.
    """

    BASE_URL = "https://www.eventbriteapi.com/v3"

    def __init__(self, rate_limiter, cache):
        self.token = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, token):
        self.token = token

    def search_venues(self, query, location=None):
        """Search Eventbrite for venues."""
        if not self.token:
            return None

        cache_key = f"eventbrite_venue_{query}_{location or 'any'}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            params = {'q': query, 'expand': 'venue'}
            if location:
                params['location.address'] = location

            resp = requests.get(
                f"{self.BASE_URL}/events/search/",
                params=params,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            venues_seen = {}
            for event in data.get('events', []):
                venue = event.get('venue', {})
                vid = venue.get('id')
                if vid and vid not in venues_seen:
                    venues_seen[vid] = {
                        'eb_id': vid,
                        'venue_name': venue.get('name'),
                        'city': venue.get('address', {}).get('city'),
                        'country': venue.get('address', {}).get('country'),
                        'capacity': venue.get('capacity'),
                        'latitude': venue.get('latitude'),
                        'longitude': venue.get('longitude'),
                        'address': venue.get('address', {}).get('localized_address_display'),
                    }

            result = list(venues_seen.values())
            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Eventbrite search failed for '{query}': {e}")
            return None


class ResidentAdvisorConnector:
    """
    Scraper for Resident Advisor (ra.co).
    Provides: electronic music venue data, club scene intelligence.
    Uses GraphQL scraping approach.
    """

    BASE_URL = "https://ra.co/graphql"

    def __init__(self, rate_limiter, cache):
        self.rate_limiter = rate_limiter
        self.cache = cache

    def get_clubs_by_city(self, city_slug):
        """
        Query RA for clubs/venues in a city.
        city_slug examples: 'london', 'berlin', 'tokyo', 'bangkok'
        """
        cache_key = f"ra_clubs_{city_slug}"
        cached = self.cache.get(cache_key, max_age_hours=168)
        if cached:
            return cached

        self.rate_limiter.wait()

        query = """
        query GET_POPULAR_VENUES($filters: VenueFilters) {
          listing(filters: $filters) {
            data {
              id
              name
              address
              contentUrl
              area { name country { name } }
            }
            totalResults
          }
        }
        """

        try:
            resp = requests.post(
                self.BASE_URL,
                json={
                    'query': query,
                    'variables': {
                        'filters': {
                            'areas': {'eq': city_slug},
                            'pageSize': 50,
                        }
                    }
                },
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': f'https://ra.co/clubs/{city_slug}',
                },
                timeout=30
            )

            if resp.status_code == 200:
                data = resp.json()
                venues = data.get('data', {}).get('listing', {}).get('data', [])
                result = []
                for v in venues:
                    area = v.get('area', {})
                    result.append({
                        'ra_id': v.get('id'),
                        'venue_name': v.get('name'),
                        'address': v.get('address'),
                        'city': area.get('name', city_slug),
                        'country': area.get('country', {}).get('name', ''),
                        'venue_type': 'nightclub',
                        'ra_url': f"https://ra.co{v.get('contentUrl', '')}",
                    })

                self.cache.set(cache_key, result)
                return result
            else:
                logger.warning(f"RA GraphQL returned {resp.status_code} for {city_slug}")
                return []

        except Exception as e:
            logger.error(f"RA scrape failed for {city_slug}: {e}")
            return []


class BandsintownEventsConnector:
    """
    Connector for Bandsintown API — enrichment mode.
    Given a venue name, find events via artist search to estimate activity.
    """

    BASE_URL = "https://rest.bandsintown.com"

    def __init__(self, rate_limiter, cache):
        self.app_id = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, app_id):
        self.app_id = app_id

    def get_venue_events_via_artist(self, artist_name, venue_name):
        """Check if an artist has events at a specific venue."""
        if not self.app_id:
            return []

        cache_key = f"bit_enrich_{artist_name}_{venue_name}"
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

            matches = []
            for event in events:
                ev_venue = event.get('venue', {}).get('name', '')
                if venue_name.lower() in ev_venue.lower() or ev_venue.lower() in venue_name.lower():
                    matches.append({
                        'artist': artist_name,
                        'date': event.get('datetime'),
                        'venue': ev_venue,
                        'ticket_url': event.get('url'),
                    })

            self.cache.set(cache_key, matches)
            return matches

        except Exception as e:
            logger.debug(f"Bandsintown enrichment failed for {artist_name}: {e}")
            return []


class PredictHQEventsConnector:
    """
    Connector for PredictHQ Events API — demand intelligence.
    Provides: event count, categories, and demand rank for a venue/area.
    """

    BASE_URL = "https://api.predicthq.com/v1"

    def __init__(self, rate_limiter, cache):
        self.token = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, token):
        self.token = token

    def get_events_near_venue(self, lat, lng, radius_km=2, days_ahead=90):
        """Get upcoming events near a venue location."""
        if not self.token:
            return None

        cache_key = f"phq_events_{lat}_{lng}_{radius_km}"
        cached = self.cache.get(cache_key, max_age_hours=24)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            start = datetime.utcnow().strftime('%Y-%m-%d')
            end = (datetime.utcnow() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

            resp = requests.get(
                f"{self.BASE_URL}/events/",
                params={
                    'within': f'{radius_km}km@{lat},{lng}',
                    'active.gte': start,
                    'active.lte': end,
                    'category': 'concerts,performing-arts,sports,festivals',
                    'limit': 50,
                },
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            result = {
                'event_count': data.get('count', 0),
                'categories': {},
                'events': [],
            }

            for event in data.get('results', []):
                cat = event.get('category', 'other')
                result['categories'][cat] = result['categories'].get(cat, 0) + 1
                result['events'].append({
                    'title': event.get('title'),
                    'category': cat,
                    'start': event.get('start'),
                    'rank': event.get('rank'),
                    'local_rank': event.get('local_rank'),
                })

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"PredictHQ events failed: {e}")
            return None


class SkiddleConnector:
    """
    Connector for Skiddle API — UK event data.
    Strong for: UK festivals, club nights, gigs.
    Free API key available.
    """

    BASE_URL = "https://www.skiddle.com/api/v1"

    def __init__(self, rate_limiter, cache):
        self.api_key = None
        self.rate_limiter = rate_limiter
        self.cache = cache

    def configure(self, api_key):
        self.api_key = api_key

    def get_venue_events(self, venue_name, latitude=None, longitude=None):
        """Get events at or near a venue."""
        if not self.api_key:
            return None

        cache_key = f"skiddle_events_{venue_name}_{latitude}_{longitude}"
        cached = self.cache.get(cache_key, max_age_hours=24)
        if cached is not None:
            return cached

        self.rate_limiter.wait()

        try:
            params = {
                'api_key': self.api_key,
                'keyword': venue_name,
                'limit': 20,
            }
            if latitude and longitude:
                params['latitude'] = latitude
                params['longitude'] = longitude
                params['radius'] = 5

            resp = requests.get(
                f"{self.BASE_URL}/events/search/",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            events = data.get('results', [])
            result = {
                'event_count': len(events),
                'total': data.get('totalcount', 0),
                'events': [
                    {
                        'name': e.get('eventname'),
                        'date': e.get('date'),
                        'venue': e.get('venue', {}).get('name'),
                        'genre': e.get('genres', [{}])[0].get('name', '') if e.get('genres') else '',
                    }
                    for e in events[:10]
                ],
                'genres': list(set(
                    g.get('name', '')
                    for e in events
                    for g in e.get('genres', [])
                    if g.get('name')
                )),
            }

            self.cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"Skiddle search failed for '{venue_name}': {e}")
            return None


class EventEnrichmentAgent(BaseAgent):
    """
    Layer 2 Sub-Agent: Event Enrichment
    Enriches venues with event activity signals (cadence, genres, popularity).
    Uses 7 sources: Songkick, Setlist.fm, Eventbrite, Bandsintown,
    PredictHQ, Skiddle, and Resident Advisor.
    """

    def __init__(self):
        super().__init__('event_enrichment')
        self.songkick = SongkickConnector(RateLimiter(2, 10000), self.cache)
        self.setlistfm = SetlistFmConnector(RateLimiter(2, 5000), self.cache)
        self.eventbrite = EventbriteConnector(RateLimiter(5, 1000), self.cache)
        self.bandsintown = BandsintownEventsConnector(RateLimiter(1, 5000), self.cache)
        self.predicthq = PredictHQEventsConnector(RateLimiter(2, 1000), self.cache)
        self.skiddle = SkiddleConnector(RateLimiter(2, 5000), self.cache)
        self.ra = ResidentAdvisorConnector(RateLimiter(0.5, 500), self.cache)

        self.log_decision(
            "Selected 7 enrichment sources for comprehensive activity signals",
            "Songkick: upcoming event cadence (primary activity signal). "
            "Setlist.fm: historical depth (years of concert data). "
            "Eventbrite: international non-music events. "
            "Bandsintown: artist touring → venue activity validation. "
            "PredictHQ: demand intelligence with rank scores. "
            "Skiddle: UK festivals, club nights, gigs. "
            "RA: electronic music / nightlife coverage. "
            "Combined: event_cadence_score = f(upcoming, historical, demand_rank, genre_diversity)."
        )

    def configure(self, songkick_key=None, setlistfm_key=None,
                  eventbrite_token=None, bandsintown_app_id=None,
                  predicthq_token=None, skiddle_key=None):
        """Configure API keys for enrichment sources."""
        if songkick_key:
            self.songkick.configure(songkick_key)
        if setlistfm_key:
            self.setlistfm.configure(setlistfm_key)
        if eventbrite_token:
            self.eventbrite.configure(eventbrite_token)
        if bandsintown_app_id:
            self.bandsintown.configure(bandsintown_app_id)
        if predicthq_token:
            self.predicthq.configure(predicthq_token)
        if skiddle_key:
            self.skiddle.configure(skiddle_key)

    def enrich_venue(self, venue_name, city=None, lat=None, lng=None, country=None):
        """
        Enrich a single venue with event activity signals from all sources.
        Returns dict with enrichment data.
        """
        enrichment = {
            'upcoming_events_count': 0,
            'historical_events_count': 0,
            'event_cadence_score': 0.0,
            'demand_rank': 0,
            'genres_detected': [],
            'recent_artists': [],
            'activity_level': 'Unknown',
        }

        # 1. Songkick: upcoming events
        sk_venues = self.songkick.search_venue(venue_name)
        if sk_venues:
            for sv in sk_venues:
                if venue_name.lower() in sv.get('sk_name', '').lower() or \
                   sv.get('sk_name', '').lower() in venue_name.lower():
                    events = self.songkick.get_venue_events(sv['sk_id'])
                    if events:
                        enrichment['upcoming_events_count'] += events.get('total', 0)
                        self.stats['api_calls'] += 1
                    break
            self.stats['api_calls'] += 1

        # 2. Setlist.fm: historical events
        sfm_venues = self.setlistfm.search_venue(venue_name, city)
        if sfm_venues:
            for sv in sfm_venues:
                if venue_name.lower() in sv.get('sfm_name', '').lower():
                    setlists = self.setlistfm.get_venue_setlists(sv['sfm_id'])
                    if setlists:
                        enrichment['historical_events_count'] = setlists.get('total_historical_events', 0)
                        enrichment['recent_artists'] = [
                            s['artist'] for s in setlists.get('recent_events', [])
                            if s.get('artist')
                        ]
                        self.stats['api_calls'] += 1
                    break
            self.stats['api_calls'] += 1

        # 3. PredictHQ: demand intelligence (if coordinates available)
        if lat and lng and self.predicthq.token:
            phq_result = self.predicthq.get_events_near_venue(lat, lng)
            if phq_result:
                enrichment['upcoming_events_count'] += phq_result.get('event_count', 0)
                ranks = [e.get('local_rank', 0) for e in phq_result.get('events', []) if e.get('local_rank')]
                if ranks:
                    enrichment['demand_rank'] = sum(ranks) / len(ranks)
                self.stats['api_calls'] += 1

        # 4. Skiddle: UK event data
        if country in ('United Kingdom', 'UK', 'Ireland') and self.skiddle.api_key:
            sk_result = self.skiddle.get_venue_events(venue_name, lat, lng)
            if sk_result:
                enrichment['upcoming_events_count'] += sk_result.get('total', 0)
                enrichment['genres_detected'].extend(sk_result.get('genres', []))
                self.stats['api_calls'] += 1

        # Compute activity score
        upcoming = enrichment['upcoming_events_count']
        historical = enrichment['historical_events_count']
        demand = enrichment['demand_rank']

        upcoming_score = min(upcoming / 50.0, 1.0)
        historical_score = min(historical / 500.0, 1.0)
        demand_score = min(demand / 80.0, 1.0)

        if demand_score > 0:
            enrichment['event_cadence_score'] = round(
                0.45 * upcoming_score + 0.30 * historical_score + 0.25 * demand_score, 3
            )
        else:
            enrichment['event_cadence_score'] = round(
                0.60 * upcoming_score + 0.40 * historical_score, 3
            )

        # Activity level
        score = enrichment['event_cadence_score']
        if score >= 0.7:
            enrichment['activity_level'] = 'High'
        elif score >= 0.3:
            enrichment['activity_level'] = 'Moderate'
        elif score > 0:
            enrichment['activity_level'] = 'Low'

        return enrichment

    def fetch_ra_venues(self, cities=None):
        """Fetch club/venue data from Resident Advisor for key cities."""
        if cities is None:
            cities = ['london', 'berlin', 'amsterdam', 'paris', 'barcelona',
                      'tokyo', 'bangkok', 'singapore', 'jakarta', 'dubai',
                      'melbourne', 'seoul', 'mumbai', 'sao-paulo', 'buenos-aires',
                      'istanbul', 'cape-town', 'cairo']

        all_venues = []
        for city in cities:
            venues = self.ra.get_clubs_by_city(city)
            all_venues.extend(venues)
            self.stats['api_calls'] += 1
            self.stats['records_fetched'] += len(venues)

        if not all_venues:
            return pd.DataFrame(columns=self.UNIFIED_SCHEMA)

        df = pd.DataFrame(all_venues)
        df['data_sources'] = 'resident_advisor'
        return self.to_unified_schema(df)

    def fetch(self, params=None):
        """
        Fetch enrichment data for venues.
        params: dict with:
          - venues_df: DataFrame with venue_name, city, country, latitude, longitude
          - max_venues: int
          - include_ra: bool (scrape Resident Advisor)
        """
        params = params or {}
        venues_df = params.get('venues_df', pd.DataFrame())
        max_venues = params.get('max_venues', 50)
        include_ra = params.get('include_ra', False)

        results = []

        for idx, row in venues_df.head(max_venues).iterrows():
            venue_name = row.get('venue_name', '')
            city = row.get('city')
            country = row.get('country')
            lat = row.get('latitude')
            lng = row.get('longitude')
            if not venue_name:
                continue

            enrichment = self.enrich_venue(venue_name, city, lat, lng, country)
            results.append({
                'venue_name': venue_name,
                'city': city,
                'country': country,
                'upcoming_events': json.dumps({
                    'count': enrichment['upcoming_events_count']
                }),
                'past_events': json.dumps({
                    'count': enrichment['historical_events_count'],
                    'artists': enrichment['recent_artists'][:5],
                }),
                'notes': json.dumps({
                    'cadence_score': enrichment['event_cadence_score'],
                    'activity_level': enrichment['activity_level'],
                    'demand_rank': enrichment['demand_rank'],
                    'genres': enrichment['genres_detected'],
                }),
                'data_sources': 'event_enrichment',
            })
            self.stats['records_fetched'] += 1

        dfs = []
        if results:
            dfs.append(pd.DataFrame(results))

        if include_ra:
            ra_df = self.fetch_ra_venues()
            if not ra_df.empty:
                dfs.append(ra_df)

        if not dfs:
            return pd.DataFrame(columns=self.UNIFIED_SCHEMA)

        combined = pd.concat(dfs, ignore_index=True)
        return self.to_unified_schema(combined)

    def get_source_description(self):
        return {
            'agent': self.name,
            'sources': [
                {
                    'name': 'Songkick API',
                    'url': 'https://www.songkick.com/developer',
                    'type': 'API (free key)',
                    'signal': 'Upcoming event cadence + venue capacity',
                    'coverage': 'Global — 6M+ concerts',
                },
                {
                    'name': 'Setlist.fm API',
                    'url': 'https://api.setlist.fm/',
                    'type': 'API (free key, non-commercial)',
                    'signal': 'Historical event frequency for activity scoring',
                    'coverage': 'Global',
                },
                {
                    'name': 'Eventbrite API',
                    'url': 'https://www.eventbriteapi.com/v3/',
                    'type': 'API (OAuth token)',
                    'signal': 'International event venue data with capacity',
                    'coverage': 'Global — 180+ countries',
                },
                {
                    'name': 'Bandsintown Events API',
                    'url': 'https://artists.bandsintown.com/',
                    'type': 'API (free app_id)',
                    'signal': 'Artist touring events at venue — activity validation',
                    'coverage': 'Global — artist-centric',
                },
                {
                    'name': 'PredictHQ Events API',
                    'url': 'https://docs.predicthq.com/',
                    'type': 'API (requires token)',
                    'signal': 'Demand intelligence, event count + rank scores',
                    'coverage': 'Global — demand-focused',
                },
                {
                    'name': 'Skiddle API',
                    'url': 'https://www.skiddle.com/api/',
                    'type': 'API (free key)',
                    'signal': 'UK events — festivals, club nights, gigs',
                    'coverage': 'UK / Ireland',
                },
                {
                    'name': 'Resident Advisor',
                    'url': 'https://ra.co',
                    'type': 'GraphQL scraping',
                    'signal': 'Electronic music venue data for nightlife segment',
                    'coverage': 'Global electronic music — 18+ cities',
                },
            ],
        }

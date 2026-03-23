"""
Base Agent class for the Tixr multi-layer agent architecture.
All sub-agents inherit from this class.
"""

import os
import json
import time
import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger('tixr_agents')


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, calls_per_second=1, calls_per_day=5000):
        self.calls_per_second = calls_per_second
        self.calls_per_day = calls_per_day
        self.last_call_time = 0
        self.daily_count = 0
        self.daily_reset = datetime.now()

    def wait(self):
        """Wait if necessary to respect rate limits."""
        # Reset daily counter
        if datetime.now() - self.daily_reset > timedelta(days=1):
            self.daily_count = 0
            self.daily_reset = datetime.now()

        if self.daily_count >= self.calls_per_day:
            raise Exception(f"Daily rate limit reached ({self.calls_per_day} calls)")

        elapsed = time.time() - self.last_call_time
        wait_time = (1.0 / self.calls_per_second) - elapsed
        if wait_time > 0:
            time.sleep(wait_time)

        self.last_call_time = time.time()
        self.daily_count += 1


class DiskCache:
    """Simple disk-based cache for API responses."""

    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key):
        hashed = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hashed}.json"

    def get(self, key, max_age_hours=24):
        path = self._key_to_path(key)
        if path.exists():
            data = json.loads(path.read_text())
            cached_time = datetime.fromisoformat(data['cached_at'])
            if datetime.now() - cached_time < timedelta(hours=max_age_hours):
                return data['value']
        return None

    def set(self, key, value):
        path = self._key_to_path(key)
        data = {
            'cached_at': datetime.now().isoformat(),
            'key': key,
            'value': value,
        }
        path.write_text(json.dumps(data, default=str))

    def clear(self):
        for f in self.cache_dir.glob('*.json'):
            f.unlink()


class BaseAgent(ABC):
    """
    Base class for all data-pulling sub-agents.

    Each agent:
    1. Has a name and description
    2. Can pull data from one or more sources
    3. Returns data in the unified venue schema
    4. Supports caching and rate limiting
    5. Logs all operations for the decision log
    """

    UNIFIED_SCHEMA = [
        'venue_id', 'venue_name', 'city', 'country', 'region', 'venue_type',
        'capacity', 'latitude', 'longitude', 'address', 'website',
        'booking_url', 'google_maps_url', 'venue_operator', 'event_types',
        'ticketing_platform', 'exclusivity_strength', 'contract_status',
        'past_events', 'upcoming_events', 'opening_hours', 'phone',
        'notes', 'data_sources', 'wikidata_id', 'osm_id', 'source_urls',
    ]

    def __init__(self, name, cache_dir=None):
        self.name = name
        self.decision_log = []
        self.stats = {'records_fetched': 0, 'api_calls': 0, 'errors': 0}
        self.rate_limiter = RateLimiter()

        if cache_dir is None:
            cache_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), '..', 'cache', name
            )
        self.cache = DiskCache(cache_dir)

    def log_decision(self, decision, reasoning):
        """Log a decision for the Tixr decision log requirement."""
        entry = {
            'agent': self.name,
            'timestamp': datetime.now().isoformat(),
            'decision': decision,
            'reasoning': reasoning,
        }
        self.decision_log.append(entry)
        logger.info(f"[{self.name}] {decision}: {reasoning}")

    def to_unified_schema(self, df):
        """Ensure dataframe matches the unified schema."""
        for col in self.UNIFIED_SCHEMA:
            if col not in df.columns:
                df[col] = None
        return df[self.UNIFIED_SCHEMA]

    @abstractmethod
    def fetch(self, params=None):
        """
        Fetch data from the agent's sources.
        Returns: pd.DataFrame in unified schema format.
        """
        pass

    @abstractmethod
    def get_source_description(self):
        """Return a description of this agent's data sources for the decision log."""
        pass

    def get_stats(self):
        """Return agent statistics."""
        return {
            'agent': self.name,
            'stats': self.stats,
            'decisions': len(self.decision_log),
        }

"""
Tixr Global Venue Intelligence - Data Normalization Pipeline
=============================================================
Merges all venue data sources into a single normalized Excel sheet with
a unified schema aligned to Tixr's case competition requirements:
  - Venue discovery (name, location, type, capacity, website)
  - Enrichment signals (events cadence, ticketing vendor, operator)
  - Exclusivity scoring inputs
  - Market intelligence overlay
"""

import pandas as pd
import numpy as np
import os
import json
import re
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

DATA_DIR = os.path.dirname(os.path.abspath(__file__)) + '/..'
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')

# ─── Unified Schema ───────────────────────────────────────────────────────────
UNIFIED_COLUMNS = [
    'venue_id',               # Unique identifier (wikidata_id or generated)
    'venue_name',             # Canonical name
    'city',                   # City
    'country',                # Country
    'region',                 # APAC, EMEA, LATAM, SEA, EMEA_Gulf, EMEA_Africa
    'venue_type',             # stadium, arena, theatre, nightclub, events_venue, etc.
    'capacity',               # Integer capacity (best available)
    'capacity_tier',          # Mega (40K+), Major (15-40K), Mid (5-15K), Small (1-5K), Boutique (<1K), Unknown
    'latitude',               # Decimal latitude
    'longitude',              # Decimal longitude
    'address',                # Full address string
    'website',                # Official website URL
    'booking_url',            # Ticket purchase URL
    'google_maps_url',        # Google Maps link
    'venue_operator',         # Operator / owner
    'event_types',            # concerts, sports, esports, comedy, etc.
    'ticketing_platform',     # Known ticketing vendor (Ticketmaster, AXS, etc.)
    'exclusivity_strength',   # Strong, Medium, Weak, None, Unknown
    'contract_status',        # Active, Expired, Unknown
    'past_events',            # Past events data (if available)
    'upcoming_events',        # Upcoming events data (if available)
    'opening_hours',          # Opening hours
    'phone',                  # Phone number
    'notes',                  # Additional notes
    'data_sources',           # Which datasets contributed to this record
    'wikidata_id',            # Wikidata Q-identifier
    'osm_id',                 # OpenStreetMap ID
    'source_urls',            # Reference URLs / sources
    # Market intelligence (joined from World Bank data)
    'gdp_per_capita_usd',
    'internet_users_pct',
    'mobile_subscriptions_per_100',
    'tourism_arrivals',
]


def normalize_capacity(val):
    """Extract numeric capacity from various formats."""
    if pd.isna(val):
        return np.nan
    val = str(val).replace(',', '').replace('"', '').strip()
    match = re.search(r'(\d+(?:\.\d+)?)', val)
    if match:
        return int(float(match.group(1)))
    return np.nan


def capacity_tier(cap):
    """Assign a capacity tier label."""
    if pd.isna(cap) or cap == 0:
        return 'Unknown'
    if cap >= 40000:
        return 'Mega (40K+)'
    if cap >= 15000:
        return 'Major (15-40K)'
    if cap >= 5000:
        return 'Mid (5-15K)'
    if cap >= 1000:
        return 'Small (1-5K)'
    return 'Boutique (<1K)'


def normalize_venue_type(raw_type):
    """Normalize venue type strings to canonical categories."""
    if pd.isna(raw_type):
        return 'venue'
    t = str(raw_type).lower().strip()
    mapping = {
        'stadium': 'stadium',
        'arena': 'arena',
        'theatre': 'theatre',
        'theater': 'theatre',
        'theatre building': 'theatre',
        'movie theater': 'cinema',
        'nightclub': 'nightclub',
        'events_venue': 'events_venue',
        'music_venue': 'music_venue',
        'concert hall': 'concert_hall',
        'amphitheatre': 'amphitheatre',
        'venue': 'venue',
        'website': 'website',  # Filter these out
    }
    for key, canonical in mapping.items():
        if key in t:
            return canonical
    return 'venue'


def load_wikidata_venues():
    """Load and normalize Wikidata venues (file 1)."""
    print("[1/9] Loading Wikidata venues...")
    fp = os.path.join(DATA_DIR, '1_wikidata_venues_target_regions.csv')
    df = pd.read_csv(fp)

    # Filter out 'website' type entries - not actual venues
    df = df[df['type'].fillna('').str.lower() != 'website'].copy()

    normalized = pd.DataFrame()
    normalized['wikidata_id'] = df['wikidata_id']
    normalized['venue_name'] = df['name']
    normalized['country'] = df['country']
    normalized['venue_type'] = df['type'].apply(normalize_venue_type)
    normalized['capacity'] = df['capacity'].apply(normalize_capacity)
    normalized['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    normalized['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    normalized['region'] = df['region']
    normalized['website'] = df['website']
    normalized['data_sources'] = 'wikidata'

    print(f"  -> {len(normalized)} venue records (filtered from {len(df)} after removing 'website' type)")
    return normalized


def load_osm_venues():
    """Load and normalize OSM city venues (file 2)."""
    print("[2/9] Loading OSM city venues...")
    fp = os.path.join(DATA_DIR, '2_osm_city_venues.csv')
    df = pd.read_csv(fp)

    normalized = pd.DataFrame()
    normalized['venue_name'] = df['name']
    normalized['city'] = df['city']
    normalized['venue_type'] = df['type'].apply(normalize_venue_type)
    normalized['capacity'] = df['capacity'].apply(normalize_capacity)
    normalized['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    normalized['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    normalized['website'] = df['website']
    normalized['address'] = df['addr_street'].fillna('') + ', ' + df['addr_city'].fillna('')
    normalized['address'] = normalized['address'].str.strip(', ')
    normalized['venue_operator'] = df['operator']
    normalized['phone'] = df['phone']
    normalized['opening_hours'] = df['opening_hours']
    normalized['osm_id'] = df['osm_id'].astype(str)
    normalized['region'] = df['region']
    normalized['data_sources'] = 'osm'

    # Remove rows where name is 'Unknown' or empty
    normalized = normalized[~normalized['venue_name'].isin(['Unknown', '']) & normalized['venue_name'].notna()].copy()
    print(f"  -> {len(normalized)} venue records")
    return normalized


def load_wikipedia_stadiums():
    """Load and normalize Wikipedia stadiums (file 3)."""
    print("[3/9] Loading Wikipedia stadiums...")
    fp = os.path.join(DATA_DIR, '3_wikipedia_stadiums_arenas.csv')
    df = pd.read_csv(fp)

    normalized = pd.DataFrame()
    normalized['venue_name'] = df['col1']
    normalized['capacity'] = df['col2'].apply(normalize_capacity)
    normalized['city'] = df['col3']
    normalized['country'] = df['col4']
    normalized['venue_type'] = df['venue_type'].apply(normalize_venue_type)
    normalized['event_types'] = df['col7']  # Sport type
    normalized['notes'] = df['col6']  # Teams
    normalized['data_sources'] = 'wikipedia'

    # Map continents to Tixr regions
    region_map = {
        'Europe': 'EMEA', 'Africa': 'EMEA_Africa', 'South America': 'LATAM',
        'North America': 'LATAM', 'Southeast Asia': 'SEA', 'East Asia': 'APAC',
        'Asia': 'APAC', 'Oceania': 'APAC', 'Middle East': 'EMEA_Gulf',
    }
    normalized['region'] = df['col5'].map(region_map).fillna('EMEA')

    print(f"  -> {len(normalized)} stadium records")
    return normalized


def load_premium_venues():
    """Load premium venues with capacity (file 4). Skipped as subset of file 7."""
    print("[4/9] Loading premium venues (capacity-filtered)...")
    fp = os.path.join(DATA_DIR, '4_premium_venues_with_capacity.csv')
    df = pd.read_csv(fp)

    normalized = pd.DataFrame()
    normalized['wikidata_id'] = df['wikidata_id']
    normalized['venue_name'] = df['name']
    normalized['country'] = df['country']
    normalized['venue_type'] = df['type'].apply(normalize_venue_type)
    normalized['capacity'] = df['capacity_num'].apply(normalize_capacity)
    normalized['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    normalized['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    normalized['region'] = df['region']
    normalized['website'] = df['website']
    normalized['data_sources'] = 'wikidata_premium'

    print(f"  -> {len(normalized)} premium venue records")
    return normalized


def load_country_detailed_venues():
    """Load all country-specific detailed venue files (venues_*_b.csv)."""
    print("[5/9] Loading country-specific detailed venues...")
    country_files = [f for f in os.listdir(DATA_DIR) if f.startswith('venues_') and f.endswith('_b.csv')]

    all_dfs = []
    for cf in sorted(country_files):
        fp = os.path.join(DATA_DIR, cf)
        df = pd.read_csv(fp)
        country_name = cf.replace('venues_', '').replace('_b.csv', '').replace('_', ' ').title()
        print(f"  Loading {cf} ({len(df)} rows)")

        normalized = pd.DataFrame()
        normalized['venue_name'] = df['venue_name']
        normalized['city'] = df['city']
        normalized['country'] = df['country']
        normalized['venue_type'] = df['venue_type'].apply(normalize_venue_type)
        normalized['capacity'] = df['capacity_max'].apply(normalize_capacity)
        normalized['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        normalized['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
        normalized['address'] = df['address']
        normalized['google_maps_url'] = df['google_maps_url']
        normalized['booking_url'] = df['booking_url']
        normalized['venue_operator'] = df['venue_operator']
        normalized['event_types'] = df['event_types']
        normalized['past_events'] = df['past_events']
        normalized['upcoming_events'] = df['upcoming_events']
        normalized['notes'] = df['notes']
        normalized['source_urls'] = df['sources']
        normalized['data_sources'] = f'detailed_{country_name.lower().replace(" ", "_")}'

        all_dfs.append(normalized)

    result = pd.concat(all_dfs, ignore_index=True)
    print(f"  -> {len(result)} total detailed venue records")
    return result


def load_sea_venues():
    """Load SEA Venues from XLSX (file SEA_Venues.xlsx)."""
    print("[6/9] Loading SEA venues (XLSX)...")
    fp = os.path.join(DATA_DIR, 'SEA_Venues.xlsx')
    df = pd.read_excel(fp)

    normalized = pd.DataFrame()
    normalized['venue_name'] = df['Venue Name']
    normalized['country'] = df['Country']
    normalized['city'] = df['City']
    normalized['venue_type'] = df['Type'].apply(normalize_venue_type)
    normalized['capacity'] = df['Capacity'].apply(normalize_capacity)
    normalized['venue_operator'] = df['Operator / Owner']
    normalized['ticketing_platform'] = df['Primary Ticketing Vendor(s)']
    normalized['address'] = df['Address']
    normalized['website'] = df['Website']
    normalized['notes'] = df['Notable Acts / Notes']
    normalized['region'] = 'SEA'
    normalized['data_sources'] = 'sea_venues_xlsx'

    print(f"  -> {len(normalized)} SEA venue records")
    return normalized


def load_exclusivity_groundtruth():
    """Load venue exclusivity ground truth (V2)."""
    print("[7/9] Loading exclusivity ground truth...")
    fp = os.path.join(DATA_DIR, 'V2_venue_exclusivity_groundtruth.csv')
    df = pd.read_csv(fp)

    normalized = pd.DataFrame()
    normalized['venue_name'] = df['venue']
    normalized['city'] = df['city']
    normalized['country'] = df['country']
    normalized['capacity'] = df['capacity'].apply(normalize_capacity)
    normalized['event_types'] = df['sport']
    normalized['ticketing_platform'] = df['ticketing_platform']
    normalized['exclusivity_strength'] = df['exclusivity_strength']
    normalized['contract_status'] = df['contract_status']
    normalized['source_urls'] = df['source']
    normalized['data_sources'] = 'exclusivity_groundtruth'

    print(f"  -> {len(normalized)} exclusivity records")
    return normalized


def load_tixr_premium_targets():
    """Load Tixr premium target venues (file 7)."""
    print("[8/9] Loading Tixr premium target venues...")
    fp = os.path.join(DATA_DIR, '7_tixr_premium_target_venues.csv')
    df = pd.read_csv(fp)

    normalized = pd.DataFrame()
    normalized['wikidata_id'] = df['wikidata_id']
    normalized['venue_name'] = df['name']
    normalized['country'] = df['country']
    normalized['venue_type'] = df['type'].apply(normalize_venue_type)
    normalized['capacity'] = df['capacity_num'].apply(normalize_capacity)
    normalized['capacity_tier'] = df['size_category']
    normalized['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    normalized['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    normalized['region'] = df['region']
    normalized['website'] = df['website']
    normalized['data_sources'] = 'tixr_premium_targets'

    print(f"  -> {len(normalized)} Tixr premium targets")
    return normalized


def assign_regions(df):
    """Fill missing regions based on country."""
    country_region = {
        'Australia': 'APAC', 'Japan': 'APAC', 'South Korea': 'APAC',
        'New Zealand': 'APAC', 'India': 'APAC', 'China': 'APAC',
        "People's Republic of China": 'APAC',
        'United Kingdom': 'EMEA', 'Germany': 'EMEA', 'France': 'EMEA',
        'Spain': 'EMEA', 'Italy': 'EMEA', 'Netherlands': 'EMEA',
        'Belgium': 'EMEA', 'Sweden': 'EMEA', 'Norway': 'EMEA',
        'Denmark': 'EMEA', 'Finland': 'EMEA', 'Austria': 'EMEA',
        'Switzerland': 'EMEA', 'Poland': 'EMEA', 'Czech Republic': 'EMEA',
        'Portugal': 'EMEA', 'Ireland': 'EMEA', 'Greece': 'EMEA',
        'Turkey': 'EMEA', 'Russia': 'EMEA', 'Hungary': 'EMEA',
        'United Arab Emirates': 'EMEA_Gulf', 'Saudi Arabia': 'EMEA_Gulf',
        'Qatar': 'EMEA_Gulf', 'Bahrain': 'EMEA_Gulf', 'Kuwait': 'EMEA_Gulf',
        'Oman': 'EMEA_Gulf', 'Israel': 'EMEA_Gulf',
        'Egypt': 'EMEA_Africa', 'South Africa': 'EMEA_Africa',
        'Nigeria': 'EMEA_Africa', 'Kenya': 'EMEA_Africa', 'Morocco': 'EMEA_Africa',
        'Brazil': 'LATAM', 'Mexico': 'LATAM', 'Argentina': 'LATAM',
        'Colombia': 'LATAM', 'Chile': 'LATAM', 'Peru': 'LATAM',
        'Venezuela': 'LATAM', 'Ecuador': 'LATAM', 'Uruguay': 'LATAM',
        'Costa Rica': 'LATAM', 'Panama': 'LATAM', 'Guatemala': 'LATAM',
        'Dominican Republic': 'LATAM', 'Puerto Rico': 'LATAM',
        'Thailand': 'SEA', 'Indonesia': 'SEA', 'Singapore': 'SEA',
        'Malaysia': 'SEA', 'Philippines': 'SEA', 'Vietnam': 'SEA',
        'Cambodia': 'SEA', 'Myanmar': 'SEA',
        'United States': 'Americas',
    }
    df['region'] = df.apply(
        lambda row: row['region'] if pd.notna(row.get('region')) else country_region.get(row.get('country', ''), ''),
        axis=1
    )
    return df


def deduplicate_venues(df):
    """Deduplicate venues by merging records from different sources."""
    print("\n[DEDUP] Deduplicating venues...")
    initial = len(df)

    # Step 1: Merge on wikidata_id (exact match)
    has_wikidata = df[df['wikidata_id'].notna()].copy()
    no_wikidata = df[df['wikidata_id'].isna()].copy()

    if len(has_wikidata) > 0:
        # Group by wikidata_id and merge
        def merge_group(group):
            row = group.iloc[0].copy()
            sources = group['data_sources'].dropna().unique()
            row['data_sources'] = '|'.join(sources)

            # Take best available for each field
            for col in ['city', 'address', 'website', 'booking_url', 'venue_operator',
                        'ticketing_platform', 'exclusivity_strength', 'event_types',
                        'phone', 'opening_hours', 'google_maps_url', 'source_urls',
                        'past_events', 'upcoming_events', 'contract_status', 'notes']:
                vals = group[col].dropna().unique() if col in group.columns else []
                if len(vals) > 0:
                    row[col] = vals[0]

            # Take max capacity
            caps = group['capacity'].dropna()
            if len(caps) > 0:
                row['capacity'] = caps.max()

            # Prefer non-NaN lat/lng
            for coord in ['latitude', 'longitude']:
                vals = group[coord].dropna()
                if len(vals) > 0:
                    row[coord] = vals.iloc[0]

            return row

        merged_wikidata = has_wikidata.groupby('wikidata_id').apply(merge_group).reset_index(drop=True)
        df = pd.concat([merged_wikidata, no_wikidata], ignore_index=True)

    # Step 2: Fuzzy dedup on name + country (for venues without wikidata_id)
    # Normalize names for matching
    df['_name_key'] = df['venue_name'].fillna('').str.lower().str.strip()
    df['_country_key'] = df['country'].fillna('').str.lower().str.strip()
    df['_dedup_key'] = df['_name_key'] + '||' + df['_country_key']

    # For duplicates, keep the one with most data (most non-null fields)
    df['_data_richness'] = df.notna().sum(axis=1)
    df = df.sort_values('_data_richness', ascending=False)
    df = df.drop_duplicates(subset='_dedup_key', keep='first')
    df = df.drop(columns=['_name_key', '_country_key', '_dedup_key', '_data_richness'])

    print(f"  -> Reduced from {initial} to {len(df)} records")
    return df


def enrich_with_market_data(df):
    """Join World Bank market intelligence data to venues by country."""
    print("\n[ENRICH] Adding market intelligence overlay...")
    wb_fp = os.path.join(DATA_DIR, '5_world_bank_market_intelligence.csv')
    wb = pd.read_csv(wb_fp)

    market_cols = ['gdp_per_capita_usd', 'internet_users_pct',
                   'mobile_subscriptions_per_100', 'tourism_arrivals']

    wb_lookup = wb.set_index('country')[market_cols].to_dict('index')

    for col in market_cols:
        df[col] = df['country'].map(lambda c: wb_lookup.get(c, {}).get(col, np.nan))

    enriched = df[df['gdp_per_capita_usd'].notna()]
    print(f"  -> {len(enriched)} venues enriched with market data (of {len(df)} total)")
    return df


def enrich_with_exclusivity(df):
    """Overlay known exclusivity data from V2 ground truth."""
    print("[ENRICH] Overlaying exclusivity ground truth...")
    excl_fp = os.path.join(DATA_DIR, 'V2_venue_exclusivity_groundtruth.csv')
    excl = pd.read_csv(excl_fp)

    # Create lookup by normalized venue name
    excl_lookup = {}
    for _, row in excl.iterrows():
        key = str(row['venue']).lower().strip()
        excl_lookup[key] = {
            'ticketing_platform': row.get('ticketing_platform', ''),
            'exclusivity_strength': row.get('exclusivity_strength', ''),
            'contract_status': row.get('contract_status', ''),
        }

    matched = 0
    for idx, row in df.iterrows():
        name_key = str(row['venue_name']).lower().strip()
        # Try exact match and partial match
        match = excl_lookup.get(name_key)
        if not match:
            for ek, ev in excl_lookup.items():
                if ek in name_key or name_key in ek:
                    match = ev
                    break

        if match:
            if pd.isna(df.at[idx, 'ticketing_platform']) or df.at[idx, 'ticketing_platform'] == '':
                df.at[idx, 'ticketing_platform'] = match['ticketing_platform']
            if pd.isna(df.at[idx, 'exclusivity_strength']) or df.at[idx, 'exclusivity_strength'] == '':
                df.at[idx, 'exclusivity_strength'] = match['exclusivity_strength']
            if pd.isna(df.at[idx, 'contract_status']) or df.at[idx, 'contract_status'] == '':
                df.at[idx, 'contract_status'] = match['contract_status']
            matched += 1

    print(f"  -> {matched} venues matched with exclusivity data")
    return df


def generate_venue_ids(df):
    """Generate unique venue IDs for all records."""
    def make_id(row):
        if pd.notna(row.get('wikidata_id')):
            return str(row['wikidata_id'])
        if pd.notna(row.get('osm_id')):
            return f"OSM_{row['osm_id']}"
        # Generate from name + country
        name = str(row.get('venue_name', 'unknown')).lower().replace(' ', '_')[:30]
        country = str(row.get('country', 'xx')).lower().replace(' ', '_')[:10]
        return f"GEN_{name}_{country}"

    df['venue_id'] = df.apply(make_id, axis=1)
    # Handle duplicates in generated IDs
    dup_mask = df['venue_id'].duplicated(keep=False)
    if dup_mask.any():
        counts = {}
        for idx in df[dup_mask].index:
            vid = df.at[idx, 'venue_id']
            counts[vid] = counts.get(vid, 0) + 1
            if counts[vid] > 1:
                df.at[idx, 'venue_id'] = f"{vid}_{counts[vid]}"

    return df


def compute_capacity_tiers(df):
    """Compute capacity tier for all records."""
    df['capacity_tier'] = df['capacity'].apply(capacity_tier)
    return df


def final_cleanup(df):
    """Final cleanup and column ordering."""
    # Ensure all unified columns exist
    for col in UNIFIED_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    # Order columns
    df = df[UNIFIED_COLUMNS].copy()

    # Filter out records with no name
    df = df[df['venue_name'].notna() & (df['venue_name'] != '')].copy()

    # Clean up string fields
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].fillna('').astype(str).str.strip()
        df[col] = df[col].replace('', np.nan).replace('nan', np.nan)

    return df


def main():
    print("=" * 70)
    print("TIXR VENUE INTELLIGENCE - DATA NORMALIZATION PIPELINE")
    print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Load all sources
    dfs = []
    dfs.append(load_wikidata_venues())
    dfs.append(load_osm_venues())
    dfs.append(load_wikipedia_stadiums())
    dfs.append(load_premium_venues())
    dfs.append(load_country_detailed_venues())
    dfs.append(load_sea_venues())
    dfs.append(load_exclusivity_groundtruth())
    dfs.append(load_tixr_premium_targets())

    # Concatenate all
    print("\n[MERGE] Concatenating all sources...")
    combined = pd.concat(dfs, ignore_index=True)
    print(f"  -> {len(combined)} total raw records")

    # Assign regions
    combined = assign_regions(combined)

    # Deduplicate
    combined = deduplicate_venues(combined)

    # Generate IDs
    combined = generate_venue_ids(combined)

    # Compute capacity tiers
    combined = compute_capacity_tiers(combined)

    # Enrich with market data
    combined = enrich_with_market_data(combined)

    # Enrich with exclusivity
    combined = enrich_with_exclusivity(combined)

    # Final cleanup
    print("\n[FINAL] Cleaning up and ordering columns...")
    result = final_cleanup(combined)

    # Stats
    print("\n" + "=" * 70)
    print("FINAL DATASET STATISTICS")
    print("=" * 70)
    print(f"Total venues: {len(result)}")
    print(f"\nBy region:")
    print(result['region'].value_counts().to_string())
    print(f"\nBy venue type:")
    print(result['venue_type'].value_counts().head(10).to_string())
    print(f"\nBy capacity tier:")
    print(result['capacity_tier'].value_counts().to_string())
    print(f"\nData completeness:")
    for col in ['venue_name', 'country', 'city', 'capacity', 'latitude',
                'longitude', 'website', 'ticketing_platform', 'venue_type']:
        pct = result[col].notna().mean() * 100
        print(f"  {col}: {pct:.1f}%")

    # Save to Excel
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, 'tixr_normalized_venues.xlsx')

    print(f"\n[SAVE] Writing to {output_path}...")

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        # Main venues sheet
        result.to_excel(writer, sheet_name='All_Venues', index=False)

        # Summary by region
        region_summary = result.groupby('region').agg(
            total_venues=('venue_id', 'count'),
            with_capacity=('capacity', lambda x: x.notna().sum()),
            with_website=('website', lambda x: x.notna().sum()),
            with_coordinates=('latitude', lambda x: x.notna().sum()),
            avg_capacity=('capacity', 'mean'),
            with_ticketing_platform=('ticketing_platform', lambda x: x.notna().sum()),
        ).reset_index()
        region_summary.to_excel(writer, sheet_name='Region_Summary', index=False)

        # Country breakdown
        country_summary = result.groupby(['region', 'country']).agg(
            total_venues=('venue_id', 'count'),
            with_capacity=('capacity', lambda x: x.notna().sum()),
            avg_capacity=('capacity', 'mean'),
            with_website=('website', lambda x: x.notna().sum()),
        ).reset_index()
        country_summary.to_excel(writer, sheet_name='Country_Summary', index=False)

        # Venue type breakdown
        type_summary = result.groupby('venue_type').agg(
            count=('venue_id', 'count'),
            avg_capacity=('capacity', 'mean'),
        ).reset_index().sort_values('count', ascending=False)
        type_summary.to_excel(writer, sheet_name='Type_Summary', index=False)

        # Exclusivity data
        excl_data = result[result['ticketing_platform'].notna()][
            ['venue_name', 'city', 'country', 'capacity', 'venue_type',
             'ticketing_platform', 'exclusivity_strength', 'contract_status']
        ]
        excl_data.to_excel(writer, sheet_name='Exclusivity_Known', index=False)

        # World Bank market data reference
        wb = pd.read_csv(os.path.join(DATA_DIR, '5_world_bank_market_intelligence.csv'))
        wb.to_excel(writer, sheet_name='Market_Intelligence', index=False)

        # Vendor exclusivity map
        v1 = pd.read_csv(os.path.join(DATA_DIR, 'V1_ticketing_vendor_exclusivity_map.csv'))
        v1.to_excel(writer, sheet_name='Vendor_Landscape', index=False)

        # Detection methods
        v3 = pd.read_csv(os.path.join(DATA_DIR, 'V3_exclusivity_detection_methods.csv'))
        v3.to_excel(writer, sheet_name='Detection_Methods', index=False)

    print(f"\n✅ Normalized data saved to: {output_path}")
    print(f"   Sheets: All_Venues, Region_Summary, Country_Summary, Type_Summary,")
    print(f"           Exclusivity_Known, Market_Intelligence, Vendor_Landscape, Detection_Methods")
    return result


if __name__ == '__main__':
    main()

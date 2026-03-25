#!/usr/bin/env python3
"""
Tixr Dashboard Generator
========================
Reads pipeline output Excel and generates a self-contained HTML dashboard
for the sales team to explore venues, markets, and recommendations.

Usage:
  python generate_dashboard.py
  python generate_dashboard.py --output my.html
"""

import os
import sys
import json
import argparse
from datetime import datetime

import math

import pandas as pd
import numpy as np


def load_data(output_dir='output'):
    """Load pipeline output. Prefer Stage 2 recommendations if available."""
    rec_path = os.path.join(output_dir, 'tixr_recommendations.xlsx')
    norm_path = os.path.join(output_dir, 'tixr_normalized_venues.xlsx')

    path = rec_path if os.path.exists(rec_path) else norm_path
    if not os.path.exists(path):
        print("ERROR: No pipeline output found in " + output_dir)
        print("Run the pipeline first: python run_pipeline.py --recommend")
        sys.exit(1)

    print("Loading data from: " + path)
    df = pd.read_excel(path, sheet_name=0)
    print("  " + str(len(df)) + " venues loaded")

    market_df = None
    try:
        market_df = pd.read_excel(path, sheet_name='Market_Intelligence')
        print("  " + str(len(market_df)) + " market records loaded")
    except Exception:
        pass

    return df, market_df, path


def compute_exclusivity_risk(row):
    vwp = row.get('venue_win_probability')
    if pd.notna(vwp):
        return round((1.0 - float(vwp)) * 100)
    strength = str(row.get('exclusivity_strength', '')).lower()
    if strength == 'strong':
        return 90
    elif strength == 'medium':
        return 55
    elif strength == 'weak':
        return 30
    return 35


def safe_str(val, default=''):
    if pd.isna(val):
        return default
    return str(val)


# ─── Geocode missing coordinates ────────────────────────────────────────────
COUNTRY_ALIASES = {
    'UK': 'United Kingdom', 'USA': 'United States', 'US': 'United States',
    'UAE': 'United Arab Emirates', 'S Korea': 'South Korea',
    'Republic of Korea': 'South Korea', 'Czechia': 'Czech Republic',
    'Russia': 'Russian Federation', 'Taiwan': 'China',
}

# Fallback centroids for countries that may have no known-coord venues
COUNTRY_FALLBACK = {
    'United States': (39.8, -98.6), 'United Kingdom': (54.0, -2.0),
    'Canada': (56.1, -106.3), 'Russian Federation': (55.75, 37.62),
    'Algeria': (28.0, 1.7), 'Libya': (26.3, 17.2), 'Taiwan': (25.0, 121.5),
    'Gabon': (0.4, 11.6), 'Syria': (35.0, 38.0), 'Ghana': (7.9, -1.0),
    'Hungary': (47.5, 19.1), 'Ukraine': (48.4, 31.2), 'Bulgaria': (42.7, 25.5),
    'Tunisia': (34.0, 9.0), 'Cuba': (21.5, -77.8), 'Senegal': (14.5, -14.5),
    'Paraguay': (-23.4, -58.4), 'Zambia': (-15.4, 28.3),
    'Democratic Republic of the Congo': (-4.0, 21.8),
    'Iran': (32.4, 53.7), 'Iraq': (33.2, 43.7), 'Pakistan': (30.4, 69.3),
    'Bangladesh': (23.7, 90.4), 'Sri Lanka': (7.9, 80.8),
    'Myanmar': (19.8, 96.2), 'Nepal': (28.4, 84.1),
}


# City fallback: (lat, lon, country) — country is used to fill missing country field
CITY_FALLBACK = {
    'London': (51.51, -0.13, 'United Kingdom'), 'Paris': (48.86, 2.35, 'France'),
    'Berlin': (52.52, 13.40, 'Germany'), 'SaoPaulo': (-23.55, -46.63, 'Brazil'),
    'MexicoCity': (19.43, -99.13, 'Mexico'), 'Madrid': (40.42, -3.70, 'Spain'),
    'BuenosAires': (-34.60, -58.38, 'Argentina'), 'Amsterdam': (52.37, 4.90, 'Netherlands'),
    'Singapore': (1.35, 103.82, 'Singapore'), 'Bogota': (4.71, -74.07, 'Colombia'),
    'Bangkok': (13.76, 100.50, 'Thailand'), 'Jakarta': (-6.21, 106.85, 'Indonesia'),
    'KualaLumpur': (3.14, 101.69, 'Malaysia'), 'Manila': (14.60, 120.98, 'Philippines'),
    'Dubai': (25.20, 55.27, 'United Arab Emirates'), 'Doha': (25.29, 51.53, 'Qatar'),
    'Riyadh': (24.71, 46.67, 'Saudi Arabia'), 'Mumbai': (19.08, 72.88, 'India'),
    'Tokyo': (35.68, 139.69, 'Japan'), 'Sydney': (-33.87, 151.21, 'Australia'),
    'Melbourne': (-37.81, 144.96, 'Australia'), 'Toronto': (43.65, -79.38, 'Canada'),
    'NewYork': (40.71, -74.01, 'United States'), 'LosAngeles': (34.05, -118.24, 'United States'),
    'Chicago': (41.88, -87.63, 'United States'), 'Miami': (25.76, -80.19, 'United States'),
    'Lisbon': (38.72, -9.14, 'Portugal'), 'Rome': (41.90, 12.50, 'Italy'),
    'Milan': (45.46, 9.19, 'Italy'), 'Vienna': (48.21, 16.37, 'Austria'),
    'Zurich': (47.38, 8.54, 'Switzerland'), 'Stockholm': (59.33, 18.07, 'Sweden'),
    'Copenhagen': (55.68, 12.57, 'Denmark'), 'Oslo': (59.91, 10.75, 'Norway'),
    'Helsinki': (60.17, 24.94, 'Finland'), 'Warsaw': (52.23, 21.01, 'Poland'),
    'Prague': (50.08, 14.44, 'Czech Republic'), 'Budapest': (47.50, 19.04, 'Hungary'),
    'Dublin': (53.35, -6.26, 'Ireland'), 'Brussels': (50.85, 4.35, 'Belgium'),
    'Seoul': (37.57, 126.98, 'South Korea'), 'HoChiMinhCity': (10.82, 106.63, 'Vietnam'),
    'Lima': (-12.05, -77.04, 'Peru'), 'Santiago': (-33.45, -70.67, 'Chile'),
}


def geocode_missing(df):
    """Fill in missing lat/lon using city→centroid, country→centroid, then fallbacks."""
    import random
    random.seed(42)

    # Normalize country names
    df['country'] = df['country'].apply(
        lambda x: COUNTRY_ALIASES.get(str(x).strip(), str(x).strip()) if pd.notna(x) else x
    )

    has = df['latitude'].notna() & df['longitude'].notna()
    n_before = has.sum()

    # Build city-level centroids from venues that have coordinates
    city_centroids = (
        df[has].groupby(['country', 'city'])
        .agg(lat=('latitude', 'mean'), lon=('longitude', 'mean'))
        .to_dict('index')
    )

    # Build country-level centroids
    country_centroids = (
        df[has].groupby('country')
        .agg(lat=('latitude', 'mean'), lon=('longitude', 'mean'))
        .to_dict('index')
    )

    # Pass 1: Fill missing country from city fallback (even if venue has coords)
    country_filled = 0
    for idx in df.index:
        if pd.notna(df.at[idx, 'country']) and str(df.at[idx, 'country']).strip():
            continue
        ci = str(df.at[idx, 'city']).strip() if pd.notna(df.at[idx, 'city']) else None
        if ci and ci in CITY_FALLBACK:
            df.at[idx, 'country'] = CITY_FALLBACK[ci][2]
            country_filled += 1
    print("  Filled country for " + str(country_filled) + " venues via city lookup")

    # Pass 2: Fill missing coordinates
    filled = 0
    for idx in df.index:
        if pd.notna(df.at[idx, 'latitude']) and pd.notna(df.at[idx, 'longitude']):
            continue

        co = df.at[idx, 'country'] if pd.notna(df.at[idx, 'country']) else None
        ci = df.at[idx, 'city'] if pd.notna(df.at[idx, 'city']) else None
        lat = lon = None

        # Try city match
        if co and ci and (co, ci) in city_centroids:
            lat = city_centroids[(co, ci)]['lat']
            lon = city_centroids[(co, ci)]['lon']
        # Try country match
        elif co and co in country_centroids:
            lat = country_centroids[co]['lat']
            lon = country_centroids[co]['lon']
        # Try city fallback
        if lat is None and ci and ci in CITY_FALLBACK:
            lat, lon = CITY_FALLBACK[ci][0], CITY_FALLBACK[ci][1]
        # Try country fallback table
        if lat is None and co and co in COUNTRY_FALLBACK:
            lat, lon = COUNTRY_FALLBACK[co]

        if lat is not None:
            # Add jitter (±0.05 degrees ≈ ±5km) to avoid stacking
            df.at[idx, 'latitude'] = lat + random.uniform(-0.05, 0.05)
            df.at[idx, 'longitude'] = lon + random.uniform(-0.05, 0.05)
            filled += 1

    n_after = df['latitude'].notna().sum()
    still_missing = len(df) - n_after
    print("  Geocoded " + str(filled) + " venues (" + str(n_before) + " → " + str(n_after) + " with coords, " + str(still_missing) + " unresolvable)")
    return df


def prepare_venues(df):
    venues = []
    for _, row in df.iterrows():
        name = safe_str(row.get('venue_name'))
        if not name:
            continue
        name = name[:80]

        lat = row.get('latitude')
        lon = row.get('longitude')
        has_coords = pd.notna(lat) and pd.notna(lon)

        cap = row.get('capacity')
        cap_val = int(float(cap)) if pd.notna(cap) and float(cap) > 0 else 0

        pf = row.get('premium_fit_score', 50)
        pf = int(float(pf)) if pd.notna(pf) else 50

        ps = row.get('priority_score', 0)
        ps = round(float(ps), 1) if pd.notna(ps) else 0

        rs = row.get('recommendation_score')
        rs = round(float(rs), 1) if pd.notna(rs) else ps

        if rs >= 65:
            tier_num = 1
        elif rs >= 61:
            tier_num = 2
        elif rs >= 48:
            tier_num = 3
        else:
            tier_num = 4

        website = 1 if pd.notna(row.get('website')) and str(row.get('website', '')).startswith('http') else 0

        ex = compute_exclusivity_risk(row)
        win_prob = max(0, (100 - ex)) / 100.0
        roi = round(rs * win_prob * (pf / 100.0), 1)

        v = {
            'n': name,
            'c': safe_str(row.get('city')),
            'co': safe_str(row.get('country')),
            'r': safe_str(row.get('region')),
            't': safe_str(row.get('venue_type'), 'Unknown'),
            'cap': cap_val,
            'ex': ex,
            'pf': pf,
            'ps': ps,
            'rs': rs,
            'ti': tier_num,
            'vd': safe_str(row.get('ticketing_platform')),
            'es': safe_str(row.get('exclusivity_strength')),
            'w': website,
            'roi': roi,
        }
        if has_coords:
            v['la'] = round(float(lat), 4)
            v['lo'] = round(float(lon), 4)

        venues.append(v)

    return venues


def prepare_markets(df):
    if 'country' not in df.columns:
        return {}

    markets = {}
    for country, grp in df.groupby('country'):
        if pd.isna(country) or not country:
            continue
        country = str(country)
        n = len(grp)
        if n < 2:
            continue

        avg_ps = grp['priority_score'].mean() if 'priority_score' in grp.columns else 0

        # Compute effective rec score per venue (same fallback as VD)
        def _eff_rs(row):
            v = row.get('recommendation_score')
            return round(float(v), 1) if pd.notna(v) else (
                round(float(row.get('priority_score', 0)), 1) if pd.notna(row.get('priority_score')) else 0
            )
        eff_scores = grp.apply(_eff_rs, axis=1)
        avg_rs = eff_scores.mean()

        t1 = int((eff_scores >= 65).sum())
        t2 = int(((eff_scores >= 61) & (eff_scores < 65)).sum())

        top_plat = ''
        if 'ticketing_platform' in grp.columns:
            plats = grp['ticketing_platform'].dropna()
            plats = plats[plats != '']
            if len(plats) > 0:
                top_plat = str(plats.value_counts().index[0])

        region = ''
        if 'region' in grp.columns:
            regions_col = grp['region'].dropna()
            if len(regions_col) > 0:
                mode = regions_col.mode()
                region = str(mode.iloc[0]) if len(mode) > 0 else ''

        ms = 0
        if 'market_score' in grp.columns:
            ms_vals = grp['market_score'].dropna()
            ms = round(float(ms_vals.mean()), 1) if len(ms_vals) > 0 else 0

        lat_c = grp['latitude'].dropna().mean() if 'latitude' in grp.columns else 0
        lon_c = grp['longitude'].dropna().mean() if 'longitude' in grp.columns else 0

        # Opportunity score (same formula as index.html)
        caps = grp['capacity'].dropna()
        caps = caps[caps > 0]
        avg_cap = float(caps.mean()) if len(caps) > 0 else 1500
        venue_annual = max(avg_cap, 1500) * 12 * 45 * 0.025
        n_winnable = t1 + t2
        annual_rev = n_winnable * venue_annual
        if annual_rev > 0:
            log_rev = math.log10(max(annual_rev, 1))
            roi_factor = max(0, min((log_rev - 5.0) / 3.5, 1)) * 100
        else:
            roi_factor = 0
        opp_score = (avg_rs * 0.25 + ms * 0.20 +
                     min(t1 / 30, 1) * 100 * 0.20 +
                     min(n_winnable / 200, 1) * 100 * 0.15 +
                     roi_factor * 0.20)

        markets[country] = {
            'n': n, 'r': region,
            'ps': round(float(avg_ps), 1) if not pd.isna(avg_ps) else 0,
            'rs': round(float(avg_rs), 1) if not pd.isna(avg_rs) else 0,
            'os': round(opp_score, 1),
            'ms': ms, 't1': t1, 't2': t2, 'tp': top_plat,
            'la': round(float(lat_c), 3) if not pd.isna(lat_c) else 0,
            'lo': round(float(lon_c), 3) if not pd.isna(lon_c) else 0,
        }

    return markets


def prepare_regions(df):
    if 'region' not in df.columns:
        return {}
    regions = {}
    for region, grp in df.groupby('region'):
        if pd.isna(region) or not region:
            continue
        avg_ps = grp['priority_score'].mean() if 'priority_score' in grp.columns else 0
        def _eff_rs_r(row):
            v = row.get('recommendation_score')
            return round(float(v), 1) if pd.notna(v) else (
                round(float(row.get('priority_score', 0)), 1) if pd.notna(row.get('priority_score')) else 0
            )
        eff_scores = grp.apply(_eff_rs_r, axis=1)
        t1 = int((eff_scores >= 65).sum())
        t2 = int(((eff_scores >= 61) & (eff_scores < 65)).sum())
        co = grp['country'].nunique() if 'country' in grp.columns else 0
        regions[str(region)] = {
            'n': len(grp), 'co': int(co),
            'ps': round(float(avg_ps), 1) if not pd.isna(avg_ps) else 0,
            't1': t1, 't2': t2,
        }
    return regions


def compute_kpis(venues):
    total = len(venues)
    t1 = sum(1 for v in venues if v['ti'] == 1)
    t2 = sum(1 for v in venues if v['ti'] == 2)
    t3 = sum(1 for v in venues if v['ti'] == 3)
    t4 = sum(1 for v in venues if v['ti'] == 4)
    avg_opp = round(sum(v['rs'] for v in venues) / max(total, 1), 1)
    countries = len(set(v['co'] for v in venues if v['co']))
    regions = len(set(v['r'] for v in venues if v['r']))
    coords = sum(1 for v in venues if 'la' in v)
    return {
        'total': total, 'coords': coords, 'countries': countries, 'regions': regions,
        't1': t1, 't2': t2, 't3': t3, 't4': t4, 'avg_opp': avg_opp,
    }


def prepare_top_recs(venues, markets):
    """Prepare top 3 country recommendations with reasoning and ROI."""
    country_data = {}
    for v in venues:
        co = v['co']
        if not co:
            continue
        if co not in country_data:
            country_data[co] = []
        country_data[co].append(v)

    ranked = []
    for co, vlist in country_data.items():
        if len(vlist) < 3:
            continue
        m = markets.get(co, {})
        n = len(vlist)
        scores = [v['rs'] for v in vlist]
        avg_score = sum(scores) / n
        ms = m.get('ms', 0)
        t1 = sum(1 for v in vlist if v['ti'] == 1)
        t2 = sum(1 for v in vlist if v['ti'] == 2)
        caps = [v['cap'] for v in vlist if v['cap'] > 0]
        avg_cap = sum(caps) / max(len(caps), 1) if caps else 1500
        avg_ex = sum(v['ex'] for v in vlist) / n
        avg_pf = sum(v['pf'] for v in vlist) / n
        avg_roi = sum(v['roi'] for v in vlist) / n

        # ROI estimates — how much Tixr earns from this market
        venue_annual = max(avg_cap, 1500) * 12 * 45 * 0.025
        n_winnable = t1 + t2
        annual_rev = n_winnable * venue_annual
        invest_per_venue = 8000
        market_base = 50000
        total_invest = market_base + n_winnable * invest_per_venue
        roi_multiple = round(annual_rev / max(total_invest, 1), 1) if annual_rev > 0 else 0

        # ROI factor: annual revenue normalized (log-scale to avoid mega-markets
        # completely dominating, but still rewarding scale meaningfully)
        if annual_rev > 0:
            # log10($1M)=6, log10($100M)=8, log10($1B)=9
            # Normalize: log10(rev) mapped from [5..8.5] → [0..100]
            log_rev = math.log10(max(annual_rev, 1))
            roi_factor = max(0, min((log_rev - 5.0) / 3.5, 1)) * 100
        else:
            roi_factor = 0

        rank_score = (avg_score * 0.25 +                       # avg recommendation_score (§7.7)
                      ms * 0.20 +                              # market fundamentals (§7.5)
                      min(t1 / 30, 1) * 100 * 0.20 +          # T1 readiness (saturates at 30)
                      min(n_winnable / 200, 1) * 100 * 0.15 + # pipeline depth (saturates at 200)
                      roi_factor * 0.20)                       # earning potential (log-scale annual rev)

        def fmt_money(val):
            if val >= 1_000_000:
                return "$" + str(round(val / 1_000_000, 1)) + "M"
            elif val >= 1000:
                return "$" + str(round(val / 1000)) + "K"
            return "$" + str(round(val))

        # Why this location
        why = []
        if ms >= 50:
            why.append("Strong market fundamentals (market score: " + str(ms) + ") — high GDP, digital readiness, and tourism")
        elif ms >= 30:
            why.append("Developing market with growth potential (market score: " + str(ms) + ")")
        if t1 > 0:
            why.append(str(t1) + " Tier 1 venues ready for immediate sales outreach")
        if t1 + t2 >= 10:
            why.append(str(t1 + t2) + " high-priority venues (Tier 1+2) in the pipeline")
        if avg_score >= 65:
            why.append("High average recommendation score (" + str(round(avg_score, 1)) + ") across " + str(n) + " venues")
        if avg_pf >= 55:
            why.append("Strong premium fit (" + str(round(avg_pf)) + "% avg) — venues align with Tixr's premium positioning")
        if avg_ex <= 45:
            why.append("Low exclusivity risk — limited existing platform lock-in")
        if avg_cap >= 5000:
            why.append("Large venue capacities (avg " + "{:,}".format(int(avg_cap)) + ") — higher revenue per venue")
        if n >= 200:
            why.append("Deep venue pipeline (" + str(n) + " venues) — significant scale opportunity")
        if annual_rev >= 1_000_000:
            why.append("Estimated " + fmt_money(annual_rev) + "/yr earning potential (" + str(roi_multiple) + "x ROI on " + fmt_money(total_invest) + " investment)")
        if not why:
            why.append(str(n) + " venues with avg score " + str(round(avg_score, 1)))

        # Key risks
        risks = []
        tp = m.get('tp', '')
        if tp:
            risks.append("Incumbent platform (" + tp + ") — requires competitive displacement strategy")
        if avg_ex >= 55:
            risks.append("Elevated exclusivity risk (avg " + str(round(avg_ex)) + "%) — some venues may have contracts")
        if ms < 40 and ms > 0:
            risks.append("Below-average market fundamentals — may limit growth ceiling")
        if ms == 0:
            risks.append("No market intelligence data — fundamentals unknown")
        if n < 30:
            risks.append("Small venue pipeline (" + str(n) + ") — limited room for scale")
        if roi_multiple < 5:
            risks.append("Lower ROI (" + str(roi_multiple) + "x) — smaller earning potential per dollar invested")
        if not risks:
            risks.append("No significant risks identified — strong candidate for expansion")

        ranked.append({
            'co': co,
            'r': m.get('r', ''),
            'avg': round(avg_score, 1),
            'ms': ms,
            'n': n,
            't1': t1, 't2': t2,
            'cap': int(avg_cap),
            'roi': round(avg_roi, 1),
            'opp': fmt_money(annual_rev),
            'invest': fmt_money(total_invest),
            'roix': roi_multiple,
            'rank': round(rank_score, 1),
            'why': why[:4],
            'risks': risks[:3],
        })

    ranked.sort(key=lambda x: x['rank'], reverse=True)
    return ranked[:3]


# ─── HTML TEMPLATE (plain string, no f-string) ──────────────────────────────

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tixr Global Venue Intelligence</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.css">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#080B12;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:#C8CDD8;overflow-x:hidden;}
::-webkit-scrollbar{width:6px;}
::-webkit-scrollbar-track{background:#0C0F18;}
::-webkit-scrollbar-thumb{background:#1F2937;border-radius:3px;}
.leaflet-container{background:#0A0C12!important;font-family:inherit!important;}
.leaflet-control-zoom a{background:#0D1018!important;color:#4B5563!important;border-color:rgba(255,255,255,0.08)!important;}
.leaflet-control-zoom a:hover{background:#161B2A!important;color:#E2E8F0!important;}
.marker-cluster-score{background:transparent!important;}
.ttip{background:rgba(8,11,18,0.97)!important;border:1px solid rgba(255,255,255,0.13)!important;border-radius:6px!important;color:#E2E8F0!important;font-size:12px!important;padding:6px 10px!important;box-shadow:none!important;line-height:1.5!important;}
.leaflet-tooltip.ttip::before{display:none!important;}
select option{background:#0D1018;color:#9CA3AF;}
.kpi-card{background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:12px 16px;text-align:center;min-width:110px;}
.kpi-val{font-size:22px;font-weight:700;font-family:'Courier New',monospace;line-height:1.1;}
.kpi-lbl{font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:#374151;margin-top:3px;}
.tab-btn{background:transparent;border:none;border-bottom:2px solid transparent;padding:10px 22px;font-size:13px;font-weight:500;color:#374151;cursor:pointer;font-family:inherit;transition:all 0.2s;}
.tab-btn.active{border-bottom-color:#F0A500;color:#F0A500;}
.tab-btn:hover{color:#9CA3AF;}
.fsel{background:#0C0F18;border:1px solid rgba(255,255,255,0.09);color:#6B7280;padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;outline:none;cursor:pointer;}
.finp{background:#0C0F18;border:1px solid rgba(255,255,255,0.09);color:#E2E8F0;padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;outline:none;width:200px;}
.finp::placeholder{color:#374151;}
.mcard{background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.055);border-radius:8px;padding:14px;cursor:pointer;transition:background 0.15s;}
.mcard:hover{background:rgba(255,255,255,0.05);}
.tb{display:inline-block;font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;}
.t1{background:rgba(16,185,129,0.15);color:#10B981;border:1px solid rgba(16,185,129,0.25);}
.t2{background:rgba(240,165,0,0.12);color:#F0A500;border:1px solid rgba(240,165,0,0.2);}
.t3{background:rgba(56,189,248,0.12);color:#38BDF8;border:1px solid rgba(56,189,248,0.2);}
.t4{background:rgba(239,68,68,0.1);color:#EF4444;border:1px solid rgba(239,68,68,0.2);}
.trow{border-bottom:1px solid rgba(255,255,255,0.03);transition:background 0.1s;cursor:pointer;}
.trow:hover{background:rgba(255,255,255,0.025);}
.th{text-align:left;padding:9px 11px;font-size:9px;letter-spacing:0.14em;color:#374151;font-weight:400;text-transform:uppercase;white-space:nowrap;}
.td{padding:9px 11px;font-size:12px;white-space:nowrap;}
.dpanel{position:fixed;top:0;right:-400px;width:400px;height:100vh;background:#0C0F18;border-left:1px solid rgba(255,255,255,0.08);z-index:10000;transition:right 0.3s ease;overflow-y:auto;padding:20px;}
.dpanel.open{right:0;}
.olay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:none;}
.olay.open{display:block;}
.bar{height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;}
.barfill{height:4px;border-radius:2px;transition:width 0.4s;}
.pgbtn{background:#0C0F18;border:1px solid rgba(255,255,255,0.09);color:#6B7280;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit;}
.pgbtn:hover{background:#161B2A;color:#E2E8F0;}
.rec-card{background:#0C0F18;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:24px;position:relative;margin-top:16px;}
.rec-rank{position:absolute;top:-12px;left:20px;font-weight:800;font-size:11px;padding:4px 14px;border-radius:20px;letter-spacing:0.05em;}
.rec-stat{background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:8px;text-align:center;}
.rec-stat-val{font-size:16px;font-weight:700;font-family:'Courier New',monospace;line-height:1.1;}
.rec-stat-lbl{font-size:8px;letter-spacing:0.12em;text-transform:uppercase;color:#374151;margin-top:2px;}
.rec-section{font-size:9px;letter-spacing:0.16em;text-transform:uppercase;font-weight:600;margin-bottom:8px;}
.rec-item{font-size:12px;color:#9CA3AF;line-height:1.6;padding-left:18px;position:relative;margin-bottom:4px;}
.rec-item::before{position:absolute;left:0;top:2px;}
.why-item::before{content:'\2713';color:#10B981;}
.risk-item::before{content:'\26A0';color:#F0A500;font-size:11px;}
.act-btn{flex:1;padding:9px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;font-weight:500;border:1px solid;transition:opacity 0.15s;}
.act-btn:hover{opacity:0.85;}
</style>
</head>
<body>

<!-- Header -->
<div style="background:#0C0F18;padding:13px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.06);">
  <div style="display:flex;align-items:center;gap:11px;">
    <div style="background:#F0A500;border-radius:4px;padding:3px 9px;font-size:12px;font-weight:800;color:#0C0F18;letter-spacing:0.04em;">TIXR</div>
    <span style="color:rgba(255,255,255,0.12);font-size:20px;font-weight:200;">|</span>
    <span style="font-size:14px;font-weight:500;color:#E2E8F0;">Global Venue Intelligence</span>
    <span class="tb t2">PIPELINE v2</span>
  </div>
  <div style="display:flex;align-items:center;gap:13px;">
    <span style="font-size:10px;color:#374151;font-family:'Courier New',monospace;" id="gen-date"></span>
    <span style="font-size:11px;color:#374151;display:flex;align-items:center;gap:5px;">
      <span style="width:5px;height:5px;border-radius:50%;background:#10B981;display:inline-block;"></span>
      <span id="hdr-stats"></span>
    </span>
  </div>
</div>

<!-- KPI Bar -->
<div id="kpi-bar" style="background:#080B12;padding:14px 20px;display:flex;gap:10px;overflow-x:auto;border-bottom:1px solid rgba(255,255,255,0.04);"></div>

<!-- Tabs -->
<div style="background:#0C0F18;display:flex;border-bottom:1px solid rgba(255,255,255,0.06);">
  <button class="tab-btn active" id="tab-btn-0" onclick="switchTab(0)">Recommendations</button>
  <button class="tab-btn" id="tab-btn-1" onclick="switchTab(1)">Map Intelligence</button>
  <button class="tab-btn" id="tab-btn-2" onclick="switchTab(2)">Venue Pipeline</button>
  <button class="tab-btn" id="tab-btn-3" onclick="switchTab(3)">Market Scorecard</button>
</div>

<!-- Recommendations Tab (Landing Page) -->
<div id="tab-0" style="padding:24px 20px;background:#080B12;min-height:calc(100vh - 170px);">
  <div style="margin-bottom:8px;">
    <div style="font-size:20px;font-weight:600;color:#E2E8F0;margin-bottom:6px;">Top Market Recommendations</div>
    <div style="font-size:12px;color:#4B5563;">AI-powered market prioritization based on venue pipeline quality, market fundamentals, and ROI potential</div>
  </div>
  <div id="rec-cards" style="max-width:920px;"></div>
</div>

<!-- Map Tab -->
<div id="tab-1" style="display:none;height:calc(100vh - 170px);position:relative;">
  <div id="sidebar" style="width:210px;min-width:210px;background:#0C0F18;overflow-y:auto;border-right:1px solid rgba(255,255,255,0.06);padding:10px;float:left;height:100%;"></div>
  <div style="margin-left:210px;position:relative;height:100%;">
    <div id="lmap" style="height:100%;width:100%;"></div>
    <div style="position:absolute;bottom:14px;left:10px;background:rgba(8,11,18,0.93);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:10px 13px;z-index:999;pointer-events:none;">
      <div style="font-size:9px;letter-spacing:0.16em;color:#374151;text-transform:uppercase;margin-bottom:7px;">Score Legend</div>
      <div style="font-size:11px;color:#4B5563;display:flex;flex-direction:column;gap:5px;">
        <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#10B981;display:inline-block;"></span>Score 65+ (Tier 1)</div>
        <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#F0A500;display:inline-block;"></span>Score 61-64 (Tier 2)</div>
        <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#38BDF8;display:inline-block;"></span>Score 48-60 (Tier 3)</div>
        <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#EF4444;display:inline-block;"></span>Score &lt;30 (Low Priority)</div>
      </div>
    </div>
    <div style="position:absolute;top:10px;right:10px;background:rgba(8,11,18,0.93);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:8px 12px;z-index:999;">
      <div style="font-size:9px;letter-spacing:0.13em;color:#374151;text-transform:uppercase;margin-bottom:5px;">Filter Map</div>
      <select id="map-tier" onchange="refreshMap()" class="fsel" style="font-size:11px;padding:4px 8px;">
        <option value="">All Tiers</option>
        <option value="1">Tier 1</option>
        <option value="2">Tier 2</option>
        <option value="3">Tier 3</option>
        <option value="12">Tier 1+2</option>
      </select>
    </div>
  </div>
</div>

<!-- Table Tab -->
<div id="tab-2" style="display:none;padding:16px 20px;background:#080B12;min-height:calc(100vh - 170px);">
  <div style="display:flex;gap:7px;margin-bottom:13px;flex-wrap:wrap;align-items:center;">
    <input type="text" id="f-search" class="finp" placeholder="Search venue or city..." oninput="filterTable()">
    <select id="f-region" class="fsel" onchange="filterTable()"><option value="">All Regions</option></select>
    <select id="f-country" class="fsel" onchange="filterTable()"><option value="">All Countries</option></select>
    <select id="f-tier" class="fsel" onchange="filterTable()">
      <option value="">All Tiers</option><option value="1">Tier 1</option><option value="2">Tier 2</option><option value="3">Tier 3</option><option value="4">Tier 4</option>
    </select>
    <select id="f-type" class="fsel" onchange="filterTable()"><option value="">All Types</option></select>
    <select id="f-excl" class="fsel" onchange="filterTable()">
      <option value="">All Exclusivity</option><option value="lo">Low Risk</option><option value="md">Medium</option><option value="hi">High</option>
    </select>
    <select id="f-sort" class="fsel" onchange="filterTable()">
      <option value="rs">Sort: Rec Score</option><option value="ps">Sort: Priority</option><option value="ex">Sort: Excl Risk</option><option value="cap">Sort: Capacity</option><option value="pf">Sort: Premium Fit</option><option value="roi">Sort: ROI</option>
    </select>
    <span id="tbl-count" style="margin-left:auto;font-size:10px;color:#374151;font-family:'Courier New',monospace;"></span>
  </div>
  <div style="border:1px solid rgba(255,255,255,0.06);border-radius:8px;overflow:hidden;">
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.07);">
        <th class="th" style="width:28px;">#</th>
        <th class="th">Venue</th>
        <th class="th">City</th>
        <th class="th">Country</th>
        <th class="th">Type</th>
        <th class="th" style="text-align:right;">Capacity</th>
        <th class="th">Platform</th>
        <th class="th" style="text-align:center;">Excl Risk</th>
        <th class="th" style="text-align:center;">Fit</th>
        <th class="th" style="text-align:center;">Score</th>
        <th class="th" style="text-align:center;">ROI</th>
        <th class="th" style="text-align:center;">Tier</th>
      </tr></thead>
      <tbody id="tbl-body"></tbody>
    </table>
  </div>
  <div id="tbl-pager" style="display:flex;justify-content:center;gap:8px;margin-top:14px;"></div>
</div>

<!-- Markets Tab -->
<div id="tab-3" style="display:none;padding:16px 20px;background:#080B12;min-height:calc(100vh - 170px);">
  <div style="display:flex;gap:7px;margin-bottom:16px;align-items:center;">
    <select id="m-region" class="fsel" onchange="renderMarkets()"><option value="">All Regions</option></select>
    <select id="m-sort" class="fsel" onchange="renderMarkets()">
      <option value="os">Sort: Opp. Score</option><option value="n">Sort: Venue Count</option><option value="t12">Sort: Tier 1+2</option><option value="ms">Sort: Market Score</option>
    </select>
    <span id="mkt-count" style="margin-left:auto;font-size:10px;color:#374151;font-family:'Courier New',monospace;"></span>
  </div>
  <div id="mkt-grid" style="display:grid;grid-template-columns:repeat(auto-fill, minmax(300px, 1fr));gap:12px;"></div>
</div>

<!-- Detail Panel -->
<div class="olay" id="overlay" onclick="closeDetail()"></div>
<div class="dpanel" id="dpanel"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.js"></script>
<script>
var VD = /*__VENUES__*/[];
var MKT = /*__MARKETS__*/{};
var REG = /*__REGIONS__*/{};
var KPI = /*__KPI__*/{};
var TOP = /*__TOPRECS__*/[];
var GEN_DATE = "__DATE__";

// ── helpers ──
function tc(ti){return ti===1?'#10B981':ti===2?'#F0A500':ti===3?'#38BDF8':'#EF4444';}
function tl(ti){return ti===1?'Tier 1':ti===2?'Tier 2':ti===3?'Tier 3':ti===4?'Tier 4':'--';}
function tlf(ti){return ti===1?'Immediate Outreach':ti===2?'High Priority':ti===3?'Monitor':ti===4?'Low Priority':'Unscored';}
function ec(e){return e<30?'#10B981':e<60?'#F0A500':'#EF4444';}
function el(e){return e<30?'Low':e<60?'Med':'High';}
function oc(s){return s>=65?'#10B981':s>=61?'#F0A500':s>=48?'#38BDF8':'#EF4444';}
function fmt(n){return n?n.toLocaleString():'--';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function scBg(s){return s>=65?'rgba(16,185,129,':s>=61?'rgba(240,165,0,':s>=48?'rgba(56,189,248,':'rgba(239,68,68,';}

// ── KPI bar ──
(function(){
  var k=KPI, h='';
  var items=[
    [k.total,'#E2E8F0','Total Venues',true],[k.t1,'#10B981','Tier 1',k.t1>0],[k.t2,'#F0A500','Tier 2',k.t2>0],
    [k.t3,'#38BDF8','Tier 3',k.t3>0],[k.t4,'#EF4444','Tier 4',k.t4>0],[k.avg_opp,'#7C8EF7','Avg Score',true],
    [k.countries,'#A78BFA','Countries',true],[k.regions,'#FB923C','Regions',true]
  ];
  items.forEach(function(it){
    if(!it[3])return;
    h+='<div class="kpi-card"><div class="kpi-val" style="color:'+it[1]+';">'+fmt(it[0])+'</div><div class="kpi-lbl">'+it[2]+'</div></div>';
  });
  document.getElementById('kpi-bar').innerHTML=h;
  document.getElementById('hdr-stats').textContent=fmt(k.total)+' venues \u00b7 '+k.countries+' markets';
  document.getElementById('gen-date').textContent=GEN_DATE;
})();

// ── tabs ──
var MAP=null,MCG=null,mapInited=false;
function switchTab(idx){
  for(var i=0;i<4;i++){
    document.getElementById('tab-'+i).style.display=(i===idx)?((i===1)?'block':'block'):'none';
    var btn=document.getElementById('tab-btn-'+i);
    if(i===idx){btn.classList.add('active');}else{btn.classList.remove('active');}
  }
  if(idx===1){
    if(!mapInited){initMap();mapInited=true;}
    else{setTimeout(function(){MAP.invalidateSize();},100);}
  }
  if(idx===2)filterTable();
  if(idx===3)renderMarkets();
}

// ── recommendations tab ──
(function renderRecs(){
  var container=document.getElementById('rec-cards');
  if(!TOP.length){container.innerHTML='<div style="color:#374151;padding:40px;text-align:center;">No recommendations available. Run pipeline with --live flag.</div>';return;}
  var rankColors=['#10B981','#F0A500','#38BDF8'];
  var rankLabels=['#1 TOP RECOMMENDATION','#2 STRONG OPPORTUNITY','#3 HIGH POTENTIAL'];
  var h='';
  TOP.forEach(function(rec,i){
    var col=rankColors[i]||'#6B7280';
    var bg=scBg(rec.avg);
    h+='<div class="rec-card">';
    h+='<div class="rec-rank" style="background:'+col+';color:#0C0F18;">'+rankLabels[i]+'</div>';
    // header
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;margin-bottom:18px;">';
    h+='<div><div style="font-size:22px;font-weight:700;color:#E2E8F0;">'+esc(rec.co)+'</div>';
    h+='<div style="font-size:12px;color:#4B5563;">'+esc(rec.r)+' \u00b7 '+fmt(rec.n)+' venues \u00b7 Market Score: '+rec.ms+'</div></div>';
    h+='<div style="text-align:center;"><div style="font-size:38px;font-weight:800;color:'+oc(rec.rank)+';font-family:\'Courier New\',monospace;line-height:1;">'+rec.rank+'</div>';
    h+='<div style="font-size:9px;color:#374151;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;">Opportunity Score</div></div></div>';
    // stats
    h+='<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:18px;">';
    function st(l,v,c){return '<div class="rec-stat"><div class="rec-stat-val" style="color:'+c+';">'+v+'</div><div class="rec-stat-lbl">'+l+'</div></div>';}
    h+=st('Tier 1',rec.t1,'#10B981');
    h+=st('Tier 2',rec.t2,'#F0A500');
    h+=st('Avg Score',rec.avg,oc(rec.avg));
    h+=st('Opportunity',rec.opp,'#10B981');
    h+=st('ROI',rec.roix+'x','#10B981');
    h+='</div>';
    // why + risks
    h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:16px;">';
    h+='<div><div class="rec-section" style="color:#10B981;">Why This Location</div>';
    rec.why.forEach(function(w){h+='<div class="rec-item why-item">'+esc(w)+'</div>';});
    h+='</div>';
    h+='<div><div class="rec-section" style="color:#F0A500;">Key Risks</div>';
    rec.risks.forEach(function(r){h+='<div class="rec-item risk-item">'+esc(r)+'</div>';});
    h+='</div></div>';
    // actions
    h+='<div style="display:flex;gap:8px;">';
    h+='<button class="act-btn" onclick="goMapCountry(\''+esc(rec.co)+'\')" style="background:rgba(240,165,0,0.1);border-color:rgba(240,165,0,0.25);color:#F0A500;">Explore on Map</button>';
    h+='<button class="act-btn" onclick="goCountry(\''+esc(rec.co)+'\')" style="background:rgba(56,189,248,0.1);border-color:rgba(56,189,248,0.25);color:#38BDF8;">View Venues</button>';
    h+='<button class="act-btn" onclick="goMarketTab(\''+esc(rec.co)+'\')" style="background:rgba(124,142,247,0.1);border-color:rgba(124,142,247,0.25);color:#7C8EF7;">Market Details</button>';
    h+='</div>';
    h+='</div>';
  });
  container.innerHTML=h;
})();

// ── map ──
function initMap(){
  var mapDiv=document.getElementById('lmap');
  MAP=L.map(mapDiv,{zoomControl:true,attributionControl:false}).setView([20,10],2);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,subdomains:'abcd'}).addTo(MAP);
  setTimeout(function(){MAP.invalidateSize();},200);
  refreshMap();
  renderSidebar();
}

function refreshMap(){
  if(!MAP)return;
  if(MCG)MAP.removeLayer(MCG);
  MCG=L.markerClusterGroup({
    maxClusterRadius:50,spiderfyOnMaxZoom:true,showCoverageOnHover:false,
    iconCreateFunction:function(cluster){
      var markers=cluster.getAllChildMarkers();
      var total=0;
      markers.forEach(function(m){total+=(m._vscore||0);});
      var avg=Math.round(total/markers.length);
      var bg=scBg(avg);
      return L.divIcon({
        html:'<div style="background:'+bg+'0.15);border-radius:50%;width:40px;height:40px;display:flex;align-items:center;justify-content:center;"><div style="background:'+bg+'0.75);width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#0C0F18;font-weight:700;font-size:11px;font-family:Courier New,monospace;">'+avg+'</div></div>',
        className:'marker-cluster-score',
        iconSize:L.point(40,40)
      });
    }
  });
  var tf=document.getElementById('map-tier').value;
  VD.forEach(function(v){
    if(!v.la||!v.lo)return;
    if(tf){
      if(tf==='12'&&v.ti!==1&&v.ti!==2)return;
      if(tf!=='12'&&v.ti!==parseInt(tf))return;
    }
    var r=Math.max(5,Math.min(16,v.cap?Math.sqrt(v.cap/2000)*8:5));
    var color=oc(v.rs);
    var mk=L.circleMarker([v.la,v.lo],{radius:r,fillColor:color,color:'rgba(0,0,0,0.4)',weight:1.5,fillOpacity:0.8});
    mk._vscore=v.rs;
    var vidx=VD.indexOf(v);
    mk.on('click',function(){showDetail(vidx);});
    var tip='<strong>'+esc(v.n)+'</strong><br>'+esc(v.c)+(v.co?', '+esc(v.co):'')+'<br>';
    tip+=esc(v.t)+(v.cap?' \u00b7 '+fmt(v.cap):'');
    if(v.ti)tip+='<br><span style="color:'+oc(v.rs)+';">Score: '+v.rs+'</span> \u00b7 '+tl(v.ti);
    mk.bindTooltip(tip,{className:'ttip',direction:'top',offset:[0,-(r+5)]});
    MCG.addLayer(mk);
  });
  MAP.addLayer(MCG);
}

function renderSidebar(){
  var sb=document.getElementById('sidebar');
  var h='<div style="font-size:9px;letter-spacing:0.16em;color:#374151;text-transform:uppercase;margin-bottom:8px;padding-left:2px;">Regions</div>';
  var rKeys=Object.keys(REG).sort(function(a,b){return REG[b].n-REG[a].n;});
  var colors={EMEA:'#F0A500',APAC:'#38BDF8',LATAM:'#10B981',SEA:'#A78BFA',EMEA_Gulf:'#FB923C',EMEA_Africa:'#EF4444'};
  rKeys.forEach(function(rk){
    var r=REG[rk];
    var col=colors[rk]||'#6B7280';
    h+='<div class="mcard" style="margin-bottom:7px;padding:9px;" onclick="goRegion(\''+esc(rk)+'\')">';
    h+='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">';
    h+='<span style="font-size:12px;font-weight:600;color:#E2E8F0;">'+esc(rk)+'</span>';
    h+='<span style="font-size:9px;padding:2px 5px;border-radius:3px;background:rgba(255,255,255,0.05);color:'+col+';">'+r.co+' mkts</span>';
    h+='</div>';
    h+='<div style="font-size:10px;color:#4B5563;">'+fmt(r.n)+' venues \u00b7 Avg: '+r.ps+'</div>';
    if(r.t1||r.t2)h+='<div style="font-size:10px;margin-top:2px;"><span style="color:#10B981;">'+r.t1+' T1</span> \u00b7 <span style="color:#F0A500;">'+r.t2+' T2</span></div>';
    h+='</div>';
  });
  sb.innerHTML=h;
}

function goRegion(r){
  switchTab(2);
  document.getElementById('f-region').value=r;
  filterTable();
}

function goMapCountry(co){
  switchTab(1);
  var m=MKT[co];
  if(m&&m.la&&m.lo){
    setTimeout(function(){MAP.flyTo([m.la,m.lo],6,{duration:1.2});},300);
  }
}

function goMarketTab(co){
  switchTab(3);
}

// ── table ──
var tblPage=0,tblPS=50,tblF=[];

function filterTable(){
  var s=document.getElementById('f-search').value.toLowerCase();
  var rg=document.getElementById('f-region').value;
  var co=document.getElementById('f-country').value;
  var ti=document.getElementById('f-tier').value;
  var tp=document.getElementById('f-type').value;
  var ex=document.getElementById('f-excl').value;
  var so=document.getElementById('f-sort').value;

  tblF=VD.filter(function(v){
    if(s&&v.n.toLowerCase().indexOf(s)<0&&v.c.toLowerCase().indexOf(s)<0&&v.co.toLowerCase().indexOf(s)<0)return false;
    if(rg&&v.r!==rg)return false;
    if(co&&v.co!==co)return false;
    if(ti&&v.ti!==parseInt(ti))return false;
    if(tp&&v.t!==tp)return false;
    if(ex==='lo'&&v.ex>=30)return false;
    if(ex==='md'&&(v.ex<30||v.ex>=60))return false;
    if(ex==='hi'&&v.ex<60)return false;
    return true;
  });
  tblF.sort(function(a,b){
    if(so==='rs')return(b.rs||0)-(a.rs||0);
    if(so==='ps')return(b.ps||0)-(a.ps||0);
    if(so==='ex')return(a.ex||0)-(b.ex||0);
    if(so==='cap')return(b.cap||0)-(a.cap||0);
    if(so==='pf')return(b.pf||0)-(a.pf||0);
    if(so==='roi')return(b.roi||0)-(a.roi||0);
    return 0;
  });
  tblPage=0;
  renderPage();
  document.getElementById('tbl-count').textContent=tblF.length.toLocaleString()+' / '+VD.length.toLocaleString()+' venues';
}

function renderPage(){
  var st=tblPage*tblPS;
  var pg=tblF.slice(st,st+tblPS);
  var tb=document.getElementById('tbl-body');
  if(!pg.length){
    tb.innerHTML='<tr><td colspan="12" style="text-align:center;padding:30px;color:#374151;">No venues match filters</td></tr>';
    document.getElementById('tbl-pager').innerHTML='';
    return;
  }
  tb.innerHTML=pg.map(function(v,i){
    var idx=st+i+1;
    var vidx=VD.indexOf(v);
    var ecv=ec(v.ex),ocv=oc(v.rs);
    var tierH=v.ti?'<span class="tb t'+v.ti+'">'+tl(v.ti)+'</span>':'<span style="color:#374151;">--</span>';
    return '<tr class="trow" onclick="showDetail('+vidx+')">' +
      '<td class="td" style="color:#374151;font-family:\'Courier New\',monospace;">'+idx+'</td>' +
      '<td class="td" style="font-weight:500;color:#E2E8F0;max-width:180px;overflow:hidden;text-overflow:ellipsis;">'+esc(v.n)+'</td>' +
      '<td class="td" style="color:#4B5563;max-width:100px;overflow:hidden;text-overflow:ellipsis;">'+esc(v.c)+'</td>' +
      '<td class="td"><span style="font-size:10px;padding:2px 7px;border-radius:4px;background:rgba(255,255,255,0.05);color:#6B7280;">'+esc(v.co)+'</span></td>' +
      '<td class="td" style="color:#4B5563;font-size:11px;">'+esc(v.t)+'</td>' +
      '<td class="td" style="text-align:right;color:#4B5563;font-family:\'Courier New\',monospace;">'+(v.cap?fmt(v.cap):'--')+'</td>' +
      '<td class="td" style="color:#4B5563;max-width:100px;overflow:hidden;text-overflow:ellipsis;font-size:11px;">'+(v.vd||'--')+'</td>' +
      '<td class="td" style="text-align:center;"><span style="font-family:\'Courier New\',monospace;color:'+ecv+';">'+v.ex+'</span><span style="font-size:9px;margin-left:3px;color:'+ecv+';">'+el(v.ex)+'</span></td>' +
      '<td class="td" style="text-align:center;"><div style="display:flex;align-items:center;gap:4px;justify-content:center;"><div style="width:34px;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;"><div style="width:'+v.pf+'%;height:3px;background:#7C8EF7;border-radius:2px;"></div></div><span style="font-size:11px;color:#4B5563;">'+v.pf+'</span></div></td>' +
      '<td class="td" style="text-align:center;font-size:13px;font-weight:700;color:'+ocv+';font-family:\'Courier New\',monospace;">'+v.rs+'</td>' +
      '<td class="td" style="text-align:center;font-size:12px;font-weight:600;color:'+oc(v.roi)+';font-family:\'Courier New\',monospace;">'+v.roi+'</td>' +
      '<td class="td" style="text-align:center;">'+tierH+'</td></tr>';
  }).join('');

  var tp=Math.ceil(tblF.length/tblPS);
  var pager=document.getElementById('tbl-pager');
  if(tp<=1){pager.innerHTML='';return;}
  var ph='';
  if(tblPage>0)ph+='<button class="pgbtn" onclick="tblPage=0;renderPage();">&laquo;</button>';
  if(tblPage>0)ph+='<button class="pgbtn" onclick="tblPage--;renderPage();">&lsaquo; Prev</button>';
  ph+='<span style="font-size:11px;color:#4B5563;padding:4px 8px;">'+(tblPage+1)+' / '+tp+'</span>';
  if(tblPage<tp-1)ph+='<button class="pgbtn" onclick="tblPage++;renderPage();">Next &rsaquo;</button>';
  if(tblPage<tp-1)ph+='<button class="pgbtn" onclick="tblPage='+(tp-1)+';renderPage();">&raquo;</button>';
  pager.innerHTML=ph;
}

// ── markets tab ──
function renderMarkets(){
  var rg=document.getElementById('m-region').value;
  var so=document.getElementById('m-sort').value;
  var keys=Object.keys(MKT);
  if(rg)keys=keys.filter(function(k){return MKT[k].r===rg;});
  keys.sort(function(a,b){
    var A=MKT[a],B=MKT[b];
    if(so==='os')return(B.os||0)-(A.os||0);
    if(so==='n')return B.n-A.n;
    if(so==='t12')return(B.t1+B.t2)-(A.t1+A.t2);
    if(so==='ms')return B.ms-A.ms;
    return 0;
  });
  document.getElementById('mkt-count').textContent=keys.length+' markets';
  var grid=document.getElementById('mkt-grid');
  var regC={EMEA:'#F0A500',APAC:'#38BDF8',LATAM:'#10B981',SEA:'#A78BFA',EMEA_Gulf:'#FB923C',EMEA_Africa:'#EF4444'};
  grid.innerHTML=keys.map(function(co){
    var m=MKT[co];
    var rc=regC[m.r]||'#6B7280';
    function ms(l,v,c){return '<div style="text-align:center;"><div style="font-size:15px;font-weight:700;color:'+c+';font-family:\'Courier New\',monospace;">'+v+'</div><div style="font-size:8px;letter-spacing:0.1em;text-transform:uppercase;color:#374151;">'+l+'</div></div>';}
    return '<div class="mcard" onclick="goCountry(\''+esc(co)+'\')">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
      '<span style="font-size:14px;font-weight:600;color:#E2E8F0;">'+esc(co)+'</span>' +
      '<span style="font-size:9px;padding:2px 6px;border-radius:3px;background:rgba(255,255,255,0.05);color:'+rc+';">'+esc(m.r)+'</span></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px;">' +
      ms('Venues',m.n,'#E2E8F0')+ms('Opp. Score',m.os||'--',oc(m.os||0))+ms('Mkt Score',m.ms||'--',m.ms?oc(m.ms):'#374151')+'</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">' +
      ms('Tier 1',m.t1,'#10B981')+ms('Tier 2',m.t2,'#F0A500')+'</div>' +
      (m.tp?'<div style="font-size:10px;color:#374151;">Top platform: <span style="color:#6B7280;">'+esc(m.tp)+'</span></div>':'') +
      '</div>';
  }).join('');
}

function goCountry(co){
  switchTab(2);
  document.getElementById('f-country').value=co;
  filterTable();
}

// ── detail panel ──
function showDetail(vidx){
  var v=VD[vidx];
  if(!v)return;
  var dp=document.getElementById('dpanel');
  var ov=document.getElementById('overlay');
  dp.classList.add('open');ov.classList.add('open');
  var ecv=ec(v.ex),ocv=oc(v.rs);
  var h='';
  h+='<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">';
  h+='<div><div style="font-size:16px;font-weight:600;color:#E2E8F0;line-height:1.3;">'+esc(v.n)+'</div>';
  h+='<div style="font-size:11px;color:#4B5563;margin-top:3px;">'+esc(v.c)+(v.co?', '+esc(v.co):'')+' \u00b7 '+esc(v.t)+'</div></div>';
  h+='<button onclick="closeDetail()" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:4px;color:#4B5563;font-size:16px;cursor:pointer;padding:2px 8px;flex-shrink:0;">\u00d7</button></div>';

  if(v.ti){
    h+='<div style="margin-bottom:14px;"><span class="tb t'+v.ti+'" style="font-size:12px;padding:4px 12px;">'+tl(v.ti)+' \u2014 '+tlf(v.ti)+'</span></div>';
  }

  h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;">';
  h+='<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.055);border-radius:8px;padding:12px;text-align:center;">';
  h+='<div style="font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:#374151;margin-bottom:3px;">Rec Score</div>';
  h+='<div style="font-size:32px;font-weight:700;color:'+ocv+';font-family:\'Courier New\',monospace;line-height:1.1;">'+v.rs+'</div>';
  h+='<div style="font-size:10px;color:#374151;">/100</div></div>';
  h+='<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.055);border-radius:8px;padding:12px;text-align:center;">';
  h+='<div style="font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:#374151;margin-bottom:3px;">ROI Index</div>';
  h+='<div style="font-size:32px;font-weight:700;color:'+oc(v.roi)+';font-family:\'Courier New\',monospace;line-height:1.1;">'+v.roi+'</div>';
  h+='<div style="font-size:10px;color:#374151;">score \u00d7 win \u00d7 fit</div></div>';
  h+='</div>';

  function ds(l,val){return '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:6px;padding:7px 9px;"><div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:#374151;margin-bottom:2px;">'+l+'</div><div style="font-size:11px;font-weight:500;color:#9CA3AF;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'+val+'</div></div>';}
  h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:14px;">';
  h+=ds('Capacity',v.cap?fmt(v.cap):'Unknown');
  h+=ds('Platform',v.vd||'Unknown');
  h+=ds('Exclusivity',v.es||'Unknown');
  h+=ds('Region',v.r||'--');
  h+=ds('Website',v.w?'Yes':'No');
  h+=ds('Priority',v.ps);
  h+='</div>';

  h+='<div style="margin-bottom:10px;">';
  h+='<div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px;"><span style="color:#4B5563;">Exclusivity Risk</span><span style="color:'+ecv+';">'+v.ex+' \u00b7 '+el(v.ex)+'</span></div>';
  h+='<div class="bar"><div class="barfill" style="width:'+v.ex+'%;background:'+ecv+';"></div></div></div>';

  h+='<div style="margin-bottom:10px;">';
  h+='<div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px;"><span style="color:#4B5563;">Premium Fit</span><span style="color:#C8CDD8;">'+v.pf+'%</span></div>';
  h+='<div class="bar"><div class="barfill" style="width:'+v.pf+'%;background:#7C8EF7;"></div></div></div>';

  h+='<div style="margin-bottom:14px;">';
  h+='<div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px;"><span style="color:#4B5563;">Priority Score</span><span style="color:#C8CDD8;">'+v.ps+'</span></div>';
  h+='<div class="bar"><div class="barfill" style="width:'+Math.min(v.ps,100)+'%;background:#A78BFA;"></div></div></div>';

  h+='<div style="display:flex;gap:8px;margin-top:16px;">';
  if(v.la&&v.lo){
    h+='<button onclick="flyTo('+v.la+','+v.lo+')" style="flex:1;background:rgba(240,165,0,0.1);border:1px solid rgba(240,165,0,0.25);color:#F0A500;padding:8px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;">Show on Map</button>';
  }
  h+='<button onclick="goCountry(\''+esc(v.co)+'\')" style="flex:1;background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.25);color:#38BDF8;padding:8px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;">View Market</button>';
  h+='</div>';
  dp.innerHTML=h;
}

function closeDetail(){
  document.getElementById('dpanel').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
}

function flyTo(la,lo){
  closeDetail();
  switchTab(1);
  setTimeout(function(){MAP.flyTo([la,lo],15,{duration:1.2});},350);
}

// ── init ──
(function(){
  var regions=Object.keys(REG).sort();
  var countries=Object.keys(MKT).sort();
  var types=[];
  var seen={};
  VD.forEach(function(v){if(v.t&&!seen[v.t]){seen[v.t]=1;types.push(v.t);}});
  types.sort();

  var ro=regions.map(function(r){return '<option value="'+esc(r)+'">'+esc(r)+'</option>';}).join('');
  document.getElementById('f-region').innerHTML='<option value="">All Regions</option>'+ro;
  document.getElementById('m-region').innerHTML='<option value="">All Regions</option>'+ro;

  var co=countries.map(function(c){return '<option value="'+esc(c)+'">'+esc(c)+'</option>';}).join('');
  document.getElementById('f-country').innerHTML='<option value="">All Countries</option>'+co;

  var to=types.map(function(t){return '<option value="'+esc(t)+'">'+esc(t)+'</option>';}).join('');
  document.getElementById('f-type').innerHTML='<option value="">All Types</option>'+to;
})();
</script>
</body>
</html>'''


def generate_html(venues_json, markets_json, regions_json, kpis_json, toprecs_json, generated_at):
    """Build the complete HTML by replacing placeholders in the template."""
    html = HTML_TEMPLATE
    html = html.replace('/*__VENUES__*/[]', venues_json)
    html = html.replace('/*__MARKETS__*/{}', markets_json)
    html = html.replace('/*__REGIONS__*/{}', regions_json)
    html = html.replace('/*__KPI__*/{}', kpis_json)
    html = html.replace('/*__TOPRECS__*/[]', toprecs_json)
    html = html.replace('__DATE__', generated_at)
    return html


def main():
    parser = argparse.ArgumentParser(description='Generate Tixr dashboard')
    parser.add_argument('--output-dir', type=str, default='output')
    parser.add_argument('--output', type=str, default='tixr_dashboard.html')
    args = parser.parse_args()

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output_dir)

    df, market_df, source_path = load_data(output_dir)

    print("Geocoding missing coordinates...")
    df = geocode_missing(df)

    # Exclude markets Tixr has already penetrated
    exclude_markets = {'United States', 'USA', 'US', 'Canada', 'United Kingdom', 'UK'}
    before_ex = len(df)
    df = df[~df['country'].fillna('').isin(exclude_markets)]
    print("  Removed " + str(before_ex - len(df)) + " venues from penetrated markets (US/Canada/UK). " + str(len(df)) + " remaining")

    print("Preparing venue data...")
    venues = prepare_venues(df)
    print("  " + str(len(venues)) + " venues prepared")

    print("Preparing market data...")
    markets = prepare_markets(df)
    print("  " + str(len(markets)) + " markets")

    print("Preparing region data...")
    regions = prepare_regions(df)
    print("  " + str(len(regions)) + " regions")

    kpis = compute_kpis(venues)

    print("Preparing top recommendations...")
    top_recs = prepare_top_recs(venues, markets)
    for i, rec in enumerate(top_recs):
        print("  #" + str(i+1) + ": " + rec['co'] + " (score: " + str(rec['avg']) + ", " + str(rec['n']) + " venues)")

    venues_json = json.dumps(venues, separators=(',', ':'))
    markets_json = json.dumps(markets, separators=(',', ':'))
    regions_json = json.dumps(regions, separators=(',', ':'))
    kpis_json = json.dumps(kpis, separators=(',', ':'))
    toprecs_json = json.dumps(top_recs, separators=(',', ':'))

    generated_at = datetime.now().strftime('%b %d %Y %H:%M')

    print("\nGenerating dashboard...")
    html = generate_html(venues_json, markets_json, regions_json, kpis_json, toprecs_json, generated_at)

    out_path = os.path.join(output_dir, args.output)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print("\nDashboard generated: " + out_path)
    print("  Size: {:.1f} MB".format(size_mb))
    print("  Venues: {:,}".format(len(venues)))
    print("  Markets: " + str(len(markets)))
    print("  Regions: " + str(len(regions)))
    print("\nOpen in browser:")
    print("  open " + out_path)


if __name__ == '__main__':
    main()

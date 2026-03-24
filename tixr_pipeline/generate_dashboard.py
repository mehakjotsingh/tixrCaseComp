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

        rt = safe_str(row.get('recommendation_tier'))
        tier_num = 0
        if 'Tier 1' in rt: tier_num = 1
        elif 'Tier 2' in rt: tier_num = 2
        elif 'Tier 3' in rt: tier_num = 3
        elif 'Tier 4' in rt: tier_num = 4

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
        avg_rs = grp['recommendation_score'].mean() if 'recommendation_score' in grp.columns else avg_ps

        t1, t2 = 0, 0
        if 'recommendation_tier' in grp.columns:
            tiers = grp['recommendation_tier'].fillna('')
            t1 = int(tiers.str.contains('Tier 1').sum())
            t2 = int(tiers.str.contains('Tier 2').sum())

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

        markets[country] = {
            'n': n, 'r': region,
            'ps': round(float(avg_ps), 1) if not pd.isna(avg_ps) else 0,
            'rs': round(float(avg_rs), 1) if not pd.isna(avg_rs) else 0,
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
        t1, t2 = 0, 0
        if 'recommendation_tier' in grp.columns:
            tiers = grp['recommendation_tier'].fillna('')
            t1 = int(tiers.str.contains('Tier 1').sum())
            t2 = int(tiers.str.contains('Tier 2').sum())
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
    """Prepare top 3 country recommendations — kept for initial render."""
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

        venue_annual = max(avg_cap, 1500) * 12 * 45 * 0.025
        n_winnable = t1 + t2
        annual_rev = n_winnable * venue_annual
        invest_per_venue = 8000
        market_base = 50000
        total_invest = market_base + n_winnable * invest_per_venue
        roi_multiple = round(annual_rev / max(total_invest, 1), 1) if annual_rev > 0 else 0

        if annual_rev > 0:
            log_rev = math.log10(max(annual_rev, 1))
            roi_factor = max(0, min((log_rev - 5.0) / 3.5, 1)) * 100
        else:
            roi_factor = 0

        rank_score = (avg_score * 0.25 +
                      ms * 0.20 +
                      min(t1 / 30, 1) * 100 * 0.20 +
                      min(n_winnable / 200, 1) * 100 * 0.15 +
                      roi_factor * 0.20)

        def fmt_money(val):
            if val >= 1_000_000:
                return "$" + str(round(val / 1_000_000, 1)) + "M"
            elif val >= 1000:
                return "$" + str(round(val / 1000)) + "K"
            return "$" + str(round(val))

        why = []
        if ms >= 50:
            why.append("Strong market fundamentals (market score: " + str(ms) + ") \u2014 high GDP, digital readiness, and tourism")
        elif ms >= 30:
            why.append("Developing market with growth potential (market score: " + str(ms) + ")")
        if t1 > 0:
            why.append(str(t1) + " Tier 1 venues ready for immediate sales outreach")
        if t1 + t2 >= 10:
            why.append(str(t1 + t2) + " high-priority venues (Tier 1+2) in the pipeline")
        if avg_score >= 60:
            why.append("High average recommendation score (" + str(round(avg_score, 1)) + ") across " + str(n) + " venues")
        if avg_pf >= 55:
            why.append("Strong premium fit (" + str(round(avg_pf)) + "% avg) \u2014 venues align with Tixr's premium positioning")
        if avg_ex <= 45:
            why.append("Low exclusivity risk \u2014 limited existing platform lock-in")
        if avg_cap >= 5000:
            why.append("Large venue capacities (avg " + "{:,}".format(int(avg_cap)) + ") \u2014 higher revenue per venue")
        if n >= 200:
            why.append("Deep venue pipeline (" + str(n) + " venues) \u2014 significant scale opportunity")
        if annual_rev >= 1_000_000:
            why.append("Estimated " + fmt_money(annual_rev) + "/yr earning potential (" + str(roi_multiple) + "x ROI on " + fmt_money(total_invest) + " investment)")
        if not why:
            why.append(str(n) + " venues with avg score " + str(round(avg_score, 1)))

        risks = []
        tp = m.get('tp', '')
        if tp:
            risks.append("Incumbent platform (" + tp + ") \u2014 requires competitive displacement strategy")
        if avg_ex >= 55:
            risks.append("Elevated exclusivity risk (avg " + str(round(avg_ex)) + "%) \u2014 some venues may have contracts")
        if ms < 40 and ms > 0:
            risks.append("Below-average market fundamentals \u2014 may limit growth ceiling")
        if ms == 0:
            risks.append("No market intelligence data \u2014 fundamentals unknown")
        if n < 30:
            risks.append("Small venue pipeline (" + str(n) + ") \u2014 limited room for scale")
        if roi_multiple < 5:
            risks.append("Lower ROI (" + str(roi_multiple) + "x) \u2014 smaller earning potential per dollar invested")
        if not risks:
            risks.append("No significant risks identified \u2014 strong candidate for expansion")

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


# ─── HTML TEMPLATE ───────────────────────────────────────────────────────────

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tixr Scout \u2014 Global Venue Intelligence</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --bg:#080B12;--sb:#0C0F18;--cb:rgba(255,255,255,0.025);--cbr:rgba(255,255,255,0.06);
  --acc:#F0A500;--grn:#10B981;--blu:#38BDF8;--pur:#7C8EF7;--red:#EF4444;--org:#FB923C;
  --tp:#E2E8F0;--ts:#9CA3AF;--tm:#4B5563;--td:#374151;--mono:'Courier New',monospace;
}
body{background:var(--bg);font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:var(--ts);display:flex;min-height:100vh;overflow-x:hidden;}
::-webkit-scrollbar{width:5px;height:5px;}
::-webkit-scrollbar-track{background:#080B12;}
::-webkit-scrollbar-thumb{background:#1F2937;border-radius:3px;}

/* Sidebar */
#sidebar{position:fixed;top:0;left:0;width:220px;height:100vh;background:var(--sb);border-right:1px solid var(--cbr);display:flex;flex-direction:column;z-index:200;overflow-y:auto;}
#sb-logo{padding:16px;border-bottom:1px solid var(--cbr);display:flex;align-items:center;gap:10px;flex-shrink:0;}
.logo-mark{background:var(--acc);color:#0C0F18;font-weight:800;font-size:13px;padding:5px 9px;border-radius:5px;letter-spacing:0.05em;line-height:1;}
.logo-text{font-size:13px;font-weight:600;color:var(--tp);line-height:1.25;}
.logo-sub{font-size:9px;color:var(--td);text-transform:uppercase;letter-spacing:0.12em;}
#sb-nav{flex:1;padding:10px 8px;}
.nav-sec{font-size:9px;letter-spacing:0.15em;text-transform:uppercase;color:var(--td);padding:10px 10px 4px;margin-top:2px;}
.nav-item{display:flex;align-items:center;gap:9px;padding:9px 12px;border-radius:7px;cursor:pointer;font-size:13px;font-weight:500;color:var(--tm);border-left:2px solid transparent;margin-bottom:2px;transition:all 0.15s;}
.nav-item:hover{background:rgba(255,255,255,0.03);color:var(--ts);}
.nav-item.active{background:rgba(240,165,0,0.07);border-left-color:var(--acc);color:var(--acc);}
.nav-ico{width:15px;height:15px;flex-shrink:0;opacity:0.6;}
.nav-item.active .nav-ico{opacity:1;}
.nav-badge{margin-left:auto;font-size:9px;padding:2px 6px;border-radius:9px;background:rgba(255,255,255,0.05);color:var(--td);font-family:var(--mono);}
.nav-item.active .nav-badge{background:rgba(240,165,0,0.1);color:var(--acc);}
#sb-foot{padding:12px 14px;border-top:1px solid var(--cbr);flex-shrink:0;}
.status-dot{width:6px;height:6px;border-radius:50%;background:var(--grn);display:inline-block;margin-right:5px;}

/* Main */
#main-wrap{margin-left:220px;flex:1;display:flex;flex-direction:column;min-height:100vh;}
#top-bar{background:var(--sb);border-bottom:1px solid var(--cbr);padding:0 22px;height:54px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;flex-shrink:0;}
.tb-title{font-size:15px;font-weight:600;color:var(--tp);}
.tb-sub{font-size:10px;color:var(--tm);margin-top:2px;}

/* Scope button */
#scope-btn{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);color:var(--ts);padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit;font-weight:500;transition:all 0.15s;}
#scope-btn:hover{background:rgba(255,255,255,0.07);border-color:rgba(255,255,255,0.15);color:var(--tp);}
#scope-btn.active{background:rgba(240,165,0,0.1);border-color:rgba(240,165,0,0.3);color:var(--acc);}
#scope-hidden-badge{background:var(--acc);color:#0C0F18;font-size:9px;font-weight:700;padding:2px 6px;border-radius:8px;font-family:var(--mono);display:none;}

/* Scope modal */
#scope-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.65);z-index:8000;display:none;align-items:flex-start;justify-content:center;overflow-y:auto;padding:40px 20px;}
#scope-overlay.open{display:flex;}
#scope-modal{background:var(--sb);border:1px solid rgba(255,255,255,0.09);border-radius:14px;width:100%;max-width:620px;overflow:hidden;flex-shrink:0;}
.scope-hdr{padding:20px 24px 16px;border-bottom:1px solid var(--cbr);display:flex;align-items:flex-start;justify-content:space-between;}
.scope-body{padding:20px 24px;max-height:65vh;overflow-y:auto;}
.scope-ftr{padding:14px 24px;border-top:1px solid var(--cbr);display:flex;align-items:center;justify-content:space-between;}
.scope-sec-title{font-size:10px;font-weight:600;letter-spacing:0.14em;text-transform:uppercase;color:var(--td);margin-bottom:10px;}
/* Region toggle pills */
.rpill{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:500;border:1px solid;transition:all 0.15s;user-select:none;}
.rpill.on{color:var(--tp);}
.rpill.off{color:var(--td);background:rgba(255,255,255,0.02)!important;border-color:rgba(255,255,255,0.06)!important;text-decoration:line-through;}
/* Country toggle pills */
.cpill{display:inline-flex;align-items:center;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:500;border:1px solid rgba(255,255,255,0.07);background:rgba(255,255,255,0.03);color:var(--ts);transition:all 0.15s;user-select:none;}
.cpill:hover{border-color:rgba(255,255,255,0.15);}
.cpill.off{color:var(--td);background:rgba(255,255,255,0.01)!important;border-color:rgba(255,255,255,0.04)!important;text-decoration:line-through;}
/* Scope live counter */
#scope-counter{background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:8px;padding:10px 14px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;}
#scope-counter.warn{background:rgba(240,165,0,0.08);border-color:rgba(240,165,0,0.2);}
.scope-pbar{height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;margin-top:4px;}
.scope-pbar-fill{height:3px;border-radius:2px;background:var(--grn);transition:width 0.3s;}

/* Tab panes */
.tab-pane{flex:1;background:var(--bg);padding:22px;min-height:calc(100vh - 54px);}
.map-pane{padding:0;display:flex;height:calc(100vh - 54px);overflow:hidden;}

/* KPI grid */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:20px;}
.kpi-card{background:var(--cb);border:1px solid var(--cbr);border-radius:10px;padding:14px 16px;}
.kpi-val{font-size:24px;font-weight:700;font-family:var(--mono);line-height:1.1;margin-bottom:4px;}
.kpi-lbl{font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:var(--td);}
.kpi-sub{font-size:10px;color:var(--tm);margin-top:2px;}

/* Charts */
.charts-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px;}
.chart-card{background:var(--cb);border:1px solid var(--cbr);border-radius:10px;padding:16px;}
.chart-title{font-size:10px;font-weight:600;color:var(--tp);text-transform:uppercase;letter-spacing:0.14em;margin-bottom:14px;}

/* Section headers */
.sec-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}
.sec-title{font-size:13px;font-weight:600;color:var(--tp);}
.sec-sub{font-size:10px;color:var(--tm);margin-top:1px;}

/* Tier badges */
.tb{display:inline-block;font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;}
.t1{background:rgba(16,185,129,0.15);color:#10B981;border:1px solid rgba(16,185,129,0.25);}
.t2{background:rgba(240,165,0,0.12);color:#F0A500;border:1px solid rgba(240,165,0,0.2);}
.t3{background:rgba(56,189,248,0.12);color:#38BDF8;border:1px solid rgba(56,189,248,0.2);}
.t4{background:rgba(239,68,68,0.1);color:#EF4444;border:1px solid rgba(239,68,68,0.2);}

/* Tables */
.tbl-wrap{border:1px solid var(--cbr);border-radius:8px;overflow:hidden;}
.th{text-align:left;padding:9px 11px;font-size:9px;letter-spacing:0.14em;color:var(--td);font-weight:400;text-transform:uppercase;white-space:nowrap;}
.td{padding:9px 11px;font-size:12px;white-space:nowrap;border-bottom:1px solid rgba(255,255,255,0.03);}
.trow{cursor:pointer;transition:background 0.1s;}
.trow:hover{background:rgba(255,255,255,0.025);}

/* Filters */
.filter-bar{display:flex;gap:7px;margin-bottom:14px;flex-wrap:wrap;align-items:center;}
.fsel{background:var(--sb);border:1px solid rgba(255,255,255,0.09);color:#6B7280;padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;outline:none;cursor:pointer;}
.finp{background:var(--sb);border:1px solid rgba(255,255,255,0.09);color:var(--tp);padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;outline:none;width:200px;}
.finp::placeholder{color:var(--td);}
select option{background:#0D1018;color:#9CA3AF;}
.pgbtn{background:var(--sb);border:1px solid rgba(255,255,255,0.09);color:#6B7280;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit;}
.pgbtn:hover{background:#161B2A;color:var(--tp);}

/* Market cards */
.mcard{background:var(--cb);border:1px solid rgba(255,255,255,0.055);border-radius:8px;padding:14px;cursor:pointer;transition:all 0.15s;}
.mcard:hover{background:rgba(255,255,255,0.05);border-color:rgba(255,255,255,0.1);}

/* Recommendation cards */
.rec-card{background:var(--sb);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:24px;position:relative;margin-top:18px;}
.rec-rank{position:absolute;top:-11px;left:20px;font-weight:800;font-size:11px;padding:4px 14px;border-radius:20px;letter-spacing:0.05em;}
.rec-stat{background:var(--cb);border:1px solid var(--cbr);border-radius:6px;padding:8px;text-align:center;}
.rec-stat-val{font-size:16px;font-weight:700;font-family:var(--mono);line-height:1.1;}
.rec-stat-lbl{font-size:8px;letter-spacing:0.12em;text-transform:uppercase;color:var(--td);margin-top:2px;}
.rec-section{font-size:9px;letter-spacing:0.16em;text-transform:uppercase;font-weight:600;margin-bottom:8px;}
.rec-item{font-size:12px;color:var(--ts);line-height:1.6;padding-left:18px;position:relative;margin-bottom:4px;}
.rec-item::before{position:absolute;left:0;top:2px;}
.why-item::before{content:'\2713';color:#10B981;}
.risk-item::before{content:'\26A0';color:#F0A500;font-size:11px;}
.act-btn{flex:1;padding:9px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;font-weight:500;border:1px solid;transition:opacity 0.15s;}
.act-btn:hover{opacity:0.85;}

/* Bar progress */
.bar{height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;}
.barfill{height:4px;border-radius:2px;transition:width 0.4s;}

/* Detail panel */
.dpanel{position:fixed;top:0;right:-420px;width:400px;height:100vh;background:var(--sb);border-left:1px solid rgba(255,255,255,0.08);z-index:10000;transition:right 0.3s ease;overflow-y:auto;padding:20px;}
.dpanel.open{right:0;}
.olay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999;display:none;}
.olay.open{display:block;}

/* Map */
#map-sidebar{width:210px;min-width:210px;background:var(--sb);overflow-y:auto;border-right:1px solid var(--cbr);padding:10px;height:100%;}
#lmap{flex:1;height:100%;}
.leaflet-container{background:#0A0C12!important;font-family:inherit!important;}
.leaflet-control-zoom a{background:#0D1018!important;color:#4B5563!important;border-color:rgba(255,255,255,0.08)!important;}
.leaflet-control-zoom a:hover{background:#161B2A!important;color:#E2E8F0!important;}
.marker-cluster-score{background:transparent!important;}
.ttip{background:rgba(8,11,18,0.97)!important;border:1px solid rgba(255,255,255,0.13)!important;border-radius:6px!important;color:#E2E8F0!important;font-size:12px!important;padding:6px 10px!important;box-shadow:none!important;line-height:1.5!important;}
.leaflet-tooltip.ttip::before{display:none!important;}

/* Tier dist list */
.tdist-item{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);}
.tdist-item:last-child{border-bottom:none;}

/* Scope search */
#scope-co-search{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);color:var(--tp);padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;outline:none;width:100%;margin-bottom:10px;}
#scope-co-search::placeholder{color:var(--td);}

@keyframes fadeIn{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}
.fade-in{animation:fadeIn 0.25s ease;}

/* ── Country Focus ── */
#map-focus-banner{position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:1200;display:none;
  background:rgba(8,11,18,0.96);border:1px solid rgba(124,142,247,0.4);border-radius:24px;
  padding:6px 14px 6px 10px;display:none;align-items:center;gap:8px;pointer-events:all;
  box-shadow:0 2px 16px rgba(124,142,247,0.15);}
#map-focus-banner.visible{display:flex;}
.mfb-dot{width:8px;height:8px;border-radius:50%;background:#7C8EF7;flex-shrink:0;}
.mfb-label{font-size:12px;font-weight:600;color:#E2E8F0;letter-spacing:0.01em;}
.mfb-clear{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
  color:#6B7280;font-size:10px;padding:2px 8px;border-radius:10px;cursor:pointer;
  font-family:inherit;transition:all 0.15s;margin-left:4px;}
.mfb-clear:hover{color:#E2E8F0;background:rgba(255,255,255,0.1);}

/* Country focus search in sidebar */
#map-co-search{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);
  color:var(--tp);padding:5px 8px;border-radius:6px;font-size:11px;font-family:inherit;
  outline:none;width:100%;margin-bottom:8px;box-sizing:border-box;}
#map-co-search::placeholder{color:var(--td);}
.map-co-pill{font-size:11px;padding:3px 9px;border-radius:4px;cursor:pointer;
  border:1px solid rgba(255,255,255,0.07);background:rgba(255,255,255,0.03);
  color:var(--ts);transition:all 0.12s;margin:2px 2px 2px 0;display:inline-block;user-select:none;}
.map-co-pill:hover{border-color:rgba(124,142,247,0.5);color:#E2E8F0;background:rgba(124,142,247,0.08);}

/* Country stats sidebar card */
.cs-back{display:flex;align-items:center;gap:6px;cursor:pointer;font-size:11px;color:#6B7280;
  padding:4px 0 10px;border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:10px;
  transition:color 0.12s;}
.cs-back:hover{color:#E2E8F0;}
.cs-name{font-size:14px;font-weight:700;color:#E2E8F0;margin-bottom:2px;}
.cs-region{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600;margin-bottom:10px;}
.cs-kpi-row{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:10px;}
.cs-kpi{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);
  border-radius:6px;padding:7px 9px;text-align:center;}
.cs-kpi-val{font-size:15px;font-weight:700;font-family:var(--mono);}
.cs-kpi-lbl{font-size:8px;letter-spacing:0.12em;text-transform:uppercase;color:var(--td);margin-top:1px;}
.cs-sec{font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:var(--td);
  font-weight:600;margin:10px 0 5px;}
.cs-tier-row{display:flex;align-items:center;gap:6px;margin-bottom:4px;}
.cs-bar-bg{flex:1;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;}
.cs-bar-fill{height:3px;border-radius:2px;}
.cs-venue-row{display:flex;align-items:baseline;justify-content:space-between;
  padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:11px;}
.cs-venue-row:last-child{border-bottom:none;}
.cs-venue-name{color:#C8CDD8;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:6px;}
.cs-score{font-family:var(--mono);font-weight:700;font-size:11px;}
</style>
</head>
<body>

<!-- ═══ SIDEBAR ═══ -->
<nav id="sidebar">
  <div id="sb-logo">
    <div class="logo-mark">T</div>
    <div>
      <div class="logo-text">TIXR Venue Intel</div>
      <div class="logo-sub">Scout v2</div>
    </div>
  </div>
  <div id="sb-nav">
    <div class="nav-sec">Analytics</div>
    <div class="nav-item active" id="nav-0" onclick="switchTab(0)">
      <svg class="nav-ico" viewBox="0 0 16 16" fill="currentColor">
        <rect x="1" y="1" width="6" height="6" rx="1.5"/><rect x="9" y="1" width="6" height="6" rx="1.5"/>
        <rect x="1" y="9" width="6" height="6" rx="1.5"/><rect x="9" y="9" width="6" height="6" rx="1.5"/>
      </svg>
      Overview<span class="nav-badge" id="nb-0"></span>
    </div>
    <div class="nav-item" id="nav-1" onclick="switchTab(1)">
      <svg class="nav-ico" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 1.5l1.6 3.3 3.6.5-2.6 2.5.6 3.6L8 9.7l-3.2 1.7.6-3.6L2.8 5.3l3.6-.5z"/>
      </svg>
      Recommendations<span class="nav-badge">Top 3</span>
    </div>
    <div class="nav-sec">Exploration</div>
    <div class="nav-item" id="nav-2" onclick="switchTab(2)">
      <svg class="nav-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
        <circle cx="8" cy="8" r="6.5"/><ellipse cx="8" cy="8" rx="3" ry="6.5"/>
        <line x1="1.5" y1="8" x2="14.5" y2="8"/>
      </svg>
      Map Intelligence
    </div>
    <div class="nav-item" id="nav-3" onclick="switchTab(3)">
      <svg class="nav-ico" viewBox="0 0 16 16" fill="currentColor">
        <rect x="1" y="3.5" width="14" height="1.5" rx=".75"/>
        <rect x="1" y="7.25" width="14" height="1.5" rx=".75"/>
        <rect x="1" y="11" width="14" height="1.5" rx=".75"/>
      </svg>
      Venue Pipeline<span class="nav-badge" id="nb-3"></span>
    </div>
    <div class="nav-item" id="nav-4" onclick="switchTab(4)">
      <svg class="nav-ico" viewBox="0 0 16 16" fill="currentColor">
        <rect x="1.5" y="7.5" width="3" height="7" rx="1"/>
        <rect x="6.5" y="4.5" width="3" height="10" rx="1"/>
        <rect x="11.5" y="1.5" width="3" height="13" rx="1"/>
      </svg>
      Market Scorecard<span class="nav-badge" id="nb-4"></span>
    </div>
    <div class="nav-sec">Focus Areas</div>
    <div class="nav-item" id="nav-5" onclick="switchTab(5)">
      <svg class="nav-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
        <circle cx="8" cy="6.5" r="3.2"/><circle cx="8" cy="6.5" r="1.2" fill="currentColor" stroke="none"/>
        <path d="M8 9.7C8 9.7 3.5 13.2 3.5 6.5a4.5 4.5 0 0 1 9 0C12.5 13.2 8 9.7 8 9.7z" opacity=".25"/>
      </svg>
      SEA Focus<span class="nav-badge" id="nb-5" style="background:rgba(167,139,250,0.12);color:#A78BFA;"></span>
    </div>
  </div>
  <div id="sb-foot">
    <div style="display:flex;align-items:center;font-size:10px;color:#4B5563;margin-bottom:4px;">
      <span class="status-dot"></span>Pipeline Active
    </div>
    <div style="font-size:9px;color:#374151;font-family:'Courier New',monospace;" id="gen-date-sb"></div>
  </div>
</nav>

<!-- ═══ MAIN WRAP ═══ -->
<div id="main-wrap">

  <!-- Top Bar -->
  <div id="top-bar">
    <div>
      <div class="tb-title" id="tb-title">Global Venue Intelligence</div>
      <div class="tb-sub" id="tb-sub">Real-time pipeline overview &mdash; Tixr expansion targeting system</div>
    </div>
    <div style="display:flex;align-items:center;gap:10px;">
      <span style="font-size:10px;color:#374151;font-family:'Courier New',monospace;" id="gen-date"></span>
      <span style="font-size:11px;color:#374151;display:flex;align-items:center;gap:5px;">
        <span style="width:5px;height:5px;border-radius:50%;background:#10B981;display:inline-block;"></span>
        <span id="hdr-stats"></span>
      </span>
      <button id="scope-btn" onclick="openScope()">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="6" cy="6" r="4.5"/><line x1="9.5" y1="9.5" x2="14" y2="14"/>
          <line x1="4" y1="6" x2="8" y2="6"/><line x1="2" y1="3.5" x2="10" y2="3.5"/>
          <line x1="3" y1="8.5" x2="9" y2="8.5"/>
        </svg>
        Data Scope
        <span id="scope-hidden-badge"></span>
      </button>
    </div>
  </div>

  <!-- TAB 0: Overview -->
  <div id="tab-0" class="tab-pane fade-in">
    <div class="kpi-grid" id="kpi-grid-ov"></div>
    <div class="charts-row">
      <div class="chart-card">
        <div class="chart-title">Venues by Region</div>
        <div style="position:relative;height:200px;"><canvas id="chart-region"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Target Tier Distribution</div>
        <div style="display:flex;gap:20px;align-items:center;">
          <div style="flex:0 0 150px;height:150px;position:relative;"><canvas id="chart-tier"></canvas></div>
          <div id="tier-dist-list" style="flex:1;"></div>
        </div>
      </div>
    </div>
    <div>
      <div class="sec-hdr">
        <div>
          <div class="sec-title">Top Priority Targets</div>
          <div class="sec-sub">Ranked by composite priority score</div>
        </div>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr style="background:rgba(255,255,255,0.02);">
            <th class="th">#</th><th class="th">Venue</th><th class="th">City</th><th class="th">Country</th>
            <th class="th">Type</th><th class="th" style="text-align:right;">Capacity</th>
            <th class="th" style="text-align:center;">VWP</th><th class="th">Exclusivity</th>
            <th class="th" style="text-align:center;">Rec Score</th><th class="th" style="text-align:center;">Tier</th>
          </tr></thead>
          <tbody id="ov-tbl-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 1: Recommendations -->
  <div id="tab-1" class="tab-pane fade-in" style="display:none;">
    <div style="margin-bottom:18px;">
      <div style="font-size:19px;font-weight:600;color:#E2E8F0;margin-bottom:5px;">Top Market Recommendations</div>
      <div style="font-size:12px;color:#4B5563;">AI-powered market prioritization based on venue pipeline quality, market fundamentals, and ROI potential</div>
    </div>
    <div id="rec-cards" style="max-width:920px;"></div>
  </div>

  <!-- TAB 2: Map Intelligence -->
  <div id="tab-2" class="tab-pane map-pane" style="display:none;">
    <div id="map-sidebar"></div>
    <div style="flex:1;position:relative;height:100%;">
      <div id="lmap" style="height:100%;width:100%;"></div>
      <!-- Score legend -->
      <div style="position:absolute;bottom:14px;left:10px;background:rgba(8,11,18,0.93);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:10px 13px;z-index:999;pointer-events:none;">
        <div style="font-size:9px;letter-spacing:0.16em;color:#374151;text-transform:uppercase;margin-bottom:7px;">Score Legend</div>
        <div style="font-size:11px;color:#4B5563;display:flex;flex-direction:column;gap:5px;">
          <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#10B981;display:inline-block;"></span>Score 60+</div>
          <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#F0A500;display:inline-block;"></span>Score 50-59</div>
          <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#38BDF8;display:inline-block;"></span>Score 30-49</div>
          <div style="display:flex;align-items:center;gap:7px;"><span style="width:8px;height:8px;border-radius:50%;background:#EF4444;display:inline-block;"></span>Score &lt;30</div>
        </div>
      </div>
      <!-- Filter + Country Search panel -->
      <div style="position:absolute;top:10px;right:10px;background:rgba(8,11,18,0.93);border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:8px 12px;z-index:999;min-width:160px;">
        <div style="font-size:9px;letter-spacing:0.13em;color:#374151;text-transform:uppercase;margin-bottom:5px;">Filter Map</div>
        <select id="map-tier" onchange="refreshMap()" class="fsel" style="font-size:11px;padding:4px 8px;width:100%;box-sizing:border-box;">
          <option value="">All Tiers</option><option value="1">Tier 1</option>
          <option value="2">Tier 2</option><option value="3">Tier 3</option><option value="12">Tier 1+2</option>
        </select>
        <div style="font-size:9px;letter-spacing:0.13em;color:#374151;text-transform:uppercase;margin:8px 0 5px;">Country Focus</div>
        <input id="map-right-search" type="text" placeholder="Search country..." oninput="filterMapCountrySearch()"
          style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);color:#E2E8F0;padding:5px 8px;border-radius:6px;font-size:11px;font-family:inherit;outline:none;width:100%;box-sizing:border-box;">
        <div id="map-right-results" style="margin-top:5px;max-height:160px;overflow-y:auto;display:none;"></div>
      </div>
      <!-- Focused country banner (centered top) -->
      <div id="map-focus-banner">
        <span class="mfb-dot"></span>
        <span class="mfb-label" id="map-focus-label">Germany</span>
        <button class="mfb-clear" onclick="clearMapFocus()">&#x2715; Clear Focus</button>
      </div>
    </div>
  </div>

  <!-- TAB 3: Venue Pipeline -->
  <div id="tab-3" class="tab-pane fade-in" style="display:none;">
    <div class="filter-bar">
      <input type="text" id="f-search" class="finp" placeholder="Search venue or city..." oninput="filterTable()">
      <select id="f-region" class="fsel" onchange="filterTable()"><option value="">All Regions</option></select>
      <select id="f-country" class="fsel" onchange="filterTable()"><option value="">All Countries</option></select>
      <select id="f-tier" class="fsel" onchange="filterTable()">
        <option value="">All Tiers</option><option value="1">Tier 1</option><option value="2">Tier 2</option>
        <option value="3">Tier 3</option><option value="4">Tier 4</option>
      </select>
      <select id="f-type" class="fsel" onchange="filterTable()"><option value="">All Types</option></select>
      <select id="f-excl" class="fsel" onchange="filterTable()">
        <option value="">All Exclusivity</option><option value="lo">Low Risk</option>
        <option value="md">Medium</option><option value="hi">High</option>
      </select>
      <select id="f-sort" class="fsel" onchange="filterTable()">
        <option value="rs">Sort: Rec Score</option><option value="ps">Sort: Priority</option>
        <option value="ex">Sort: Excl Risk</option><option value="cap">Sort: Capacity</option>
        <option value="pf">Sort: Premium Fit</option><option value="roi">Sort: ROI</option>
      </select>
      <span id="tbl-count" style="margin-left:auto;font-size:10px;color:#374151;font-family:'Courier New',monospace;"></span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr style="background:rgba(255,255,255,0.02);">
          <th class="th" style="width:28px;">#</th><th class="th">Venue</th><th class="th">City</th>
          <th class="th">Country</th><th class="th">Type</th>
          <th class="th" style="text-align:right;">Capacity</th><th class="th">Platform</th>
          <th class="th" style="text-align:center;">Excl Risk</th><th class="th" style="text-align:center;">Fit</th>
          <th class="th" style="text-align:center;">Score</th><th class="th" style="text-align:center;">ROI</th>
          <th class="th" style="text-align:center;">Tier</th>
        </tr></thead>
        <tbody id="tbl-body"></tbody>
      </table>
    </div>
    <div id="tbl-pager" style="display:flex;justify-content:center;gap:8px;margin-top:14px;"></div>
  </div>

  <!-- TAB 4: Market Scorecard -->
  <div id="tab-4" class="tab-pane fade-in" style="display:none;">
    <div class="filter-bar">
      <select id="m-region" class="fsel" onchange="renderMarkets()"><option value="">All Regions</option></select>
      <select id="m-sort" class="fsel" onchange="renderMarkets()">
        <option value="rs">Sort: Avg Score</option><option value="n">Sort: Venue Count</option>
        <option value="t12">Sort: Tier 1+2</option><option value="ms">Sort: Market Score</option>
      </select>
      <span id="mkt-count" style="margin-left:auto;font-size:10px;color:#374151;font-family:'Courier New',monospace;"></span>
    </div>
    <div id="mkt-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;"></div>
  </div>

  <!-- TAB 5: SEA Focus -->
  <div id="tab-5" class="tab-pane fade-in" style="display:none;">
    <div style="margin-bottom:18px;">
      <div style="font-size:19px;font-weight:600;color:#E2E8F0;margin-bottom:5px;">Southeast Asia Focus</div>
      <div style="font-size:12px;color:#4B5563;">Deep dive into SEA market opportunities &mdash; Singapore, Thailand, Malaysia, Indonesia &amp; more</div>
    </div>
    <div class="kpi-grid" id="sea-kpi-grid" style="margin-bottom:20px;"></div>
    <div class="charts-row" style="margin-bottom:20px;">
      <div class="chart-card">
        <div class="chart-title">SEA Venues by Country</div>
        <div style="position:relative;height:200px;"><canvas id="chart-sea-co"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">SEA Tier Distribution</div>
        <div style="display:flex;gap:20px;align-items:center;">
          <div style="flex:0 0 150px;height:150px;position:relative;"><canvas id="chart-sea-tier"></canvas></div>
          <div id="sea-tier-list" style="flex:1;"></div>
        </div>
      </div>
    </div>
    <div>
      <div class="sec-hdr">
        <div><div class="sec-title">Top SEA Venues</div><div class="sec-sub">Ranked by recommendation score</div></div>
        <div style="display:flex;gap:7px;">
          <select id="sea-co-f" class="fsel" onchange="renderSEATable()"><option value="">All Countries</option></select>
          <select id="sea-ti-f" class="fsel" onchange="renderSEATable()">
            <option value="">All Tiers</option><option value="1">Tier 1</option><option value="2">Tier 2</option>
          </select>
        </div>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr style="background:rgba(255,255,255,0.02);">
            <th class="th">#</th><th class="th">Venue</th><th class="th">City</th><th class="th">Country</th>
            <th class="th">Type</th><th class="th" style="text-align:right;">Capacity</th>
            <th class="th" style="text-align:center;">Excl Risk</th>
            <th class="th" style="text-align:center;">Score</th><th class="th" style="text-align:center;">ROI</th>
            <th class="th" style="text-align:center;">Tier</th>
          </tr></thead>
          <tbody id="sea-tbl-body"></tbody>
        </table>
      </div>
      <div id="sea-pager" style="display:flex;justify-content:center;gap:8px;margin-top:14px;"></div>
    </div>
  </div>

</div><!-- /main-wrap -->

<!-- ═══ SCOPE MODAL ═══ -->
<div id="scope-overlay" onclick="handleScopeOverlayClick(event)">
  <div id="scope-modal">
    <div class="scope-hdr">
      <div>
        <div style="font-size:16px;font-weight:600;color:#E2E8F0;margin-bottom:3px;">Data Scope</div>
        <div style="font-size:11px;color:#4B5563;">Hide regions or markets to exclude them from all charts, KPIs, tables &amp; recommendations</div>
      </div>
      <button onclick="closeScope()" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:4px;color:#4B5563;font-size:16px;cursor:pointer;padding:2px 8px;flex-shrink:0;">&times;</button>
    </div>
    <div class="scope-body">
      <!-- Live counter -->
      <div id="scope-counter">
        <div>
          <div style="font-size:13px;font-weight:600;color:#E2E8F0;" id="scope-count-text"></div>
          <div class="scope-pbar" style="width:200px;margin-top:6px;"><div class="scope-pbar-fill" id="scope-pbar-fill"></div></div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:11px;color:#4B5563;" id="scope-pct-text"></div>
          <button onclick="resetScope()" style="margin-top:6px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:4px;color:#6B7280;font-size:10px;cursor:pointer;padding:3px 9px;font-family:inherit;">Reset All</button>
        </div>
      </div>

      <!-- Regions -->
      <div style="margin-bottom:20px;">
        <div class="scope-sec-title">Regions <span style="font-style:normal;text-transform:none;letter-spacing:0;font-weight:400;color:#374151;" id="scope-r-count"></span></div>
        <div id="scope-region-pills" style="display:flex;flex-wrap:wrap;gap:8px;"></div>
      </div>

      <!-- Markets / Countries -->
      <div>
        <div class="scope-sec-title" style="margin-bottom:8px;">Markets <span style="font-style:normal;text-transform:none;letter-spacing:0;font-weight:400;color:#374151;" id="scope-c-count"></span></div>
        <input type="text" id="scope-co-search" placeholder="Search market..." oninput="filterScopeCountries()">
        <div id="scope-country-pills" style="display:flex;flex-wrap:wrap;gap:6px;max-height:260px;overflow-y:auto;padding-right:4px;"></div>
      </div>
    </div>
    <div class="scope-ftr">
      <div style="font-size:11px;color:#374151;">Click any region or market to toggle it on/off</div>
      <button onclick="closeScope()" style="background:rgba(240,165,0,0.1);border:1px solid rgba(240,165,0,0.25);color:#F0A500;padding:7px 18px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:500;font-family:inherit;">Done</button>
    </div>
  </div>
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
var CB = /*__CB__*/{};
var GEN_DATE = "__DATE__";

// ── Helpers ──
function tc(ti){return ti===1?'#10B981':ti===2?'#F0A500':ti===3?'#38BDF8':'#EF4444';}
function tl(ti){return ti===1?'Tier 1':ti===2?'Tier 2':ti===3?'Tier 3':ti===4?'Tier 4':'--';}
function tlf(ti){return ti===1?'Immediate Outreach':ti===2?'High Priority':ti===3?'Monitor':ti===4?'Low Priority':'Unscored';}
function ec(e){return e<30?'#10B981':e<60?'#F0A500':'#EF4444';}
function el(e){return e<30?'Low':e<60?'Med':'High';}
function oc(s){return s>=60?'#10B981':s>=50?'#F0A500':s>=30?'#38BDF8':'#EF4444';}
function fmt(n){return n!=null?Number(n).toLocaleString():'--';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function scBg(s){return s>=60?'rgba(16,185,129,':s>=50?'rgba(240,165,0,':s>=30?'rgba(56,189,248,':'rgba(239,68,68,';}
function r2(n){return Math.round(n*10)/10;}

// ── SEA Countries ──
var SEA_COS = ['Singapore','Thailand','Malaysia','Indonesia','Philippines','Vietnam','Myanmar','Cambodia','Laos','Brunei','Timor-Leste'];

// ── Data Scope: hidden sets ──
var hiddenR = {};
var hiddenC = {};

function getActiveVD(){
  var hr=Object.keys(hiddenR).length>0, hc=Object.keys(hiddenC).length>0;
  if(!hr&&!hc)return VD;
  return VD.filter(function(v){
    if(hr&&hiddenR[v.r])return false;
    if(hc&&hiddenC[v.co])return false;
    return true;
  });
}

function getActiveREG(){
  var aVD=getActiveVD();
  var hr=Object.keys(hiddenR).length>0,hc=Object.keys(hiddenC).length>0;
  if(!hr&&!hc)return REG;
  // Recompute from active venues
  var res={};
  aVD.forEach(function(v){
    if(!v.r)return;
    if(!res[v.r])res[v.r]={n:0,co:{},ps_sum:0,t1:0,t2:0,cnt:0};
    res[v.r].n++; res[v.r].co[v.co]=1; res[v.r].ps_sum+=(v.rs||0); res[v.r].cnt++;
    if(v.ti===1)res[v.r].t1++; if(v.ti===2)res[v.r].t2++;
  });
  Object.keys(res).forEach(function(r){
    var d=res[r];
    res[r]={n:d.n,co:Object.keys(d.co).length,ps:d.cnt?r2(d.ps_sum/d.cnt):0,t1:d.t1,t2:d.t2};
  });
  return res;
}

function getActiveMKT(){
  var hr=Object.keys(hiddenR).length>0,hc=Object.keys(hiddenC).length>0;
  if(!hr&&!hc)return MKT;
  var res={};
  Object.keys(MKT).forEach(function(co){
    var m=MKT[co];
    if(hc&&hiddenC[co])return;
    if(hr&&hiddenR[m.r])return;
    res[co]=m;
  });
  return res;
}

function computeActiveKPIs(aVD){
  var t=aVD.length,t1=0,t2=0,t3=0,t4=0,rsSum=0;
  aVD.forEach(function(v){
    if(v.ti===1)t1++;else if(v.ti===2)t2++;else if(v.ti===3)t3++;else if(v.ti===4)t4++;
    rsSum+=(v.rs||0);
  });
  var cos={},regs={};
  aVD.forEach(function(v){if(v.co)cos[v.co]=1;if(v.r)regs[v.r]=1;});
  return{total:t,t1:t1,t2:t2,t3:t3,t4:t4,avg_opp:t?r2(rsSum/t):0,
    countries:Object.keys(cos).length,regions:Object.keys(regs).length};
}

// ── JS Recommendation engine (mirrors Python logic) ──
function computeTopRecs(aVD){
  var cGroups={};
  aVD.forEach(function(v){if(!v.co)return;if(!cGroups[v.co])cGroups[v.co]=[];cGroups[v.co].push(v);});
  var ranked=[];
  Object.keys(cGroups).forEach(function(co){
    var vlist=cGroups[co];
    if(vlist.length<3)return;
    var m=MKT[co]||{};
    var n=vlist.length;
    var avgScore=vlist.reduce(function(s,v){return s+(v.rs||0);},0)/n;
    var ms=m.ms||0;
    var t1=vlist.filter(function(v){return v.ti===1;}).length;
    var t2=vlist.filter(function(v){return v.ti===2;}).length;
    var caps=vlist.filter(function(v){return v.cap>0;}).map(function(v){return v.cap;});
    var avgCap=caps.length?caps.reduce(function(s,c){return s+c;},0)/caps.length:1500;
    var avgEx=vlist.reduce(function(s,v){return s+v.ex;},0)/n;
    var avgPf=vlist.reduce(function(s,v){return s+v.pf;},0)/n;
    var avgRoi=vlist.reduce(function(s,v){return s+v.roi;},0)/n;
    var nWin=t1+t2;
    var venueAnnual=Math.max(avgCap,1500)*12*45*0.025;
    var annualRev=nWin*venueAnnual;
    var totalInvest=50000+nWin*8000;
    var roiMult=annualRev>0?r2(annualRev/Math.max(totalInvest,1)):0;
    var logRev=annualRev>0?Math.log10(Math.max(annualRev,1)):0;
    var roiFactor=Math.max(0,Math.min((logRev-5.0)/3.5,1))*100;
    var rankScore=avgScore*0.25+ms*0.20+Math.min(t1/30,1)*100*0.20+Math.min(nWin/200,1)*100*0.15+roiFactor*0.20;
    function fmtM(v){if(v>=1e6)return'$'+r2(v/1e6)+'M';if(v>=1000)return'$'+Math.round(v/1000)+'K';return'$'+Math.round(v);}
    var why=[];
    if(ms>=50)why.push('Strong market fundamentals (score: '+ms+') \u2014 high GDP & digital readiness');
    else if(ms>=30)why.push('Developing market with growth potential (score: '+ms+')');
    if(t1>0)why.push(t1+' Tier 1 venues ready for immediate sales outreach');
    if(t1+t2>=10)why.push((t1+t2)+' high-priority venues (Tier 1+2) in the pipeline');
    if(avgScore>=60)why.push('High avg recommendation score ('+r2(avgScore)+') across '+n+' venues');
    if(avgPf>=55)why.push('Strong premium fit ('+Math.round(avgPf)+'%) \u2014 aligns with Tixr positioning');
    if(avgEx<=45)why.push('Low exclusivity risk \u2014 limited platform lock-in');
    if(n>=200)why.push('Deep venue pipeline ('+n+' venues) \u2014 significant scale');
    if(annualRev>=1e6)why.push('Est. '+fmtM(annualRev)+'/yr earning potential ('+roiMult+'x ROI)');
    if(!why.length)why.push(n+' venues with avg score '+r2(avgScore));
    var risks=[];
    if(m.tp)risks.push('Incumbent platform ('+m.tp+') \u2014 requires displacement strategy');
    if(avgEx>=55)risks.push('Elevated exclusivity risk (avg '+Math.round(avgEx)+'%)');
    if(ms<40&&ms>0)risks.push('Below-average market fundamentals \u2014 may limit growth');
    if(ms===0)risks.push('No market intelligence data \u2014 fundamentals unknown');
    if(n<30)risks.push('Small pipeline ('+n+' venues) \u2014 limited scale potential');
    if(!risks.length)risks.push('No significant risks identified \u2014 strong candidate');
    ranked.push({co:co,r:m.r||'',avg:r2(avgScore),ms:ms,n:n,t1:t1,t2:t2,
      cap:Math.round(avgCap),roi:r2(avgRoi),opp:fmtM(annualRev),invest:fmtM(totalInvest),
      roix:roiMult,rank:r2(rankScore),why:why.slice(0,4),risks:risks.slice(0,3)});
  });
  ranked.sort(function(a,b){return b.rank-a.rank;});
  return ranked.slice(0,3);
}

// ── Tab info ──
var TAB_INFO=[
  ['Global Venue Intelligence','Real-time pipeline overview \u2014 Tixr expansion targeting system'],
  ['Top Market Recommendations','AI-powered market prioritization based on venue pipeline quality, market fundamentals, and ROI potential'],
  ['Map Intelligence','Geographic visualization of global venue opportunities'],
  ['Venue Pipeline','Full searchable and filterable venue database'],
  ['Market Scorecard','Country-level market analysis and comparison'],
  ['SEA Focus','Southeast Asia deep dive \u2014 Singapore, Thailand, Malaysia, Indonesia & more']
];

// ── Init header ──
(function(){
  var k=KPI;
  document.getElementById('hdr-stats').textContent=fmt(k.total)+' venues \u00b7 '+k.countries+' markets';
  document.getElementById('gen-date').textContent=GEN_DATE;
  document.getElementById('gen-date-sb').textContent=GEN_DATE;
  document.getElementById('nb-0').textContent=fmt(k.total);
  document.getElementById('nb-3').textContent=fmt(VD.length);
  document.getElementById('nb-4').textContent=Object.keys(MKT).length;
  var seaN=VD.filter(function(v){return v.r==='SEA'||SEA_COS.indexOf(v.co)>=0;}).length;
  document.getElementById('nb-5').textContent=seaN;
})();

// ── Tab switching ──
var MAP=null,MCG=null,mapInited=false,ovInited=false,seaInited=false;
var mapFocusCountry=null;
var countryBoundaryLayer=null;
var charts={};

function destroyChart(id){if(charts[id]){charts[id].destroy();delete charts[id];}}
function makeChart(id,ctx,cfg){destroyChart(id);charts[id]=new Chart(ctx,cfg);return charts[id];}

function switchTab(idx){
  for(var i=0;i<6;i++){
    var tp=document.getElementById('tab-'+i);
    if(i===idx){tp.style.display=(i===2)?'flex':'block';}else{tp.style.display='none';}
    var nav=document.getElementById('nav-'+i);
    if(nav){if(i===idx)nav.classList.add('active');else nav.classList.remove('active');}
  }
  document.getElementById('tb-title').textContent=TAB_INFO[idx][0];
  document.getElementById('tb-sub').textContent=TAB_INFO[idx][1];
  if(idx===0&&!ovInited){renderOverview();ovInited=true;}
  if(idx===1)renderRecs();
  if(idx===2){
    if(!mapInited){initMap();mapInited=true;}
    else{
      setTimeout(function(){MAP.invalidateSize();},100);
      refreshMap();
      renderMapSidebar();
    }
  }
  if(idx===3)filterTable();
  if(idx===4)renderMarkets();
  if(idx===5&&!seaInited){renderSEA();seaInited=true;}
  else if(idx===5&&seaInited){renderSEA();}
}

// ════════════════════════════════════════
// DATA SCOPE
// ════════════════════════════════════════
var rColors={EMEA:'#F0A500',APAC:'#38BDF8',LATAM:'#10B981',SEA:'#A78BFA',EMEA_Gulf:'#FB923C',EMEA_Africa:'#EF4444'};

function openScope(){
  renderScopeModal();
  document.getElementById('scope-overlay').classList.add('open');
}
function closeScope(){document.getElementById('scope-overlay').classList.remove('open');}
function handleScopeOverlayClick(e){if(e.target===document.getElementById('scope-overlay'))closeScope();}

function renderScopeModal(){
  updateScopeCounter();
  // Regions
  var rKeys=Object.keys(REG).sort();
  document.getElementById('scope-r-count').textContent='('+rKeys.length+')';
  document.getElementById('scope-region-pills').innerHTML=rKeys.map(function(r){
    var col=rColors[r]||'#6B7280';
    var on=!hiddenR[r];
    return '<div class="rpill '+(on?'on':'off')+'" style="background:'+(on?'rgba(255,255,255,0.04)':'')+'!important;border-color:'+(on?col+'55':'')+';" onclick="toggleRegion(\''+esc(r)+'\')">'+
      '<span style="width:6px;height:6px;border-radius:50%;background:'+col+';display:inline-block;flex-shrink:0;"></span>'+
      esc(r)+' <span style="opacity:0.5;font-size:10px;">'+REG[r].n.toLocaleString()+'</span></div>';
  }).join('');
  // Countries
  renderScopeCountries('');
}

function renderScopeCountries(query){
  var coKeys=Object.keys(MKT).sort();
  document.getElementById('scope-c-count').textContent='('+coKeys.length+')';
  var q=query.toLowerCase();
  if(q)coKeys=coKeys.filter(function(c){return c.toLowerCase().indexOf(q)>=0;});
  // Group by region
  var byR={};
  coKeys.forEach(function(co){var r=MKT[co].r||'Other';if(!byR[r])byR[r]=[];byR[r].push(co);});
  var html='';
  Object.keys(byR).sort().forEach(function(r){
    var col=rColors[r]||'#6B7280';
    html+='<div style="width:100%;margin-top:10px;margin-bottom:4px;font-size:9px;letter-spacing:0.12em;text-transform:uppercase;color:'+col+';">'+esc(r)+'</div>';
    byR[r].forEach(function(co){
      var on=!hiddenC[co];
      html+='<div class="cpill '+(on?'on':'off')+'" onclick="toggleCountry(\''+esc(co)+'\')">'+esc(co)+'</div>';
    });
  });
  document.getElementById('scope-country-pills').innerHTML=html;
}

function filterScopeCountries(){
  renderScopeCountries(document.getElementById('scope-co-search').value);
}

function toggleRegion(r){
  if(hiddenR[r])delete hiddenR[r];else hiddenR[r]=1;
  renderScopeModal();
  applyScope();
}

function toggleCountry(co){
  if(hiddenC[co])delete hiddenC[co];else hiddenC[co]=1;
  // Keep search state
  var q=document.getElementById('scope-co-search').value;
  updateScopeCounter();
  renderScopeCountries(q);
  // Re-render region pills in case all countries of a region are toggled
  var rKeys=Object.keys(REG).sort();
  document.getElementById('scope-region-pills').innerHTML=rKeys.map(function(r){
    var col=rColors[r]||'#6B7280';
    var on=!hiddenR[r];
    return '<div class="rpill '+(on?'on':'off')+'" style="background:'+(on?'rgba(255,255,255,0.04)':'')+'!important;border-color:'+(on?col+'55':'')+';" onclick="toggleRegion(\''+esc(r)+'\')">'+
      '<span style="width:6px;height:6px;border-radius:50%;background:'+col+';display:inline-block;flex-shrink:0;"></span>'+
      esc(r)+' <span style="opacity:0.5;font-size:10px;">'+REG[r].n.toLocaleString()+'</span></div>';
  }).join('');
  applyScope();
}

function resetScope(){
  hiddenR={};hiddenC={};
  renderScopeModal();
  applyScope();
}

function updateScopeCounter(){
  var aVD=getActiveVD();
  var total=VD.length,active=aVD.length;
  var pct=Math.round(active/total*100);
  var hidden=total-active;
  document.getElementById('scope-count-text').textContent=active.toLocaleString()+' of '+total.toLocaleString()+' venues visible';
  document.getElementById('scope-pct-text').textContent=pct+'% of data';
  document.getElementById('scope-pbar-fill').style.width=pct+'%';
  var ctr=document.getElementById('scope-counter');
  if(hidden>0){
    ctr.classList.add('warn');
    document.getElementById('scope-pbar-fill').style.background='#F0A500';
  }else{
    ctr.classList.remove('warn');
    document.getElementById('scope-pbar-fill').style.background='#10B981';
  }
}

function applyScope(){
  var aVD=getActiveVD();
  var totalHidden=VD.length-aVD.length;
  // Update scope button badge
  var badge=document.getElementById('scope-hidden-badge');
  if(totalHidden>0){
    badge.textContent=totalHidden.toLocaleString()+' hidden';
    badge.style.display='inline-block';
    document.getElementById('scope-btn').classList.add('active');
  }else{
    badge.style.display='none';
    document.getElementById('scope-btn').classList.remove('active');
  }
  // Update sidebar badges
  var ak=computeActiveKPIs(aVD);
  document.getElementById('nb-0').textContent=fmt(ak.total);
  document.getElementById('nb-3').textContent=fmt(ak.total);
  document.getElementById('nb-4').textContent=Object.keys(getActiveMKT()).length;
  var seaActive=aVD.filter(function(v){return v.r==='SEA'||SEA_COS.indexOf(v.co)>=0;});
  document.getElementById('nb-5').textContent=seaActive.length;
  // Update header stats
  document.getElementById('hdr-stats').textContent=fmt(ak.total)+' venues \u00b7 '+ak.countries+' markets';
  // Re-render active tab
  ovInited=false; seaInited=false;
  var curTab=0;
  for(var i=0;i<6;i++){if(document.getElementById('tab-'+i).style.display!=='none'){curTab=i;break;}}
  if(curTab===0){renderOverview();ovInited=true;}
  if(curTab===1)renderRecs();
  if(curTab===2&&mapInited){renderMapSidebar();refreshMap();}
  if(curTab===3)filterTable();
  if(curTab===4)renderMarkets();
  if(curTab===5){renderSEA();seaInited=true;}
}

// ════════════════════════════════════════
// TAB 0 — OVERVIEW
// ════════════════════════════════════════
function renderOverview(){
  var aVD=getActiveVD();
  var ak=computeActiveKPIs(aVD);
  var sgT2=aVD.filter(function(v){return v.co==='Singapore'&&v.ti===2;}).length;
  var kpiData=[
    {v:fmt(ak.total),l:'Venues Discovered',c:'#E2E8F0',sub:ak.total+' across '+ak.countries+' countries'},
    {v:ak.countries,l:'Countries',c:'#A78BFA',sub:ak.regions+' regions'},
    {v:'19',l:'Data Sources',c:'#38BDF8',sub:'19 APIs integrated'},
    {v:ak.t2,l:'Tier 2 Targets',c:'#F0A500',sub:'Immediate outreach'},
    {v:sgT2,l:'SEA Opportunities',c:'#A78BFA',sub:'Singapore Tier 2 venues'},
    {v:'$5/mo',l:'Pipeline Cost',c:'#10B981',sub:'~170K API calls'}
  ];
  document.getElementById('kpi-grid-ov').innerHTML=kpiData.map(function(it){
    return '<div class="kpi-card"><div class="kpi-val" style="color:'+it.c+';">'+it.v+'</div>'+
      '<div class="kpi-lbl">'+it.l+'</div><div class="kpi-sub">'+it.sub+'</div></div>';
  }).join('');

  // Region chart
  var aREG=getActiveREG();
  var rKeys=Object.keys(aREG).sort(function(a,b){return aREG[b].n-aREG[a].n;});
  destroyChart('region');
  makeChart('region',document.getElementById('chart-region').getContext('2d'),{
    type:'bar',
    data:{labels:rKeys,datasets:[{data:rKeys.map(function(r){return aREG[r].n;}),
      backgroundColor:rKeys.map(function(r){return (rColors[r]||'#6B7280')+'CC';}),
      borderWidth:0,borderRadius:4}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return ' '+c.raw.toLocaleString()+' venues';}}}},
      scales:{x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#374151',font:{size:10}},border:{display:false}},
        y:{grid:{display:false},ticks:{color:'#9CA3AF',font:{size:11}},border:{display:false}}}}
  });

  // Tier donut
  destroyChart('tier');
  makeChart('tier',document.getElementById('chart-tier').getContext('2d'),{
    type:'doughnut',
    data:{labels:['Tier 1','Tier 2','Tier 3','Tier 4'],
      datasets:[{data:[ak.t1,ak.t2,ak.t3,ak.t4],
        backgroundColor:['#10B981','#F0A500','#38BDF8','#EF4444'],borderWidth:0,hoverOffset:4}]},
    options:{cutout:'68%',plugins:{legend:{display:false},
      tooltip:{callbacks:{label:function(c){return ' '+c.label+': '+c.raw.toLocaleString();}}}}}
  });

  var tl_items=[{l:'Tier 1 \u2014 Immediate Outreach',v:ak.t1,c:'#10B981'},{l:'Tier 2 \u2014 High Priority',v:ak.t2,c:'#F0A500'},
    {l:'Tier 3 \u2014 Monitor',v:ak.t3,c:'#38BDF8'},{l:'Tier 4 \u2014 Low Priority',v:ak.t4,c:'#EF4444'}];
  var total=ak.t1+ak.t2+ak.t3+ak.t4||1;
  document.getElementById('tier-dist-list').innerHTML=tl_items.map(function(it){
    var pct=Math.round(it.v/total*100);
    return '<div class="tdist-item"><div style="flex:1;"><div style="font-size:11px;color:#9CA3AF;margin-bottom:3px;">'+it.l+'</div>'+
      '<div style="height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">'+
      '<div style="height:3px;border-radius:2px;background:'+it.c+';width:'+pct+'%;"></div></div></div>'+
      '<div style="font-size:13px;font-weight:700;font-family:\'Courier New\',monospace;color:'+it.c+';margin-left:10px;min-width:50px;text-align:right;">'+fmt(it.v)+'</div></div>';
  }).join('');

  var top=aVD.slice().sort(function(a,b){return(b.rs||0)-(a.rs||0);}).slice(0,10);
  document.getElementById('ov-tbl-body').innerHTML=top.map(function(v,i){
    var tierH=v.ti?'<span class="tb t'+v.ti+'">'+tl(v.ti)+'</span>':'<span style="color:#374151;">--</span>';
    return '<tr class="trow" onclick="showDetail('+VD.indexOf(v)+')">' +
      '<td class="td" style="color:#374151;font-family:\'Courier New\',monospace;">'+(i+1)+'</td>' +
      '<td class="td" style="font-weight:500;color:#E2E8F0;max-width:200px;overflow:hidden;text-overflow:ellipsis;">'+esc(v.n)+'</td>' +
      '<td class="td" style="color:#4B5563;">'+esc(v.c)+'</td>' +
      '<td class="td"><span style="font-size:10px;padding:2px 7px;border-radius:4px;background:rgba(255,255,255,0.05);color:#6B7280;">'+esc(v.co)+'</span></td>' +
      '<td class="td" style="color:#4B5563;font-size:11px;">'+esc(v.t)+'</td>' +
      '<td class="td" style="text-align:right;color:#4B5563;font-family:\'Courier New\',monospace;">'+(v.cap?fmt(v.cap):'--')+'</td>' +
      '<td class="td" style="text-align:center;font-family:\'Courier New\',monospace;color:'+ec(v.ex)+';">'+(100-v.ex)+'%</td>' +
      '<td class="td" style="color:#4B5563;font-size:11px;">'+(v.es||'Unknown')+'</td>' +
      '<td class="td" style="text-align:center;font-size:14px;font-weight:700;color:'+oc(v.rs)+';font-family:\'Courier New\',monospace;">'+v.rs+'</td>' +
      '<td class="td" style="text-align:center;">'+tierH+'</td></tr>';
  }).join('');
}

// ════════════════════════════════════════
// TAB 1 — RECOMMENDATIONS
// ════════════════════════════════════════
function renderRecs(){
  var activeTop=computeTopRecs(getActiveVD());
  var container=document.getElementById('rec-cards');
  if(!activeTop.length){
    container.innerHTML='<div style="color:#374151;padding:40px;text-align:center;">No recommendations available for the current data scope.</div>';
    return;
  }
  var rankColors=['#10B981','#F0A500','#38BDF8'];
  var rankLabels=['\u21911 TOP RECOMMENDATION','\u21912 STRONG OPPORTUNITY','\u21913 HIGH POTENTIAL'];
  var h='';
  activeTop.forEach(function(rec,i){
    var col=rankColors[i]||'#6B7280';
    h+='<div class="rec-card">';
    h+='<div class="rec-rank" style="background:'+col+';color:#0C0F18;">'+rankLabels[i]+'</div>';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;margin-bottom:18px;">';
    h+='<div><div style="font-size:22px;font-weight:700;color:#E2E8F0;">'+esc(rec.co)+'</div>';
    h+='<div style="font-size:12px;color:#4B5563;">'+esc(rec.r)+' \u00b7 '+fmt(rec.n)+' venues \u00b7 Market Score: '+rec.ms+'</div></div>';
    h+='<div style="text-align:center;"><div style="font-size:38px;font-weight:800;color:'+oc(rec.avg)+';font-family:\'Courier New\',monospace;line-height:1;">'+rec.avg+'</div>';
    h+='<div style="font-size:9px;color:#374151;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;">Avg Score</div></div></div>';
    h+='<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:18px;">';
    function st(l,v,c){return '<div class="rec-stat"><div class="rec-stat-val" style="color:'+c+';">'+v+'</div><div class="rec-stat-lbl">'+l+'</div></div>';}
    h+=st('Tier 1',rec.t1,'#10B981')+st('Tier 2',rec.t2,'#F0A500')+st('Avg ROI',rec.roi,oc(rec.roi))+st('Opportunity',rec.opp,'#10B981')+st('ROI',rec.roix+'x','#10B981');
    h+='</div>';
    h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:16px;">';
    h+='<div><div class="rec-section" style="color:#10B981;">Why This Location</div>';
    rec.why.forEach(function(w){h+='<div class="rec-item why-item">'+esc(w)+'</div>';});
    h+='</div><div><div class="rec-section" style="color:#F0A500;">Key Risks</div>';
    rec.risks.forEach(function(r){h+='<div class="rec-item risk-item">'+esc(r)+'</div>';});
    h+='</div></div>';
    h+='<div style="display:flex;gap:8px;">';
    h+='<button class="act-btn" onclick="goMapCountry(\''+esc(rec.co)+'\')" style="background:rgba(240,165,0,0.1);border-color:rgba(240,165,0,0.25);color:#F0A500;">Explore on Map</button>';
    h+='<button class="act-btn" onclick="goCountry(\''+esc(rec.co)+'\')" style="background:rgba(56,189,248,0.1);border-color:rgba(56,189,248,0.25);color:#38BDF8;">View Venues</button>';
    h+='<button class="act-btn" onclick="switchTab(4)" style="background:rgba(124,142,247,0.1);border-color:rgba(124,142,247,0.25);color:#7C8EF7;">Market Details</button>';
    h+='</div></div>';
  });
  container.innerHTML=h;
}

// ════════════════════════════════════════
// TAB 2 — MAP
// ════════════════════════════════════════
function initMap(){
  MAP=L.map(document.getElementById('lmap'),{zoomControl:true,attributionControl:false}).setView([20,10],2);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,subdomains:'abcd'}).addTo(MAP);
  setTimeout(function(){MAP.invalidateSize();},200);
  refreshMap();
  renderMapSidebar();
  // if a country was pre-set (navigated from another tab), draw boundary and fly to it
  if(mapFocusCountry){
    drawCountryBoundary(mapFocusCountry);
    var m=MKT[mapFocusCountry];
    if(m&&m.la&&m.lo)setTimeout(function(){MAP.flyTo([m.la,m.lo],5,{duration:1.2});},400);
  }
}

function refreshMap(){
  if(!MAP)return;
  if(MCG)MAP.removeLayer(MCG);
  MCG=L.markerClusterGroup({maxClusterRadius:50,spiderfyOnMaxZoom:true,showCoverageOnHover:false,
    iconCreateFunction:function(cluster){
      var ms=cluster.getAllChildMarkers(),total=0;
      ms.forEach(function(m){total+=(m._vscore||0);});
      var avg=Math.round(total/ms.length),bg=scBg(avg);
      return L.divIcon({html:'<div style="background:'+bg+'0.15);border-radius:50%;width:40px;height:40px;display:flex;align-items:center;justify-content:center;"><div style="background:'+bg+'0.75);width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#0C0F18;font-weight:700;font-size:11px;font-family:Courier New,monospace;">'+avg+'</div></div>',
        className:'marker-cluster-score',iconSize:L.point(40,40)});
    }
  });
  var tf=document.getElementById('map-tier').value;
  var aVD=getActiveVD();
  aVD.forEach(function(v){
    if(!v.la||!v.lo)return;
    if(tf){if(tf==='12'&&v.ti!==1&&v.ti!==2)return;if(tf!=='12'&&v.ti!==parseInt(tf))return;}
    var focused=mapFocusCountry&&v.co===mapFocusCountry;
    var dimmed=mapFocusCountry&&v.co!==mapFocusCountry;
    if(dimmed)return; // hide non-focused when a country is focused
    var r=Math.max(5,Math.min(16,v.cap?Math.sqrt(v.cap/2000)*8:5));
    var mk=L.circleMarker([v.la,v.lo],{
      radius:r,fillColor:oc(v.rs),
      color:focused?'rgba(255,255,255,0.6)':'rgba(0,0,0,0.4)',
      weight:focused?2:1.5,fillOpacity:0.9
    });
    mk._vscore=v.rs;
    var vidx=VD.indexOf(v);
    mk.on('click',function(){showDetail(vidx);});
    var tip='<strong>'+esc(v.n)+'</strong><br>'+esc(v.c)+(v.co?', '+esc(v.co):'')+'<br>'+esc(v.t)+(v.cap?' \u00b7 '+fmt(v.cap):'');
    if(v.ti)tip+='<br><span style="color:'+oc(v.rs)+';">Score: '+v.rs+'</span> \u00b7 '+tl(v.ti);
    mk.bindTooltip(tip,{className:'ttip',direction:'top',offset:[0,-(r+5)]});
    MCG.addLayer(mk);
  });
  MAP.addLayer(MCG);
  // update focus banner
  var banner=document.getElementById('map-focus-banner');
  if(mapFocusCountry){
    banner.classList.add('visible');
    document.getElementById('map-focus-label').textContent=mapFocusCountry;
  } else {
    banner.classList.remove('visible');
  }
}

function renderMapSidebar(){
  var sb=document.getElementById('map-sidebar');
  if(mapFocusCountry){
    renderCountryStatsSidebar(mapFocusCountry);
    return;
  }
  var aREG=getActiveREG();
  var h='<div style="font-size:9px;letter-spacing:0.16em;color:#374151;text-transform:uppercase;margin-bottom:8px;padding-left:2px;">Regions</div>';
  Object.keys(aREG).sort(function(a,b){return aREG[b].n-aREG[a].n;}).forEach(function(rk){
    var r=aREG[rk],col=rColors[rk]||'#6B7280';
    h+='<div class="mcard" style="margin-bottom:7px;padding:9px;" onclick="goRegion(\''+esc(rk)+'\')">';
    h+='<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">';
    h+='<span style="font-size:12px;font-weight:600;color:#E2E8F0;">'+esc(rk)+'</span>';
    h+='<span style="font-size:9px;padding:2px 5px;border-radius:3px;background:rgba(255,255,255,0.05);color:'+col+';">'+r.co+' mkts</span></div>';
    h+='<div style="font-size:10px;color:#4B5563;">'+fmt(r.n)+' venues \u00b7 Avg: '+r.ps+'</div>';
    if(r.t1||r.t2)h+='<div style="font-size:10px;margin-top:2px;"><span style="color:#10B981;">'+r.t1+' T1</span> \u00b7 <span style="color:#F0A500;">'+r.t2+' T2</span></div>';
    h+='</div>';
  });
  // Country search section
  h+='<div style="font-size:9px;letter-spacing:0.16em;color:#374151;text-transform:uppercase;margin-top:14px;margin-bottom:8px;padding-left:2px;">Focus a Country</div>';
  h+='<input id="map-co-search" type="text" placeholder="Search country..." oninput="renderMapCountryPills()" style="">';
  h+='<div id="map-co-pills" style="max-height:220px;overflow-y:auto;"></div>';
  sb.innerHTML=h;
  renderMapCountryPills();
}

function renderMapCountryPills(){
  var el=document.getElementById('map-co-pills');
  if(!el)return;
  var q=(document.getElementById('map-co-search')||{value:''}).value.toLowerCase();
  var cos=Object.keys(MKT).sort();
  if(q)cos=cos.filter(function(c){return c.toLowerCase().indexOf(q)>=0;});
  el.innerHTML=cos.map(function(co){
    return '<span class="map-co-pill" onclick="focusMapCountry(\''+esc(co)+'\')">'+esc(co)+'</span>';
  }).join('');
}

function renderCountryStatsSidebar(co){
  var sb=document.getElementById('map-sidebar');
  var st=buildCountryStats(co);
  var mkt=MKT[co]||{};
  var col=rColors[mkt.r]||'#7C8EF7';
  var total=st.n;
  var h='';
  // Back button
  h+='<div class="cs-back" onclick="clearMapFocus()">&#8592; All Countries</div>';
  // Country header
  h+='<div class="cs-name">'+esc(co)+'</div>';
  h+='<span class="cs-region" style="background:'+col+'22;color:'+col+';border:1px solid '+col+'44;">'+esc(mkt.r||'--')+'</span>';
  // KPI grid
  h+='<div class="cs-kpi-row">';
  h+='<div class="cs-kpi"><div class="cs-kpi-val" style="color:#E2E8F0;">'+fmt(total)+'</div><div class="cs-kpi-lbl">Venues</div></div>';
  h+='<div class="cs-kpi"><div class="cs-kpi-val" style="color:#C8CDD8;">'+st.avg+'</div><div class="cs-kpi-lbl">Avg Score</div></div>';
  h+='<div class="cs-kpi"><div class="cs-kpi-val" style="color:'+(mkt.ms>=60?'#10B981':mkt.ms>=40?'#F0A500':'#EF4444')+';">'+(mkt.ms||'--')+'</div><div class="cs-kpi-lbl">Mkt Score</div></div>';
  h+='<div class="cs-kpi"><div class="cs-kpi-val" style="color:#10B981;">'+st.t1+'</div><div class="cs-kpi-lbl">Tier 1</div></div>';
  h+='</div>';
  // Tier breakdown bars
  h+='<div class="cs-sec">Tier Breakdown</div>';
  var tierData=[
    {label:'Tier 1',n:st.t1,color:'#10B981'},
    {label:'Tier 2',n:st.t2,color:'#F0A500'},
    {label:'Tier 3',n:st.t3,color:'#38BDF8'},
    {label:'Tier 4',n:st.t4,color:'#EF4444'}
  ];
  tierData.forEach(function(td){
    var pct=total>0?Math.round(td.n/total*100):0;
    h+='<div class="cs-tier-row">';
    h+='<span style="font-size:10px;color:#4B5563;width:42px;flex-shrink:0;">'+td.label+'</span>';
    h+='<div class="cs-bar-bg"><div class="cs-bar-fill" style="width:'+pct+'%;background:'+td.color+';"></div></div>';
    h+='<span style="font-size:10px;color:'+td.color+';font-family:var(--mono);width:32px;text-align:right;flex-shrink:0;">'+td.n+'</span>';
    h+='</div>';
  });
  // Top venue types
  if(st.types&&st.types.length){
    h+='<div class="cs-sec">Top Venue Types</div>';
    st.types.forEach(function(tp){
      var pct=total>0?Math.round(tp.n/total*100):0;
      h+='<div style="display:flex;align-items:center;gap:5px;margin-bottom:3px;">';
      h+='<span style="font-size:10px;color:#4B5563;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+esc(tp.t)+'</span>';
      h+='<span style="font-size:10px;font-family:var(--mono);color:#6B7280;">'+tp.n+'</span>';
      h+='</div>';
    });
  }
  // Top capacity venue
  if(st.topCap&&st.topCap.n){
    h+='<div class="cs-sec">Largest Venue</div>';
    h+='<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:7px 8px;">';
    h+='<div style="font-size:11px;color:#C8CDD8;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+esc(st.topCap.n)+'</div>';
    h+='<div style="font-size:10px;color:#4B5563;margin-top:2px;">'+esc(st.topCap.c||'')+(st.topCap.cap?' \u00b7 '+fmt(st.topCap.cap)+' cap':'')+'</div>';
    h+='</div>';
  }
  // Top 5 venues by score
  h+='<div class="cs-sec">Top Venues by Score</div>';
  st.topVenues.forEach(function(v,i){
    h+='<div class="cs-venue-row">';
    h+='<span style="font-size:10px;color:#374151;font-family:var(--mono);width:14px;flex-shrink:0;">'+(i+1)+'</span>';
    h+='<span class="cs-venue-name">'+esc(v.n)+'</span>';
    h+='<span class="cs-score" style="color:'+oc(v.rs)+';">'+v.rs+'</span>';
    h+='</div>';
  });
  // Action buttons
  h+='<div style="margin-top:12px;display:flex;flex-direction:column;gap:5px;">';
  h+='<button onclick="goCountry(\''+esc(co)+'\')" style="background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.25);color:#38BDF8;padding:7px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;text-align:center;">View in Pipeline \u2192</button>';
  h+='<button onclick="goMapCountryMarket(\''+esc(co)+'\')" style="background:rgba(124,142,247,0.08);border:1px solid rgba(124,142,247,0.25);color:#7C8EF7;padding:7px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;text-align:center;">Market Scorecard \u2192</button>';
  h+='</div>';
  sb.innerHTML=h;
}

function buildCountryStats(co){
  var venues=getActiveVD().filter(function(v){return v.co===co;});
  var t1=0,t2=0,t3=0,t4=0,scoreSum=0;
  venues.forEach(function(v){
    if(v.ti===1)t1++;else if(v.ti===2)t2++;else if(v.ti===3)t3++;else if(v.ti===4)t4++;
    scoreSum+=(v.rs||0);
  });
  var avg=venues.length?Math.round(scoreSum/venues.length*10)/10:0;
  var topCap=venues.reduce(function(best,v){return(v.cap||0)>(best.cap||0)?v:best;},{cap:0});
  var topVenues=venues.slice().sort(function(a,b){return(b.rs||0)-(a.rs||0);}).slice(0,5);
  var types={};
  venues.forEach(function(v){if(v.t)types[v.t]=(types[v.t]||0)+1;});
  var sortedTypes=Object.keys(types).sort(function(a,b){return types[b]-types[a];}).slice(0,4).map(function(t){return{t:t,n:types[t]};});
  return{n:venues.length,t1:t1,t2:t2,t3:t3,t4:t4,avg:avg,topCap:topCap,topVenues:topVenues,types:sortedTypes};
}

function drawCountryBoundary(co){
  if(countryBoundaryLayer){MAP.removeLayer(countryBoundaryLayer);countryBoundaryLayer=null;}
  if(!MAP||!co||!CB[co])return;
  countryBoundaryLayer=L.geoJSON({type:'Feature',geometry:CB[co]},{
    style:{color:'#7C8EF7',weight:2.5,opacity:0.9,fillColor:'#7C8EF7',fillOpacity:0.07,dashArray:'6 4'}
  }).addTo(MAP);
}

function focusMapCountry(co){
  mapFocusCountry=co;
  var rs=document.getElementById('map-right-search');
  if(rs)rs.value='';
  var rr=document.getElementById('map-right-results');
  if(rr)rr.style.display='none';
  refreshMap();
  renderMapSidebar();
  drawCountryBoundary(co);
  var m=MKT[co];
  if(m&&m.la&&m.lo&&MAP){setTimeout(function(){MAP.flyTo([m.la,m.lo],5,{duration:1.2});},300);}
}

function clearMapFocus(){
  mapFocusCountry=null;
  if(countryBoundaryLayer&&MAP){MAP.removeLayer(countryBoundaryLayer);countryBoundaryLayer=null;}
  refreshMap();
  renderMapSidebar();
  if(MAP)setTimeout(function(){MAP.setView([20,10],2,{animate:true,duration:1.0});},100);
}

function filterMapCountrySearch(){
  var inp=document.getElementById('map-right-search');
  var res=document.getElementById('map-right-results');
  if(!inp||!res)return;
  var q=inp.value.toLowerCase().trim();
  if(!q){res.style.display='none';res.innerHTML='';return;}
  var cos=Object.keys(MKT).sort().filter(function(c){return c.toLowerCase().indexOf(q)>=0;}).slice(0,12);
  if(!cos.length){res.style.display='none';return;}
  res.style.display='block';
  res.innerHTML=cos.map(function(co){
    return '<div onclick="focusMapCountry(\''+esc(co)+'\')" style="padding:5px 6px;cursor:pointer;font-size:11px;color:#C8CDD8;border-radius:4px;transition:background 0.1s;" onmouseover="this.style.background=\'rgba(124,142,247,0.1)\'" onmouseout="this.style.background=\'\'">'+esc(co)+'</div>';
  }).join('');
}

function goMapCountryMarket(co){
  switchTab(4);
  setTimeout(function(){
    var mg=document.getElementById('m-region');
    if(mg)mg.value='';
    renderMarkets();
    // scroll to the specific country card
    setTimeout(function(){
      var cards=document.querySelectorAll('#mkt-grid .mcard');
      for(var i=0;i<cards.length;i++){
        if(cards[i].textContent.indexOf(co)>=0){cards[i].scrollIntoView({behavior:'smooth',block:'center'});cards[i].style.border='1px solid rgba(124,142,247,0.5)';setTimeout(function(c){c.style.border='';}.bind(null,cards[i]),2500);break;}
      }
    },200);
  },100);
}

// ════════════════════════════════════════
// TAB 3 — VENUE PIPELINE
// ════════════════════════════════════════
var tblPage=0,tblPS=50,tblF=[];

function filterTable(){
  var s=document.getElementById('f-search').value.toLowerCase();
  var rg=document.getElementById('f-region').value,co=document.getElementById('f-country').value;
  var ti=document.getElementById('f-tier').value,tp=document.getElementById('f-type').value;
  var ex=document.getElementById('f-excl').value,so=document.getElementById('f-sort').value;
  var aVD=getActiveVD();
  tblF=aVD.filter(function(v){
    if(s&&v.n.toLowerCase().indexOf(s)<0&&v.c.toLowerCase().indexOf(s)<0&&v.co.toLowerCase().indexOf(s)<0)return false;
    if(rg&&v.r!==rg)return false;if(co&&v.co!==co)return false;if(ti&&v.ti!==parseInt(ti))return false;
    if(tp&&v.t!==tp)return false;
    if(ex==='lo'&&v.ex>=30)return false;if(ex==='md'&&(v.ex<30||v.ex>=60))return false;if(ex==='hi'&&v.ex<60)return false;
    return true;
  });
  tblF.sort(function(a,b){
    if(so==='rs')return(b.rs||0)-(a.rs||0);if(so==='ps')return(b.ps||0)-(a.ps||0);
    if(so==='ex')return(a.ex||0)-(b.ex||0);if(so==='cap')return(b.cap||0)-(a.cap||0);
    if(so==='pf')return(b.pf||0)-(a.pf||0);if(so==='roi')return(b.roi||0)-(a.roi||0);
    return 0;
  });
  tblPage=0;renderPage();
  document.getElementById('tbl-count').textContent=tblF.length.toLocaleString()+' / '+aVD.length.toLocaleString()+' venues';
}

function renderPage(){
  var st=tblPage*tblPS,pg=tblF.slice(st,st+tblPS),tb=document.getElementById('tbl-body');
  if(!pg.length){tb.innerHTML='<tr><td colspan="12" style="text-align:center;padding:30px;color:#374151;">No venues match filters</td></tr>';document.getElementById('tbl-pager').innerHTML='';return;}
  tb.innerHTML=pg.map(function(v,i){
    var idx=st+i+1,vidx=VD.indexOf(v),ecv=ec(v.ex),ocv=oc(v.rs);
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
  var tp2=Math.ceil(tblF.length/tblPS),pager=document.getElementById('tbl-pager');
  if(tp2<=1){pager.innerHTML='';return;}
  var ph='';
  if(tblPage>0)ph+='<button class="pgbtn" onclick="tblPage=0;renderPage();">&laquo;</button>';
  if(tblPage>0)ph+='<button class="pgbtn" onclick="tblPage--;renderPage();">&lsaquo; Prev</button>';
  ph+='<span style="font-size:11px;color:#4B5563;padding:4px 8px;">'+(tblPage+1)+' / '+tp2+'</span>';
  if(tblPage<tp2-1)ph+='<button class="pgbtn" onclick="tblPage++;renderPage();">Next &rsaquo;</button>';
  if(tblPage<tp2-1)ph+='<button class="pgbtn" onclick="tblPage='+(tp2-1)+';renderPage();">&raquo;</button>';
  pager.innerHTML=ph;
}

// ════════════════════════════════════════
// TAB 4 — MARKET SCORECARD
// ════════════════════════════════════════
function renderMarkets(){
  var rg=document.getElementById('m-region').value,so=document.getElementById('m-sort').value;
  var aMKT=getActiveMKT();
  var keys=Object.keys(aMKT);
  if(rg)keys=keys.filter(function(k){return aMKT[k].r===rg;});
  keys.sort(function(a,b){
    var A=aMKT[a],B=aMKT[b];
    if(so==='rs')return B.rs-A.rs;if(so==='n')return B.n-A.n;
    if(so==='t12')return(B.t1+B.t2)-(A.t1+A.t2);if(so==='ms')return B.ms-A.ms;return 0;
  });
  document.getElementById('mkt-count').textContent=keys.length+' markets';
  function ms(l,v,c){return '<div style="text-align:center;"><div style="font-size:15px;font-weight:700;color:'+c+';font-family:\'Courier New\',monospace;">'+v+'</div><div style="font-size:8px;letter-spacing:0.1em;text-transform:uppercase;color:#374151;">'+l+'</div></div>';}
  document.getElementById('mkt-grid').innerHTML=keys.map(function(co){
    var m=aMKT[co],rc=rColors[m.r]||'#6B7280';
    return '<div class="mcard" onclick="goCountry(\''+esc(co)+'\')">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
      '<span style="font-size:14px;font-weight:600;color:#E2E8F0;">'+esc(co)+'</span>' +
      '<span style="font-size:9px;padding:2px 6px;border-radius:3px;background:rgba(255,255,255,0.05);color:'+rc+';">'+esc(m.r)+'</span></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px;">' +
      ms('Venues',m.n,'#E2E8F0')+ms('Avg Score',m.rs,oc(m.rs))+ms('Mkt Score',m.ms||'--',m.ms?oc(m.ms):'#374151')+'</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">' +
      ms('Tier 1',m.t1,'#10B981')+ms('Tier 2',m.t2,'#F0A500')+'</div>' +
      (m.tp?'<div style="font-size:10px;color:#374151;">Top platform: <span style="color:#6B7280;">'+esc(m.tp)+'</span></div>':'')+'</div>';
  }).join('');
}

// ════════════════════════════════════════
// TAB 5 — SEA FOCUS
// ════════════════════════════════════════
var seaPage=0,seaPS=50,seaF=[];

function renderSEA(){
  var aVD=getActiveVD();
  var svd=aVD.filter(function(v){return v.r==='SEA'||SEA_COS.indexOf(v.co)>=0;});
  if(!svd.length){
    document.getElementById('sea-kpi-grid').innerHTML='<div style="color:#374151;padding:20px;grid-column:1/-1;">All SEA markets are currently hidden. Use Data Scope to restore them.</div>';
    document.getElementById('sea-tbl-body').innerHTML='';
    return;
  }
  var t1=svd.filter(function(v){return v.ti===1;}).length;
  var t2=svd.filter(function(v){return v.ti===2;}).length;
  var cos={};svd.forEach(function(v){if(v.co)cos[v.co]=1;});
  var avgS=svd.length?r2(svd.reduce(function(a,v){return a+(v.rs||0);},0)/svd.length):0;
  var sgT2=svd.filter(function(v){return v.co==='Singapore'&&v.ti===2;}).length;
  document.getElementById('sea-kpi-grid').innerHTML=[
    {v:svd.length,l:'SEA Venues',c:'#A78BFA',sub:Object.keys(cos).length+' countries covered'},
    {v:t1,l:'Tier 1 Venues',c:'#10B981',sub:'Immediate outreach'},
    {v:t2,l:'Tier 2 Venues',c:'#F0A500',sub:'High priority'},
    {v:Object.keys(cos).length,l:'Countries',c:'#38BDF8',sub:'in Southeast Asia'},
    {v:avgS,l:'Avg Score',c:'#7C8EF7',sub:'across SEA pipeline'},
    {v:sgT2,l:'SG Opportunities',c:'#A78BFA',sub:'Singapore Tier 2'}
  ].map(function(it){
    return '<div class="kpi-card"><div class="kpi-val" style="color:'+it.c+';">'+it.v+'</div>'+
      '<div class="kpi-lbl">'+it.l+'</div><div class="kpi-sub">'+it.sub+'</div></div>';
  }).join('');

  // Country chart
  var coCounts={};svd.forEach(function(v){if(v.co)coCounts[v.co]=(coCounts[v.co]||0)+1;});
  var coKeys=Object.keys(coCounts).sort(function(a,b){return coCounts[b]-coCounts[a];});
  var coPal=['#A78BFA','#38BDF8','#10B981','#F0A500','#FB923C','#7C8EF7','#EF4444','#34D399','#FBBF24','#60A5FA'];
  destroyChart('sea-co');
  makeChart('sea-co',document.getElementById('chart-sea-co').getContext('2d'),{
    type:'bar',
    data:{labels:coKeys,datasets:[{data:coKeys.map(function(c){return coCounts[c];}),
      backgroundColor:coKeys.map(function(_,i){return coPal[i%coPal.length]+'CC';}),borderWidth:0,borderRadius:4}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return ' '+c.raw.toLocaleString()+' venues';}}}},
      scales:{x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#374151',font:{size:10}},border:{display:false}},
        y:{grid:{display:false},ticks:{color:'#9CA3AF',font:{size:11}},border:{display:false}}}}
  });

  var st1=t1,st2=t2,st3=svd.filter(function(v){return v.ti===3;}).length,st4=svd.filter(function(v){return v.ti===4;}).length;
  destroyChart('sea-tier');
  makeChart('sea-tier',document.getElementById('chart-sea-tier').getContext('2d'),{
    type:'doughnut',
    data:{labels:['Tier 1','Tier 2','Tier 3','Tier 4'],
      datasets:[{data:[st1,st2,st3,st4],backgroundColor:['#10B981','#F0A500','#38BDF8','#EF4444'],borderWidth:0,hoverOffset:4}]},
    options:{cutout:'68%',plugins:{legend:{display:false},
      tooltip:{callbacks:{label:function(c){return ' '+c.label+': '+c.raw.toLocaleString();}}}}}
  });

  var stot=st1+st2+st3+st4||1;
  document.getElementById('sea-tier-list').innerHTML=[
    {l:'Tier 1',v:st1,c:'#10B981'},{l:'Tier 2',v:st2,c:'#F0A500'},
    {l:'Tier 3',v:st3,c:'#38BDF8'},{l:'Tier 4',v:st4,c:'#EF4444'}
  ].map(function(it){
    var pct=Math.round(it.v/stot*100);
    return '<div class="tdist-item"><div style="flex:1;"><div style="font-size:11px;color:#9CA3AF;margin-bottom:3px;">'+it.l+'</div>'+
      '<div style="height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">'+
      '<div style="height:3px;border-radius:2px;background:'+it.c+';width:'+pct+'%;"></div></div></div>'+
      '<div style="font-size:13px;font-weight:700;font-family:\'Courier New\',monospace;color:'+it.c+';margin-left:10px;min-width:36px;text-align:right;">'+fmt(it.v)+'</div></div>';
  }).join('');

  var cf=document.getElementById('sea-co-f');
  cf.innerHTML='<option value="">All Countries</option>'+coKeys.map(function(c){return '<option value="'+esc(c)+'">'+esc(c)+'</option>';}).join('');
  seaF=svd;
  renderSEATable(svd);
}

function renderSEATable(svdParam){
  var svd=svdParam||seaF;
  var co=document.getElementById('sea-co-f').value,ti=document.getElementById('sea-ti-f').value;
  seaF=(svd||seaF).filter(function(v){
    if(co&&v.co!==co)return false;if(ti&&v.ti!==parseInt(ti))return false;return true;
  }).slice().sort(function(a,b){return(b.rs||0)-(a.rs||0);});
  seaPage=0;renderSEAPage();
}

function renderSEAPage(){
  var st=seaPage*seaPS,pg=seaF.slice(st,st+seaPS),tb=document.getElementById('sea-tbl-body');
  if(!pg.length){tb.innerHTML='<tr><td colspan="10" style="text-align:center;padding:30px;color:#374151;">No venues found</td></tr>';document.getElementById('sea-pager').innerHTML='';return;}
  tb.innerHTML=pg.map(function(v,i){
    var vidx=VD.indexOf(v),ecv=ec(v.ex),ocv=oc(v.rs);
    var tierH=v.ti?'<span class="tb t'+v.ti+'">'+tl(v.ti)+'</span>':'<span style="color:#374151;">--</span>';
    return '<tr class="trow" onclick="showDetail('+vidx+')">' +
      '<td class="td" style="color:#374151;font-family:\'Courier New\',monospace;">'+(st+i+1)+'</td>' +
      '<td class="td" style="font-weight:500;color:#E2E8F0;max-width:200px;overflow:hidden;text-overflow:ellipsis;">'+esc(v.n)+'</td>' +
      '<td class="td" style="color:#4B5563;">'+esc(v.c)+'</td>' +
      '<td class="td"><span style="font-size:10px;padding:2px 7px;border-radius:4px;background:rgba(167,139,250,0.1);color:#A78BFA;">'+esc(v.co)+'</span></td>' +
      '<td class="td" style="color:#4B5563;font-size:11px;">'+esc(v.t)+'</td>' +
      '<td class="td" style="text-align:right;color:#4B5563;font-family:\'Courier New\',monospace;">'+(v.cap?fmt(v.cap):'--')+'</td>' +
      '<td class="td" style="text-align:center;"><span style="font-family:\'Courier New\',monospace;color:'+ecv+';">'+v.ex+'</span><span style="font-size:9px;margin-left:3px;color:'+ecv+';">'+el(v.ex)+'</span></td>' +
      '<td class="td" style="text-align:center;font-size:13px;font-weight:700;color:'+ocv+';font-family:\'Courier New\',monospace;">'+v.rs+'</td>' +
      '<td class="td" style="text-align:center;font-size:12px;font-weight:600;color:'+oc(v.roi)+';font-family:\'Courier New\',monospace;">'+v.roi+'</td>' +
      '<td class="td" style="text-align:center;">'+tierH+'</td></tr>';
  }).join('');
  var tp2=Math.ceil(seaF.length/seaPS),pager=document.getElementById('sea-pager');
  if(tp2<=1){pager.innerHTML='';return;}
  var ph='';
  if(seaPage>0)ph+='<button class="pgbtn" onclick="seaPage=0;renderSEAPage();">&laquo;</button>';
  if(seaPage>0)ph+='<button class="pgbtn" onclick="seaPage--;renderSEAPage();">&lsaquo; Prev</button>';
  ph+='<span style="font-size:11px;color:#4B5563;padding:4px 8px;">'+(seaPage+1)+' / '+tp2+'</span>';
  if(seaPage<tp2-1)ph+='<button class="pgbtn" onclick="seaPage++;renderSEAPage();">Next &rsaquo;</button>';
  if(seaPage<tp2-1)ph+='<button class="pgbtn" onclick="seaPage='+(tp2-1)+';renderSEAPage();">&raquo;</button>';
  pager.innerHTML=ph;
}

// ════════════════════════════════════════
// DETAIL PANEL
// ════════════════════════════════════════
function showDetail(vidx){
  var v=VD[vidx];if(!v)return;
  var dp=document.getElementById('dpanel'),ov=document.getElementById('overlay');
  dp.classList.add('open');ov.classList.add('open');
  var ecv=ec(v.ex),ocv=oc(v.rs),h='';
  h+='<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">';
  h+='<div><div style="font-size:16px;font-weight:600;color:#E2E8F0;line-height:1.3;">'+esc(v.n)+'</div>';
  h+='<div style="font-size:11px;color:#4B5563;margin-top:3px;">'+esc(v.c)+(v.co?', '+esc(v.co):'')+' \u00b7 '+esc(v.t)+'</div></div>';
  h+='<button onclick="closeDetail()" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:4px;color:#4B5563;font-size:16px;cursor:pointer;padding:2px 8px;flex-shrink:0;">\u00d7</button></div>';
  if(v.ti)h+='<div style="margin-bottom:14px;"><span class="tb t'+v.ti+'" style="font-size:12px;padding:4px 12px;">'+tl(v.ti)+' \u2014 '+tlf(v.ti)+'</span></div>';
  h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;">';
  h+='<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.055);border-radius:8px;padding:12px;text-align:center;">';
  h+='<div style="font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:#374151;margin-bottom:3px;">Rec Score</div>';
  h+='<div style="font-size:32px;font-weight:700;color:'+ocv+';font-family:\'Courier New\',monospace;line-height:1.1;">'+v.rs+'</div>';
  h+='<div style="font-size:10px;color:#374151;">/100</div></div>';
  h+='<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.055);border-radius:8px;padding:12px;text-align:center;">';
  h+='<div style="font-size:9px;letter-spacing:0.14em;text-transform:uppercase;color:#374151;margin-bottom:3px;">ROI Index</div>';
  h+='<div style="font-size:32px;font-weight:700;color:'+oc(v.roi)+';font-family:\'Courier New\',monospace;line-height:1.1;">'+v.roi+'</div>';
  h+='<div style="font-size:10px;color:#374151;">score \u00d7 win \u00d7 fit</div></div></div>';
  function ds(l,val){return '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:6px;padding:7px 9px;"><div style="font-size:9px;letter-spacing:0.1em;text-transform:uppercase;color:#374151;margin-bottom:2px;">'+l+'</div><div style="font-size:11px;font-weight:500;color:#9CA3AF;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'+val+'</div></div>';}
  h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:14px;">';
  h+=ds('Capacity',v.cap?fmt(v.cap):'Unknown')+ds('Platform',v.vd||'Unknown')+ds('Exclusivity',v.es||'Unknown')+ds('Region',v.r||'--')+ds('Website',v.w?'Yes':'No')+ds('Priority',v.ps);
  h+='</div>';
  h+='<div style="margin-bottom:10px;"><div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px;"><span style="color:#4B5563;">Exclusivity Risk</span><span style="color:'+ecv+';">'+v.ex+' \u00b7 '+el(v.ex)+'</span></div><div class="bar"><div class="barfill" style="width:'+v.ex+'%;background:'+ecv+';"></div></div></div>';
  h+='<div style="margin-bottom:10px;"><div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px;"><span style="color:#4B5563;">Premium Fit</span><span style="color:#C8CDD8;">'+v.pf+'%</span></div><div class="bar"><div class="barfill" style="width:'+v.pf+'%;background:#7C8EF7;"></div></div></div>';
  h+='<div style="margin-bottom:14px;"><div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:4px;"><span style="color:#4B5563;">Priority Score</span><span style="color:#C8CDD8;">'+v.ps+'</span></div><div class="bar"><div class="barfill" style="width:'+Math.min(v.ps,100)+'%;background:#A78BFA;"></div></div></div>';
  h+='<div style="display:flex;gap:8px;margin-top:16px;">';
  if(v.la&&v.lo)h+='<button onclick="flyTo('+v.la+','+v.lo+')" style="flex:1;background:rgba(240,165,0,0.1);border:1px solid rgba(240,165,0,0.25);color:#F0A500;padding:8px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;">Show on Map</button>';
  h+='<button onclick="goCountry(\''+esc(v.co)+'\')" style="flex:1;background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.25);color:#38BDF8;padding:8px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;">View Market</button>';
  h+='</div>';
  dp.innerHTML=h;
}
function closeDetail(){document.getElementById('dpanel').classList.remove('open');document.getElementById('overlay').classList.remove('open');}
function flyTo(la,lo){closeDetail();switchTab(2);setTimeout(function(){MAP.flyTo([la,lo],15,{duration:1.2});},350);}
function goRegion(r){switchTab(3);document.getElementById('f-region').value=r;filterTable();}
function goMapCountry(co){mapFocusCountry=co;switchTab(2);}
function goCountry(co){switchTab(3);document.getElementById('f-country').value=co;filterTable();}

// ── Init dropdowns ──
(function(){
  var regions=Object.keys(REG).sort(),countries=Object.keys(MKT).sort(),types=[],seen={};
  VD.forEach(function(v){if(v.t&&!seen[v.t]){seen[v.t]=1;types.push(v.t);}});types.sort();
  var ro=regions.map(function(r){return '<option value="'+esc(r)+'">'+esc(r)+'</option>';}).join('');
  document.getElementById('f-region').innerHTML='<option value="">All Regions</option>'+ro;
  document.getElementById('m-region').innerHTML='<option value="">All Regions</option>'+ro;
  var co=countries.map(function(c){return '<option value="'+esc(c)+'">'+esc(c)+'</option>';}).join('');
  document.getElementById('f-country').innerHTML='<option value="">All Countries</option>'+co;
  var to=types.map(function(t){return '<option value="'+esc(t)+'">'+esc(t)+'</option>';}).join('');
  document.getElementById('f-type').innerHTML='<option value="">All Types</option>'+to;
})();

// ── Initial render ──
renderOverview();ovInited=true;
</script>
</body>
</html>'''


def prepare_country_boundaries(market_countries, output_dir):
    """
    Download simplified country boundary polygons at build time and embed them.
    Uses Natural Earth 110m (low-res but small) GeoJSON. Results are cached locally.
    """
    import urllib.request

    cache_path = os.path.join(output_dir, 'country_boundaries_cache.json')

    # Load from local cache if all countries are present
    if os.path.exists(cache_path):
        with open(cache_path, encoding='utf-8') as f:
            cached = json.load(f)
        if all(c in cached for c in market_countries):
            print(f"  Loaded {len(cached)} country boundaries from cache")
            return cached
    else:
        cached = {}

    # Low-resolution Natural Earth countries GeoJSON (~500 KB download)
    url = ('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/'
           'master/geojson/ne_110m_admin_0_countries.geojson')
    print("  Downloading country boundaries (one-time)...")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TixrDashboard/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            world = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"  Warning: Could not download country boundaries: {e}")
        return cached

    # Name aliases: our dataset names → Natural Earth ADMIN names
    aliases = {
        "People's Republic of China": "China",
        "South Korea": "Republic of Korea",
        "North Korea": "Dem. Rep. Korea",
        "Czech Republic": "Czechia",
        "Republic of Ireland": "Ireland",
        "Bosnia": "Bosnia and Herz.",
        "UAE": "United Arab Emirates",
        "UK": "United Kingdom",
        "USA": "United States of America",
        "Russia": "Russia",
        "Taiwan": "Taiwan",
        "Hong Kong": "Hong Kong S.A.R.",
        "Macau": "Macao S.A.R",
        "Vietnam": "Vietnam",
        "Ivory Coast": "Côte d'Ivoire",
        "Congo": "Congo",
        "DR Congo": "Dem. Rep. Congo",
    }

    def round_coords(c, p=1):
        """Recursively round all coordinate values to p decimal places."""
        if isinstance(c[0], (int, float)):
            return [round(c[0], p), round(c[1], p)]
        return [round_coords(x, p) for x in c]

    # Build lookup: admin_name_lower → feature
    feat_lookup = {}
    for feat in world.get('features', []):
        admin = feat['properties'].get('ADMIN') or feat['properties'].get('NAME', '')
        if admin:
            feat_lookup[admin.lower()] = feat

    result = dict(cached)
    matched, missing = 0, []
    for co in market_countries:
        if co in result:
            matched += 1
            continue
        # Try direct match, then alias, then partial
        lookup_name = aliases.get(co, co)
        feat = (feat_lookup.get(lookup_name.lower()) or
                feat_lookup.get(co.lower()))
        if not feat:
            # Partial match fallback
            co_l = co.lower()
            for k, f in feat_lookup.items():
                if co_l in k or k in co_l:
                    feat = f
                    break
        if feat:
            geom = feat['geometry']
            result[co] = {'type': geom['type'],
                          'coordinates': round_coords(geom['coordinates'], 1)}
            matched += 1
        else:
            missing.append(co)

    print(f"  Boundaries matched: {matched}/{len(market_countries)}"
          + (f"  (no geometry for: {', '.join(missing[:5])})" if missing else ""))

    # Cache for future runs
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, separators=(',', ':'))
    except Exception:
        pass

    return result


def generate_html(venues_json, markets_json, regions_json, kpis_json, toprecs_json, cb_json, generated_at):
    """Build the complete HTML by replacing placeholders in the template."""
    html = HTML_TEMPLATE
    html = html.replace('/*__VENUES__*/[]', venues_json)
    html = html.replace('/*__MARKETS__*/{}', markets_json)
    html = html.replace('/*__REGIONS__*/{}', regions_json)
    html = html.replace('/*__KPI__*/{}', kpis_json)
    html = html.replace('/*__CB__*/{}', cb_json)
    html = html.replace('__DATE__', generated_at)
    return html


def main():
    parser = argparse.ArgumentParser(description='Generate Tixr dashboard')
    parser.add_argument('--output-dir', type=str, default='output')
    parser.add_argument('--output', type=str, default='tixr_dashboard.html')
    args = parser.parse_args()

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output_dir)

    df, market_df, source_path = load_data(output_dir)

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

    print("Preparing country boundaries...")
    market_countries = list(markets.keys())
    boundaries = prepare_country_boundaries(market_countries, output_dir)

    venues_json = json.dumps(venues, separators=(',', ':'))
    markets_json = json.dumps(markets, separators=(',', ':'))
    regions_json = json.dumps(regions, separators=(',', ':'))
    kpis_json = json.dumps(kpis, separators=(',', ':'))
    toprecs_json = json.dumps(top_recs, separators=(',', ':'))
    cb_json = json.dumps(boundaries, separators=(',', ':'))

    generated_at = datetime.now().strftime('%b %d %Y %H:%M')

    print("\nGenerating dashboard...")
    html = generate_html(venues_json, markets_json, regions_json, kpis_json, toprecs_json, cb_json, generated_at)

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

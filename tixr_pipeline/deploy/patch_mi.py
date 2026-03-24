import re, sys

fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add market-intelligence.css link after existing style close tag
html = html.replace(
    '</style>',
    '</style>\n<link rel="stylesheet" href="market-intelligence.css">',
    1
)

# 2. Add Market Intelligence tab button
html = html.replace(
    '<button class="tab-btn" id="tab-btn-3" onclick="switchTab(3)">Market Scorecard</button>\n</div>',
    '<button class="tab-btn" id="tab-btn-3" onclick="switchTab(3)">Market Scorecard</button>\n  <button class="tab-btn" id="tab-btn-4" onclick="switchTab(4)">Market Intelligence</button>\n</div>'
)

# 3. Find the end of tab-3 div and add tab-4 HTML before the overlay
tab4_html = '''
<!-- Market Intelligence Tab -->
<div id="tab-4" style="display:none;padding:24px 20px;background:#080B12;min-height:calc(100vh - 170px);">
  <div style="margin-bottom:6px;">
    <div style="font-size:20px;font-weight:600;color:#E2E8F0;margin-bottom:4px;">Market Intelligence</div>
    <div style="font-size:12px;color:#4B5563;margin-bottom:16px;">Comprehensive economic &amp; venue data across all target markets &mdash; powered by World Bank, Wikidata &amp; OSM intelligence</div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap;align-items:center;">
    <select id="mi-region" class="fsel" onchange="renderMI()"><option value="">All Regions</option></select>
    <select id="mi-metric" class="fsel" onchange="renderMI()">
      <option value="gdp">GDP per Capita</option><option value="internet">Internet Penetration</option><option value="mobile">Mobile Subscriptions</option><option value="tourism">Tourism Arrivals</option><option value="venues">Venue Count</option>
    </select>
    <span id="mi-count" style="margin-left:auto;font-size:10px;color:#374141;font-family:'Courier New',monospace;"></span>
  </div>
  <div id="mi-hero-bar"></div>
  <div class="mi-chart-row"><div class="mi-chart-box"><canvas id="mi-chart-gdp"></canvas></div><div class="mi-chart-box"><canvas id="mi-chart-venue"></canvas></div></div>
  <div class="mi-chart-row"><div class="mi-chart-box"><canvas id="mi-chart-tier"></canvas></div><div class="mi-chart-box"><canvas id="mi-chart-digital"></canvas></div></div>
  <div class="mi-section">
    <div class="mi-stitle">Country Deep Dive</div>
    <div class="mi-sdesc">Complete market intelligence for all tracked countries &mdash; click any row to view venues</div>
    <div style="border:1px solid rgba(255,255,255,0.06);border-radius:10px;overflow-x:auto;"><table class="mi-tbl"><thead><tr>
      <th>Country</th><th>Region</th><th>Venues</th><th>Tier 1</th><th>Tier 2</th><th>Avg Score</th><th>GDP/Cap</th><th>Internet %</th><th>Mobile/100</th><th>Tourism</th><th>Mkt Score</th>
    </tr></thead><tbody id="mi-tbody"></tbody></table></div>
  </div>
</div>
'''
# Insert tab-4 before the detail panel overlay
html = html.replace(
    '<div id="overlay"',
    tab4_html + '\n<div id="overlay"'
)

# 4. Add Chart.js CDN before leaflet
html = html.replace(
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>',
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>\n<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
)

# 5. Update switchTab to handle 5 tabs and trigger renderMI()
old_switch = '''function switchTab(n){
  for(var i=0;i<4;i++){
    document.getElementById('tab-'+i).style.display=i===n?'block':'none';
    document.getElementById('tab-btn-'+i).classList.toggle('active',i===n);
  }
  if(n===1)setTimeout(function(){MAP.invalidateSize();},200);
}'''
new_switch = '''function switchTab(n){
  for(var i=0;i<5;i++){
    document.getElementById('tab-'+i).style.display=i===n?'block':'none';
    document.getElementById('tab-btn-'+i).classList.toggle('active',i===n);
  }
  if(n===1)setTimeout(function(){MAP.invalidateSize();},200);
  if(n===4)renderMI();
}'''
html = html.replace(old_switch, new_switch)

# 6. Add market-intelligence.js before closing </body>
html = html.replace(
    '</body>',
    '<script src="market-intelligence.js"></script>\n</body>'
)

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(html)

print("Done! index.html patched successfully.")

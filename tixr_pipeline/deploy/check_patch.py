fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

checks = {
    'tab-btn-4': 'tab-btn-4' in c,
    'market-intelligence.js': 'market-intelligence.js' in c,
    'market-intelligence.css': 'market-intelligence.css' in c,
    'Chart.js CDN': 'Chart.js' in c or 'chart.umd' in c,
    'tab-4 div': 'id="tab-4"' in c,
    'loop i<5': 'i<5' in c,
    'loop i<4': 'i<4' in c,
    'renderMI in html': 'renderMI' in c,
}
for k,v in checks.items():
    print(f'{k}: {v}')

# Find switchTab function
import re
m = re.search(r'function switchTab\(n\)\{[^}]+\}', c)
if m:
    print('\nswitchTab function:')
    print(m.group(0))
else:
    print('\nCould not find switchTab function with regex')
    # Try to find it by index
    idx = c.find('switchTab')
    if idx >= 0:
        print(f'Found switchTab at index {idx}')
        print(c[idx:idx+300])

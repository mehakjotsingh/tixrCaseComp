fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

out = []
out.append(f'tab-btn-4: {"tab-btn-4" in c}')
out.append(f'market-intelligence.js: {"market-intelligence.js" in c}')
out.append(f'market-intelligence.css: {"market-intelligence.css" in c}')
out.append(f'chart.umd: {"chart.umd" in c}')
out.append(f'tab-4 div: {"""id="tab-4\"""" in c}')
out.append(f'loop i<5: {"i<5" in c}')
out.append(f'loop i<4: {"i<4" in c}')
out.append(f'renderMI in html: {"renderMI" in c}')
out.append(f'mi-hero-bar: {"mi-hero-bar" in c}')

import re
m = re.search(r'function switchTab\(n\)\{.*?\n\}', c, re.DOTALL)
if m:
    out.append(f'\nswitchTab:\n{m.group(0)}')
else:
    idx = c.find('switchTab')
    if idx >= 0:
        out.append(f'\nswitchTab context:\n{c[idx:idx+400]}')
    else:
        out.append('\nswitchTab NOT found')

with open('diag_output.txt', 'w') as f:
    f.write('\n'.join(out))
print('Written to diag_output.txt')

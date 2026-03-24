import json, re

fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

# ── 1. Fix switchTab to properly call renderMI() ──
# Find the switchTab function and replace it entirely
# The function pattern: function switchTab(n){ ... }
# It should be a self-contained function

# First, let's find it properly
idx = c.find('function switchTab(n){')
if idx < 0:
    print('ERROR: switchTab not found')
else:
    # Find the matching closing brace
    brace_count = 0
    start = idx
    i = idx
    while i < len(c):
        if c[i] == '{':
            brace_count += 1
        elif c[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break
        i += 1
    
    old_func = c[start:end]
    print(f'Found switchTab: {repr(old_func[:200])}...')
    
    new_func = '''function switchTab(n){
  for(var i=0;i<5;i++){
    document.getElementById('tab-'+i).style.display=i===n?'block':'none';
    document.getElementById('tab-btn-'+i).classList.toggle('active',i===n);
  }
  if(n===1)setTimeout(function(){MAP.invalidateSize();},200);
  if(n===4){setTimeout(function(){renderMI();},100);}
}'''
    c = c[:start] + new_func + c[end:]
    print('Replaced switchTab function')

# ── 2. Remove "United Kingdom" and "People's Republic of China" from VD ──
# Find the VD array
vd_start = c.find('var VD = [')
if vd_start < 0:
    print('ERROR: VD not found')
else:
    vd_end = c.find('];', vd_start) + 2
    vd_str = c[vd_start+len('var VD = '):vd_end-1]  # just the array part
    
    try:
        vd = json.loads(vd_str)
        orig_count = len(vd)
        # Remove UK and People's Republic of China
        vd = [v for v in vd if v.get('co') not in ('United Kingdom', "People's Republic of China")]
        new_count = len(vd)
        print(f'VD: removed {orig_count - new_count} venues (UK + PRC). {new_count} remaining.')
        
        new_vd_str = 'var VD = ' + json.dumps(vd, ensure_ascii=False) + ';'
        c = c[:vd_start] + new_vd_str + c[vd_end:]
    except json.JSONDecodeError as e:
        print(f'JSON parse error: {e}')

# ── 3. Remove from MKT object ──
# MKT is built from VD data, need to find and update it
mkt_start = c.find('var MKT={')
if mkt_start < 0:
    mkt_start = c.find('var MKT = {')
if mkt_start < 0:
    print('WARNING: MKT object not found, will be recomputed from VD')
else:
    # Find matching brace
    brace_count = 0
    i = c.index('{', mkt_start)
    while i < len(c):
        if c[i] == '{':
            brace_count += 1
        elif c[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                mkt_end = i + 2  # include };
                break
        i += 1
    
    mkt_str = c[c.index('{', mkt_start):mkt_end-1]
    try:
        mkt = json.loads(mkt_str)
        for key in ['United Kingdom', "People's Republic of China"]:
            if key in mkt:
                del mkt[key]
                print(f'Removed {key} from MKT')
        new_mkt_str = 'var MKT=' + json.dumps(mkt, ensure_ascii=False) + ';'
        c = c[:mkt_start] + new_mkt_str + c[mkt_end:]
    except json.JSONDecodeError as e:
        print(f'MKT JSON parse error: {e}')

# ── 4. Remove from REG counts if needed ──
# REG just has venue counts per region, it will still work

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(c)

print('\nAll fixes applied to index.html')

# ── 5. Also remove UK from market-intelligence.js WB_DATA ──
mi_path = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\market-intelligence.js'
with open(mi_path, 'r', encoding='utf-8') as f:
    mi = f.read()

# Remove the UK line from WB_DATA
mi = mi.replace('  "United Kingdom":{gdp:49945,internet:96.3,mobile:122.8,tourism:11101000,r:"EMEA"},\n', '')
print('Removed UK from WB_DATA in market-intelligence.js')

with open(mi_path, 'w', encoding='utf-8') as f:
    f.write(mi)

print('Done!')

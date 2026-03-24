fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

# Fix 1: Update switchTab loop from i<4 to i<5
# The function is on one line or uses \r\n
import re

# Find and replace the switchTab function - handle both \r\n and \n
old = 'for(var i=0;i<4;i++){'
new = 'for(var i=0;i<5;i++){'
if old in c:
    c = c.replace(old, new, 1)
    print('Fixed loop to i<5')
else:
    print('ERROR: Could not find loop pattern')

# Fix 2: Add renderMI() call after MAP invalidateSize
# Find: if(n===1)setTimeout(function(){MAP.invalidateSize();},200);
# Add after: if(n===4)renderMI();
old_map = "if(n===1)setTimeout(function(){MAP.invalidateSize();},200);"
new_map = "if(n===1)setTimeout(function(){MAP.invalidateSize();},200);\n  if(n===4)renderMI();"

# But need to handle \r\n
if old_map in c:
    c = c.replace(old_map, new_map, 1)
    print('Added renderMI() call')
else:
    # Try with \r\n aware approach - just add it after
    old_map2 = "if(n===1)setTimeout(function(){MAP.invalidateSize();},200);\r\n}"
    new_map2 = "if(n===1)setTimeout(function(){MAP.invalidateSize();},200);\r\n  if(n===4)renderMI();\r\n}"
    if old_map2 in c:
        c = c.replace(old_map2, new_map2, 1)
        print('Added renderMI() call (\\r\\n variant)')
    else:
        print('WARNING: Could not add renderMI() - trying fallback')
        # Fallback: just check if renderMI call is already there via the JS file
        if 'if(n===4)renderMI()' not in c:
            # Insert right after the MAP line
            idx = c.find('MAP.invalidateSize();},200);')
            if idx > 0:
                end = idx + len('MAP.invalidateSize();},200);')
                c = c[:end] + '\n  if(n===4)renderMI();' + c[end:]
                print('Added renderMI() via fallback')

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(c)

# Verify
with open(fpath, 'r', encoding='utf-8') as f:
    v = f.read()
print(f'\nVerification:')
print(f'  i<5: {"i<5" in v}')
print(f'  renderMI in switchTab area: {"if(n===4)renderMI()" in v}')

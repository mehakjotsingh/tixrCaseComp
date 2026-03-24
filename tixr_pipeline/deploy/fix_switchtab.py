fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

# The current switchTab function ends with:
#   if(idx===3)renderMarkets();
# }
# We need to add: if(idx===4){setTimeout(function(){renderMI();},150);}

old = "if(idx===3)renderMarkets();\r\n}"
new = "if(idx===3)renderMarkets();\r\n  if(idx===4){setTimeout(function(){renderMI();},150);}\r\n}"

if old in c:
    c = c.replace(old, new, 1)
    print('Added renderMI() call to switchTab(idx)')
else:
    # Try without \r
    old2 = "if(idx===3)renderMarkets();\n}"
    new2 = "if(idx===3)renderMarkets();\n  if(idx===4){setTimeout(function(){renderMI();},150);}\n}"
    if old2 in c:
        c = c.replace(old2, new2, 1)
        print('Added renderMI() call (\\n variant)')
    else:
        print('ERROR: Could not find insertion point')
        # Last resort: just add after the renderMarkets line
        idx = c.find('if(idx===3)renderMarkets();')
        if idx >= 0:
            end = idx + len('if(idx===3)renderMarkets();')
            c = c[:end] + '\n  if(idx===4){setTimeout(function(){renderMI();},150);}' + c[end:]
            print('Added renderMI() via fallback')

# Also clean up the orphaned renderMI call from old dead code
# "if(n===4)renderMI();" is sitting in dead code
orphan = '  if(n===4)renderMI();\n'
if orphan in c:
    c = c.replace(orphan, '', 1)
    print('Cleaned up orphaned renderMI call')

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(c)

# Verify
with open(fpath, 'r', encoding='utf-8') as f:
    v = f.read()
print(f'\nVerification:')
print(f'  "idx===4" in file: {"idx===4" in v}')
print(f'  "renderMI" count: {v.count("renderMI")}')

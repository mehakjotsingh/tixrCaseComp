fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

# Find switchTab in various forms
for pattern in ['function switchTab(n){', 'function switchTab(n)\r\n{', 'function switchTab(n) {']:
    idx = c.find(pattern)
    if idx >= 0:
        print(f'Found at idx {idx} with pattern: {repr(pattern)}')
        print(f'Context: {repr(c[idx:idx+400])}')
        break
else:
    # Search broadly
    idx = c.find('switchTab')
    while idx >= 0:
        # Check if this is the function definition
        start = max(0, idx-20)
        context = c[start:idx+300]
        if 'function' in context[:30]:
            print(f'Found function def near idx {idx}')
            print(f'Context: {repr(context)}')
            break
        idx = c.find('switchTab', idx+1)
    else:
        print('switchTab NOT found anywhere as function def')
        # Let's find ALL occurrences
        idx = 0
        count = 0
        while True:
            idx = c.find('switchTab', idx)
            if idx < 0:
                break
            print(f'  occurrence at {idx}: {repr(c[max(0,idx-10):idx+50])}')
            count += 1
            idx += 1
        print(f'Total occurrences: {count}')

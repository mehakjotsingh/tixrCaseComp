fpath = r'c:\Users\ariha\Documents\tixrCaseComp\tixr_pipeline\deploy\index.html'
with open(fpath, 'r', encoding='utf-8') as f:
    c = f.read()

with open('diag2.txt', 'w', encoding='utf-8') as out:
    # Find switchTab
    idx = c.find('switchTab')
    while idx >= 0:
        start = max(0, idx-30)
        context = c[start:idx+200]
        if 'function' in c[max(0,idx-30):idx]:
            out.write(f'=== FUNCTION DEF at {idx} ===\n')
            # Find from 'function' keyword
            fstart = c.rfind('function', max(0,idx-30), idx)
            # Find end - count braces
            brace = 0
            end = fstart
            started = False
            for j in range(fstart, min(len(c), fstart+2000)):
                if c[j] == '{':
                    brace += 1
                    started = True
                elif c[j] == '}':
                    brace -= 1
                    if started and brace == 0:
                        end = j + 1
                        break
            out.write(c[fstart:end] + '\n')
            out.write(f'=== END ===\n\n')
        idx = c.find('switchTab', idx+1)
    
    # Also check if renderMI call exists near switchTab
    idx = c.find('renderMI')
    count = 0
    while idx >= 0:
        out.write(f'renderMI at {idx}: {repr(c[max(0,idx-50):idx+50])}\n')
        count += 1
        idx = c.find('renderMI', idx+1)
    out.write(f'\nTotal renderMI occurrences in index.html: {count}\n')

print('Written to diag2.txt')

import sys, re
sys.stdout.reconfigure(encoding='utf-8')

for path in [r'c:\Users\Erkan\Desktop\Yeni klasör\XAUUSD_ALGO_STRATEJILER.HTML', r'c:\Users\Erkan\Desktop\Yeni klasör\FOREX_ALGO_STRATEJILER.HTML']:
    print('='*80)
    print('DOSYA:', path)
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    
    # regex for groups
    groups = re.findall(r"name:\s*'([^']+)',\s*items:\s*\[(.*?)\]\s*\}", text, re.DOTALL)
    for gname, items_str in groups:
        raw_items = re.findall(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"', items_str)
        if not raw_items:
            raw_items = re.findall(r"\[\s*'([^']+)'\s*,\s*'([^']+)'", items_str)
        print(f"\n--- GRUP: {gname} ({len(raw_items)} oge) ---")
        for name, desc in raw_items:
            print(f"  * {name}")
            print(f"    Aciklama: {desc}")

import sys, re
sys.stdout.reconfigure(encoding='utf-8')

with open(r'c:\Users\Erkan\Desktop\Yeni klasör\XAUUSD_ALGO_STRATEJILER.HTML', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

groups = re.findall(r"name:\s*'([^']+)',\s*items:\s*\[(.*?)\]\s*\}", text, re.DOTALL)
print("=== XAUUSD STRATEGY GROUPS ===")
for gname, items_str in groups:
    if any(k in gname.lower() for k in ['altına özgü', 'gösterge kombinasyonları']):
        raw_items = re.findall(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"', items_str)
        if not raw_items:
            raw_items = re.findall(r"\[\s*'([^']+)'\s*,\s*'([^']+)'", items_str)
        print(f"\n=== {gname} ({len(raw_items)} oge) ===")
        for name, desc in raw_items:
            print(f"  * {name}")
            print(f"    {desc}\n")

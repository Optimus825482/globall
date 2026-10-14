# -*- coding: utf-8 -*-
"""MT5 ReportHistory HTML (UTF-16) → kapanan pozisyon tablosunu çıkar ve analiz et.

Kullanım: python _analyze_mt5_report.py <rapor.html>
Çıktı bilinçli olarak ASCII-güvenli (terminal kodlaması bozmasın).
"""
import sys
import re
import html as htmllib
from collections import Counter, defaultdict

SRC = sys.argv[1]
raw = open(SRC, "rb").read()
txt = raw.decode("utf-16")

rows = re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S)


def cells(row_html):
    out = []
    for m in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        out.append(htmllib.unescape(t).replace("\xa0", " ").strip())
    return out


# Tablo başlıklarını bul: MT5 yorum biçimi "Pozisyonlar" / "Emirler" / "İşlemler"
headers = []
for r in rows:
    c = cells(r)
    joined = " ".join(c)
    if "Pozisyon" in joined or "Emirler" in joined:
        headers.append((joined[:80], len(c)))

# Kolon başlık satırını bul: "Time","Position","Symbol","Type","Volume","Price","S/L","T/P","Time","Price","Commission","Swap","Profit"
col_rows = [r for r in rows if "Symbol" in " ".join(cells(r)) and "Volume" in " ".join(cells(r))]
print("=== KOLON BASLIK SATIRLARI ===")
for r in col_rows[:4]:
    c = cells(r)
    print(len(c), [x for x in c])

# Kapanan pozisyon satırları: ilk hücre tarih (2026.10.14), ikinci sayısal ID (>=8 hane)
DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}$")
pos_rows = []
for r in rows:
    c = cells(r)
    if len(c) >= 13 and DATE.match(c[0]) and c[2].isalpha():
        pos_rows.append(c)

print()
print("=== KAPANAN POZISYON SAYISI ===", len(pos_rows))
if pos_rows:
    print("ilk satir kolon sayisi:", len(pos_rows[0]))
    print("ORNEK:")
    for x in pos_rows[0]:
        print("   ", x)

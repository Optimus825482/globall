import csv
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\scalperagent_global\kural_vs_llm_karsilastirma_2026-09-29.csv', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f, delimiter=';'))

print(f"Toplam İşlem: {len(rows)}")

pnls = [float(r['Net PnL (TRY)'].replace(',', '.')) for r in rows if r['Net PnL (TRY)']]
pnl_pcts = [float(r['Net PnL (%)'].replace('%', '').replace(',', '.')) for r in rows if r['Net PnL (%)']]
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p <= 0]

print(f"Toplam Net PnL: {sum(pnls):.2f} TRY")
print(f"Genel Kazanma Oranı: %{len(wins)/len(pnls)*100:.1f} ({len(wins)} Win / {len(losses)} Loss)")
print(f"Ortalama Kâr: +{sum(wins)/len(wins):.2f} TRY" if wins else "Ort Kâr: 0")
print(f"Ortalama Zarar: {sum(losses)/len(losses):.2f} TRY" if losses else "Ort Zarar: 0")

from collections import Counter

print("\n--- ÇIKIŞ NEDENLERİ VE KÂRLILIK ---")
reasons = Counter(r['Çıkış Nedeni'] for r in rows)
for reason, count in reasons.most_common():
    sub_pnl = sum(float(r['Net PnL (TRY)'].replace(',', '.')) for r in rows if r['Çıkış Nedeni'] == reason)
    sub_wins = sum(1 for r in rows if r['Çıkış Nedeni'] == reason and float(r['Net PnL (TRY)'].replace(',', '.')) > 0)
    print(f"  {reason:15}: {count:2} adet | PnL: {sub_pnl:8.2f} TRY | Win Rate: %{sub_wins/count*100:5.1f}")

print("\n--- KARŞILAŞTIRMA SONUÇLARI ---")
comp_results = Counter(r['Karşılaştırma Sonucu'] for r in rows)
for cr, count in comp_results.most_common():
    cr_rows = [r for r in rows if r['Karşılaştırma Sonucu'] == cr]
    cr_pnls = [float(r['Net PnL (TRY)'].replace(',', '.')) for r in cr_rows]
    print(f"  {cr:25}: {count:2} adet | Toplam PnL: {sum(cr_pnls):8.2f} TRY")

# Detaylı İnceleme: FAKE kararı verilenler
fake_rows = [r for r in rows if r['LLM Kararı'] == 'FAKE']
fake_loss = [r for r in fake_rows if float(r['Net PnL (TRY)'].replace(',', '.')) <= 0]
fake_win = [r for r in fake_rows if float(r['Net PnL (TRY)'].replace(',', '.')) > 0]
saved_amount = sum(float(r['Net PnL (TRY)'].replace(',', '.')) for r in fake_loss)
missed_amount = sum(float(r['Net PnL (TRY)'].replace(',', '.')) for r in fake_win)

print("\n--- 🛡️ FAKE (TUZAK) KARARI ANALİZİ ---")
print(f"Toplam FAKE Kararı: {len(fake_rows)}")
print(f"  -> Gerçekten Zarar Edenler (🛡️ Zarardan Korudu): {len(fake_loss)} adet | Önlenen Zarar: {saved_amount:.2f} TRY")
print(f"  -> Kâr Edenler (⚠️ Fırsat Kaçtı): {len(fake_win)} adet | Kaçan Kâr: +{missed_amount:.2f} TRY")
print(f"  -> Net Koruma Etkisi (Zarar Önleme - Kaçan Kâr): {abs(saved_amount) - missed_amount:.2f} TRY NET KAZANÇ SAĞLADI!")

# Detaylı İnceleme: DEVAM kararı verilenler
devam_rows = [r for r in rows if r['LLM Kararı'] == 'DEVAM']
devam_win = [r for r in devam_rows if float(r['Net PnL (TRY)'].replace(',', '.')) > 0]
devam_loss = [r for r in devam_rows if float(r['Net PnL (TRY)'].replace(',', '.')) <= 0]

print("\n--- 🧠 DEVAM KARARI ANALİZİ ---")
print(f"Toplam DEVAM Kararı: {len(devam_rows)}")
print(f"  -> Kazananlar (✅ Kazanç Teyitli): {len(devam_win)} adet | Kâr: +{sum(float(r['Net PnL (TRY)'].replace(',', '.')) for r in devam_win):.2f} TRY")
print(f"  -> Kaybedenler (❌ LLM Yanıldı): {len(devam_loss)} adet | Zarar: {sum(float(r['Net PnL (TRY)'].replace(',', '.')) for r in devam_loss):.2f} TRY")

print("\nDEVAM diyen ve Kaybeden işlemlerin Güven ve Nedenleri:")
for r in devam_loss:
    pnl = float(r['Net PnL (TRY)'].replace(',', '.'))
    print(f"  {r['Sembol']:12} | Giriş: {r['Giriş Zamanı']} | Güven: {r['LLM Güven (%)']:5} | PnL: {pnl:6.2f} TRY | Çıkış: {r['Çıkış Nedeni']}")

print("\nDEVAM diyen ve Kazanan işlemlerin Güven ve Nedenleri:")
for r in devam_win:
    pnl = float(r['Net PnL (TRY)'].replace(',', '.'))
    print(f"  {r['Sembol']:12} | Giriş: {r['Giriş Zamanı']} | Güven: {r['LLM Güven (%)']:5} | PnL: +{pnl:5.2f} TRY | Çıkış: {r['Çıkış Nedeni']}")

# Churn & Ardışık Giriş Analizi
rows_asc = list(reversed(rows))
reentries = []
for i in range(1, len(rows_asc)):
    prev = rows_asc[i-1]
    curr = rows_asc[i]
    if prev['Sembol'] == curr['Sembol']:
        reentries.append((prev, curr))

print(f"\n--- 🔄 AYNI SEMBOLE PEŞ PEŞE GİRİŞ (CHURN) ANALİZİ ---")
print(f"Aynı Sembole Art Arda Açılan İşlem Sayısı: {len(reentries)}")
givebacks = 0
giveback_loss = 0.0
for p, c in reentries:
    p_pnl = float(p['Net PnL (TRY)'].replace(',', '.'))
    c_pnl = float(c['Net PnL (TRY)'].replace(',', '.'))
    if p_pnl > 0 and c_pnl < 0:
        givebacks += 1
        giveback_loss += c_pnl
    print(f"  {c['Sembol']:10} | Önceki: {p['Çıkış Nedeni']:13} ({p_pnl:6.2f} TRY) -> Yeni: {c['Çıkış Nedeni']:13} ({c_pnl:6.2f} TRY)")

print(f"\nKâr Edip Hemen Ardından Aynı Sembolde Zarar Eden (Kârı Geri Veren) İşlem Sayısı: {givebacks}")
print(f"Geri Verilen Kâr Tutarı: {giveback_loss:.2f} TRY")

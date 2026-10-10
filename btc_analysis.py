import pandas as pd
import re
from datetime import datetime, timedelta

# 1. CSV'yi oku (türkçe sütun adları, ; ayracı)
csv_path = r'D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv'
df = pd.read_csv(csv_path, sep=';', engine='python')

# Sütun adlarını normalize et (BOM ve boşluk temizliği)
df.columns = [c.replace('\ufeff', '').strip() for c in df.columns]

# Sadece BTCUSD
btc = df[df['Sembol'].str.upper() == 'BTCUSD'].copy()
print(f"Toplam BTCUSD işlem sayısı: {len(btc)}")

# Tür dönüşümleri
btc['Giriş Fiyatı'] = pd.to_numeric(btc['Giriş Fiyatı'], errors='coerce')
btc['Çıkış Fiyatı'] = pd.to_numeric(btc['Çıkış Fiyatı'], errors='coerce')
btc['Kâr/Zarar (Pip)'] = pd.to_numeric(btc['Kâr/Zarar (Pip)'].astype(str).str.replace('+',''), errors='coerce')
btc['Net Getiri (USD)'] = pd.to_numeric(btc['Net Getiri (USD)'].astype(str).str.replace('+',''), errors='coerce')
btc['Giriş Zamanı'] = pd.to_datetime(btc['Giriş Zamanı (UTC+3)'], format='%Y-%m-%d %H:%M:%S')
btc['Çıkış Zamanı'] = pd.to_datetime(btc['Çıkış Zamanı (UTC+3)'], format='%Y-%m-%d %H:%M:%S')

# Süreyi dakikaya çevir
def parse_sure(s):
    if pd.isna(s): return None
    m = re.findall(r'(\d+)\s*(dk|sa|sn)', str(s))
    total = 0
    for val, unit in m:
        v = int(val)
        if unit == 'sa': total += v * 60
        elif unit == 'dk': total += v
        elif unit == 'sn': total += v / 60.0
    return total

btc['Süre_dk'] = btc['Süre'].apply(parse_sure)

# Sonuç normalize
btc['Sonuç2'] = btc['Sonuç'].apply(lambda x: 'WIN' if 'KAZANÇ' in str(x).upper() else 'LOSS')

# 2. BUY / SELL ayrı analiz
print("\n=== 2. BUY / SELL ÖZET ===")
for yon in ['BUY', 'SELL']:
    sub = btc[btc['Yön'] == yon]
    wins = sub[sub['Sonuç2'] == 'WIN']
    losses = sub[sub['Sonuç2'] == 'LOSS']
    print(f"\n{yon}: İşlem sayısı={len(sub)}")
    print(f"  Win={len(wins)}  Loss={len(losses)}  Win oranı={len(wins)/len(sub)*100:.1f}%")
    print(f"  Net getiri (USD) toplam={sub['Net Getiri (USD)'].sum():.2f}")
    print(f"  Pip toplam={sub['Kâr/Zarar (Pip)'].sum():.1f}")
    if len(wins):
        print(f"  Ortalama kazanç (USD)={wins['Net Getiri (USD)'].mean():.2f}  Pip={wins['Kâr/Zarar (Pip)'].mean():.1f}")
    if len(losses):
        print(f"  Ortalama kayıp (USD)={losses['Net Getiri (USD)'].mean():.2f}  Pip={losses['Kâr/Zarar (Pip)'].mean():.1f}")

print("\n=== GENEL ÖZET ===")
print(f"Toplam net getiri: {btc['Net Getiri (USD)'].sum():.2f} USD")
print(f"Toplam pip: {btc['Kâr/Zarar (Pip)'].sum():.1f}")
print(f"Genel win oranı: {len(btc[btc['Sonuç2']=='WIN'])/len(btc)*100:.1f}%")

# 3. En büyük 10 kayıp
print("\n=== 3. EN BÜYÜK 10 KAYIP ===")
losses_all = btc[btc['Sonuç2'] == 'LOSS'].copy()
losses_all = losses_all.sort_values('Net Getiri (USD)', ascending=True)
print_cols = ['Bilet No', 'Yön', 'Giriş Fiyatı', 'Çıkış Fiyatı', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)', 'Süre', 'Çıkış Nedeni', 'Giriş Zamanı (UTC+3)']
for idx, row in losses_all.head(10).iterrows():
    print(f"{row['Giriş Zamanı (UTC+3)']} | {row['Yön']} | Giriş {row['Giriş Fiyatı']:.2f} -> Çıkış {row['Çıkış Fiyatı']:.2f} | Pip {row['Kâr/Zarar (Pip)']:.1f} | USD {row['Net Getiri (USD)']:.2f} | Süre {row['Süre']} | {row['Çıkış Nedeni']}")

print("\n--- Kayıpların ortak özellikleri ---")
print(f"Ortalama kayıp pip: {losses_all['Kâr/Zarar (Pip)'].mean():.1f}")
print(f"Ortalama kayıp USD: {losses_all['Net Getiri (USD)'].mean():.2f}")
print(f"Ortalama süre (dk): {losses_all['Süre_dk'].mean():.1f}")
print(f"Kayıplarda çıkış nedeni dağılımı:\n{losses_all['Çıkış Nedeni'].value_counts()}")
print(f"Kayıplarda yön dağılımı:\n{losses_all['Yön'].value_counts()}")

# 4. Zaman aralıkları
print("\n=== 4. ZAMAN ARALIKLARI (UTC+3) ===")
def bucket_saat(dt):
    h = dt.hour
    if 0 <= h < 16: return '00:00-16:00'
    if 16 <= h < 18: return '16:00-18:00'
    if 18 <= h < 20: return '18:00-20:00'
    if 20 <= h < 22: return '20:00-22:00'
    return '22:00-24:00'

btc['Saat_araligi'] = btc['Giriş Zamanı'].apply(bucket_saat)
for bucket in ['00:00-16:00','16:00-18:00','18:00-20:00','20:00-22:00','22:00-24:00']:
    sub = btc[btc['Saat_araligi'] == bucket]
    if len(sub) == 0: continue
    wins = sub[sub['Sonuç2']=='WIN']
    losses = sub[sub['Sonuç2']=='LOSS']
    fiyat_degisim = sub['Kâr/Zarar (Pip)'].sum()
    print(f"\n{bucket}: n={len(sub)}  Win={len(wins)} Loss={len(losses)} Win%={len(wins)/len(sub)*100:.1f}  Net USD={sub['Net Getiri (USD)'].sum():.2f}  Toplam Pip={fiyat_degisim:.1f}")
    print(f"  Giriş fiyatı aralığı: {sub['Giriş Fiyatı'].min():.2f} - {sub['Giriş Fiyatı'].max():.2f}")

# 5. Sinyal tekrarı / cooldown
print("\n=== 5. SİNYAL TEKRARI / COOLDOWN ===")
btc_sorted = btc.sort_values('Giriş Zamanı').reset_index(drop=True)
print("Ardışık BTCUSD işlemleri arası süre (dk) ve yön değişimi:")
for i in range(1, len(btc_sorted)):
    prev = btc_sorted.iloc[i-1]
    cur = btc_sorted.iloc[i]
    delta_min = (cur['Giriş Zamanı'] - prev['Giriş Zamanı']).total_seconds() / 60.0
    same_dir = cur['Yön'] == prev['Yön']
    if delta_min <= 30:  # 30 dk altındaki yakın işlemler
        print(f"  {cur['Giriş Zamanı (UTC+3)']} | önceki {delta_min:.1f} dk önce | yön {'AYNI' if same_dir else 'TERS'} | önceki={prev['Yön']} sonraki={cur['Yön']} | önceki sonuç={prev['Sonuç']} | yeni sonuç={cur['Sonuç']}")

# Ardışık kayıplardan sonraki işlemler
print("\nArdışık kayıptan hemen sonra açılan işlemler:")
for i in range(1, len(btc_sorted)):
    prev = btc_sorted.iloc[i-1]
    cur = btc_sorted.iloc[i]
    if prev['Sonuç2'] == 'LOSS':
        delta_min = (cur['Giriş Zamanı'] - prev['Giriş Zamanı']).total_seconds() / 60.0
        print(f"  Kayıp {prev['Giriş Zamanı (UTC+3)']} -> sonraki {cur['Giriş Zamanı (UTC+3)']} ({delta_min:.1f} dk) | yön {prev['Yön']}->{cur['Yön']} | sonuç {cur['Sonuç']}")

# 6. Çıkış nedeni dağılımı
print("\n=== 6. ÇIKIŞ NEDENİ / SL-TP ANALİZİ ===")
print(btc['Çıkış Nedeni'].value_counts())
print(f"\nSL ile kapanan işlem oranı: {len(btc[btc['Çıkış Nedeni'].str.contains('Zarar Durdur', na=False)])/len(btc)*100:.1f}%")
print(f"TP ile kapanan işlem oranı: {len(btc[btc['Çıkış Nedeni'].str.contains('Kâr Al', na=False)])/len(btc)*100:.1f}%")
print(f"Scalper Close oranı: {len(btc[btc['Çıkış Nedeni'].str.contains('Scalper Close', na=False)])/len(btc)*100:.1f}%")

# SL seviyeleri boş mu?
print(f"\nSL Seviyesi '-' olan işlem oranı: {(btc['SL Seviyesi']=='-').mean()*100:.1f}%")
print(f"TP Seviyesi '-' olan işlem oranı: {(btc['TP Seviyesi']=='-').mean()*100:.1f}%")

# Kazananların pip ortalaması vs kaybedenlerin pip ortalaması (mutlak)
wins = btc[btc['Sonuç2']=='WIN']
losses = btc[btc['Sonuç2']=='LOSS']
print(f"\nKazanan ortalama pip (mutlak): {wins['Kâr/Zarar (Pip)'].abs().mean():.1f}")
print(f"Kaybeden ortalama pip (mutlak): {losses['Kâr/Zarar (Pip)'].abs().mean():.1f}")
print(f"R/R (ortalama kazanç pip / ortalama kayıp pip): {wins['Kâr/Zarar (Pip)'].abs().mean()/losses['Kâr/Zarar (Pip)'].abs().mean():.2f}")

# 7. Lot büyüklüğüne göre
print("\n=== LOT BÜYÜKLÜĞÜ ETKİSİ ===")
print(btc.groupby('Sonuç2')['Lot'].agg(['mean','median','min','max']))

print("\n=== İŞLEMLERİN KRONOLOJİK LİSTESİ ===")
for idx, row in btc_sorted.iterrows():
    print(f"{row['Giriş Zamanı (UTC+3)']} | {row['Yön']} | {row['Giriş Fiyatı']:.2f} -> {row['Çıkış Fiyatı']:.2f} | Pip {row['Kâr/Zarar (Pip)']:+7.1f} | USD {row['Net Getiri (USD)']:+6.2f} | {row['Sonuç']} | {row['Çıkış Nedeni']}")

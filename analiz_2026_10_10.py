import pandas as pd
import numpy as np
import re
import warnings
warnings.filterwarnings('ignore')

# Veriyi oku
df = pd.read_csv(r'D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv', sep=';')

# Temizlik
for col in ['Parite', 'Sembol', 'Strateji', 'Yön', 'Çıkış Nedeni', 'Sonuç']:
    df[col] = df[col].astype(str).str.strip()

# Zaman parse
for col in ['Giriş Zamanı (UTC+3)', 'Çıkış Zamanı (UTC+3)']:
    df[col] = pd.to_datetime(df[col], format='ISO8601')

# Sayısal alanlar
for col in ['Giriş Fiyatı', 'Çıkış Fiyatı', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)']:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Sonuç binary
df['Kazanç'] = df['Sonuç'].str.contains('KAZANÇ', na=False).astype(int)
df['Kayıp'] = df['Sonuç'].str.contains('KAYIP', na=False).astype(int)

# Süre parser: "X dk Y sn" veya "Y sn"
def sure_to_seconds(s):
    if pd.isna(s):
        return np.nan
    s = str(s).strip()
    if s in ['-', '']:
        return np.nan
    dk = re.search(r'(\d+)\s*dk', s)
    sn = re.search(r'(\d+)\s*sn', s)
    total = 0
    if dk:
        total += int(dk.group(1)) * 60
    if sn:
        total += int(sn.group(1))
    return total if total > 0 else np.nan

df['Süre_Saniye'] = df['Süre'].apply(sure_to_seconds)
df['Süre_Dakika'] = df['Süre_Saniye'] / 60.0

# Çıkış nedeni kategorileri
df['SL_Cikis'] = df['Çıkış Nedeni'].str.contains('SL|Zarar Durdur|Zarar', na=False)
df['TP_Cikis'] = df['Çıkış Nedeni'].str.contains('TP|Kâr Al', na=False)
df['Scalper_Close'] = df['Çıkış Nedeni'].str.contains('Scalper Close', na=False)

# Sırala
df = df.sort_values(['Parite', 'Giriş Zamanı (UTC+3)']).reset_index(drop=True)

print("="*80)
print("GENEL VERİ ÖZETİ")
print("="*80)
print(f"Toplam işlem: {len(df)}")
print(f"Kazanç: {df['Kazanç'].sum()} | Kayıp: {df['Kayıp'].sum()}")
print(f"Win rate: {df['Kazanç'].mean()*100:.1f}%")
print(f"Toplam net getiri (USD): {df['Net Getiri (USD)'].sum():.2f}")
print(f"Ortalama işlem süresi: {df['Süre_Dakika'].mean():.1f} dk")
print(f"Median işlem süresi: {df['Süre_Dakika'].median():.1f} dk")
print(f"Ortalama kazançlı işlem süresi: {df[df['Kazanç']==1]['Süre_Dakika'].mean():.1f} dk")
print(f"Ortalama kayıplı işlem süresi: {df[df['Kayıp']==1]['Süre_Dakika'].mean():.1f} dk")

print("\n" + "="*80)
print("1. STRATEJİ DAĞILIMI VE PERFORMANSI")
print("="*80)
print("\nStrateji dağılımı:")
print(df['Strateji'].value_counts())

print("\nStrateji bazında performans:")
strat_perf = df.groupby('Strateji').agg(
    İşlem=('Bilet No','count'),
    Kazanç=('Kazanç','sum'),
    Kayıp=('Kayıp','sum'),
    WinRate=('Kazanç','mean'),
    ToplamUSD=('Net Getiri (USD)','sum'),
    OrtPip=('Kâr/Zarar (Pip)','mean'),
    OrtDakika=('Süre_Dakika','mean')
).round(2)
print(strat_perf)

print("\nParite x Strateji performansı:")
parite_strat = df.groupby(['Parite','Strateji']).agg(
    İşlem=('Bilet No','count'),
    WinRate=('Kazanç','mean'),
    ToplamUSD=('Net Getiri (USD)','sum'),
    OrtDakika=('Süre_Dakika','mean'),
    OrtPip=('Kâr/Zarar (Pip)','mean')
).round(2)
print(parite_strat)

print("\n" + "="*80)
print("2. YÖN KARARLARI TUTARLILIĞI")
print("="*80)
yon = pd.crosstab(df['Parite'], df['Yön'], margins=True)
print(yon)

print("\nParite bazında Yön-WinRate:")
yon_perf = df.groupby(['Parite','Yön']).agg(
    İşlem=('Bilet No','count'),
    Kazanç=('Kazanç','sum'),
    Kayıp=('Kayıp','sum'),
    WinRate=('Kazanç','mean'),
    ToplamUSD=('Net Getiri (USD)','sum'),
    OrtPip=('Kâr/Zarar (Pip)','mean'),
    OrtDakika=('Süre_Dakika','mean')
).round(2)
print(yon_perf)

print("\n" + "="*80)
print("BTCUSD ÖZEL ANALİZİ")
print("="*80)
btc = df[df['Parite']=='BTCUSD'].copy().sort_values('Giriş Zamanı (UTC+3)').reset_index(drop=True)
print(f"BTCUSD işlem sayısı: {len(btc)}")
print(f"BUY: {(btc['Yön']=='BUY').sum()} | SELL: {(btc['Yön']=='SELL').sum()}")
print(f"BUY oranı: {(btc['Yön']=='BUY').mean()*100:.1f}%")
if (btc['Yön']=='BUY').sum()>0:
    print(f"BUY win rate: {btc[btc['Yön']=='BUY']['Kazanç'].mean()*100:.1f}%")
if (btc['Yön']=='SELL').sum()>0:
    print(f"SELL win rate: {btc[btc['Yön']=='SELL']['Kazanç'].mean()*100:.1f}%")
print(f"BTCUSD toplam USD: {btc['Net Getiri (USD)'].sum():.2f}")
print(f"BTCUSD ortalama süre: {btc['Süre_Dakika'].mean():.1f} dk")
print(f"BTCUSD median süre: {btc['Süre_Dakika'].median():.1f} dk")

print("\nBTCUSD saatlik işlem akışı:")
for i, row in btc.iterrows():
    print(f"{row['Giriş Zamanı (UTC+3)'].strftime('%m-%d %H:%M')} {row['Yön']:4s} Giriş:{row['Giriş Fiyatı']:>10.2f} Çıkış:{row['Çıkış Fiyatı']:>10.2f} Pip:{row['Kâr/Zarar (Pip)']:>8.1f} {row['Sonuç']:10s} Neden:{row['Çıkış Nedeni']}")

print("\n" + "="*80)
print("3. ARDIŞIK İŞLEMLERDE YÖN DEĞİŞİMİ / WHIPSAW")
print("="*80)
for parite in sorted(df['Parite'].unique()):
    sub = df[df['Parite']==parite].sort_values('Giriş Zamanı (UTC+3)').reset_index(drop=True)
    if len(sub) < 2:
        continue
    print(f"\n--- {parite} (n={len(sub)}) ---")
    whipsaw_count = 0
    yon_degisim = 0
    for i in range(1, len(sub)):
        prev = sub.iloc[i-1]
        cur = sub.iloc[i]
        if prev['Yön'] != cur['Yön']:
            yon_degisim += 1
            if prev['Kayıp'] == 1 and cur['Kayıp'] == 1:
                whipsaw_count += 1
                print(f"  WHIPSAW: {prev['Giriş Zamanı (UTC+3)'].strftime('%m-%d %H:%M')} {prev['Yön']} kayıp ({prev['Kâr/Zarar (Pip)']:.1f}p) -> {cur['Giriş Zamanı (UTC+3)'].strftime('%H:%M')} {cur['Yön']} kayıp ({cur['Kâr/Zarar (Pip)']:.1f}p)")
    print(f"  Toplam yön değişimi: {yon_degisim}, whipsaw (kayıp->ters yön->kayıp): {whipsaw_count}")

print("\n" + "="*80)
print("4. MARKET REGIME / REJİM ANALİZİ")
print("="*80)
sl_kapanma = df['SL_Cikis'].sum()
tp_kapanma = df['TP_Cikis'].sum()
manuel_kapanma = df['Scalper_Close'].sum()
diger = len(df) - sl_kapanma - tp_kapanma - manuel_kapanma
print("Çıkış nedenleri:")
print(df['Çıkış Nedeni'].value_counts())
print(f"\nSL kapanma: {sl_kapanma} ({sl_kapanma/len(df)*100:.1f}%)")
print(f"TP kapanma: {tp_kapanma} ({tp_kapanma/len(df)*100:.1f}%)")
print(f"Scalper Close: {manuel_kapanma} ({manuel_kapanma/len(df)*100:.1f}%)")
print(f"Diğer: {diger}")

# SL ile kapanan kazançlı işlemler (trailing stop/breakeven)
sl_kazanc = df[(df['SL_Cikis']) & (df['Kazanç']==1)]
print(f"\nSL ile kapanan KAZANÇLI işlem sayısı: {len(sl_kazanc)} ({len(sl_kazanc)/sl_kapanma*100:.1f}% of SL exits)")
print(f"SL ile kapanan KAYIPLI işlem sayısı: {sl_kapanma - len(sl_kazanc)}")

print(f"\nKısa süreli işlem (<=5 dk): {(df['Süre_Dakika']<=5).sum()} ({(df['Süre_Dakika']<=5).mean()*100:.1f}%)")
print(f"Çok kısa işlem (<=2 dk): {(df['Süre_Dakika']<=2).sum()} ({(df['Süre_Dakika']<=2).mean()*100:.1f}%)")
print(f"5-15 dk arası: {((df['Süre_Dakika']>5)&(df['Süre_Dakika']<=15)).sum()}")
print(f">15 dk: {(df['Süre_Dakika']>15).sum()}")

print("\nParite bazında SL/TP dağılımı:")
for parite in sorted(df['Parite'].unique()):
    sub = df[df['Parite']==parite]
    sl = sub['SL_Cikis'].sum()
    tp = sub['TP_Cikis'].sum()
    sc = sub['Scalper_Close'].sum()
    print(f"  {parite}: n={len(sub)}, SL {sl} ({sl/len(sub)*100:.0f}%), TP {tp} ({tp/len(sub)*100:.0f}%), ScalperClose {sc}")

print("\nGiriş fiyatlarının saatlik trend yönü (parite bazında):")
for parite in sorted(df['Parite'].unique()):
    sub = df[df['Parite']==parite].sort_values('Giriş Zamanı (UTC+3)')
    if len(sub) < 2:
        continue
    first = sub.iloc[0]['Giriş Fiyatı']
    last = sub.iloc[-1]['Giriş Fiyatı']
    change_pct = (last - first) / first * 100
    buy_ratio = (sub['Yön']=='BUY').mean()*100
    sell_ratio = (sub['Yön']=='SELL').mean()*100
    avg_buy = sub[sub['Yön']=='BUY']['Giriş Fiyatı'].mean() if (sub['Yön']=='BUY').any() else np.nan
    avg_sell = sub[sub['Yön']=='SELL']['Giriş Fiyatı'].mean() if (sub['Yön']=='SELL').any() else np.nan
    print(f"  {parite}: ilk giriş {first:.4f}, son giriş {last:.4f}, değişim {change_pct:+.2f}%, BUY%{buy_ratio:.0f}/SELL%{sell_ratio:.0f}")
    if not np.isnan(avg_buy) and not np.isnan(avg_sell):
        print(f"          Ortalama BUY giriş: {avg_buy:.4f}, Ortalama SELL giriş: {avg_sell:.4f}")

print("\n" + "="*80)
print("5. GBPUSD YÖN ANALİZİ")
print("="*80)
gbp = df[df['Parite']=='GBPUSD'].sort_values('Giriş Zamanı (UTC+3)')
print(f"GBPUSD işlem sayısı: {len(gbp)}")
print(f"BUY: {(gbp['Yön']=='BUY').sum()}, SELL: {(gbp['Yön']=='SELL').sum()}")
print(f"BUY oranı: {(gbp['Yön']=='BUY').mean()*100:.1f}%")
if len(gbp)>0:
    print(gbp[['Giriş Zamanı (UTC+3)','Yön','Giriş Fiyatı','Çıkış Fiyatı','Kâr/Zarar (Pip)','Sonuç','Çıkış Nedeni','Süre']].to_string(index=False))

print("\n" + "="*80)
print("6. ÇIKIŞ NEDENLERİ / SÜRE / SONUÇ ÖZETİ")
print("="*80)
cikis = df.groupby('Çıkış Nedeni').agg(
    İşlem=('Bilet No','count'),
    WinRate=('Kazanç','mean'),
    OrtDakika=('Süre_Dakika','mean'),
    OrtPip=('Kâr/Zarar (Pip)','mean'),
    ToplamUSD=('Net Getiri (USD)','sum')
).round(2)
print(cikis)

print("\n" + "="*80)
print("7. PARİTE BAŞINA NET GETİRİ / RİSK METRİKLERİ")
print("="*80)
parite_ozet = df.groupby('Parite').agg(
    İşlem=('Bilet No','count'),
    Kazanç=('Kazanç','sum'),
    Kayıp=('Kayıp','sum'),
    WinRate=('Kazanç','mean'),
    ToplamUSD=('Net Getiri (USD)','sum'),
    OrtPip=('Kâr/Zarar (Pip)','mean'),
    OrtKazançPip=('Kâr/Zarar (Pip)', lambda x: x[x>0].mean()),
    OrtKayıpPip=('Kâr/Zarar (Pip)', lambda x: x[x<0].mean()),
    OrtDakika=('Süre_Dakika','mean'),
    MedianDakika=('Süre_Dakika','median'),
    MaxKayıp=('Kâr/Zarar (Pip)','min'),
    MaxKazanç=('Kâr/Zarar (Pip)','max')
).round(2)
print(parite_ozet)

print("\n" + "="*80)
print("8. SAAT BAZINDA AKTİVİTE / BTCUSD")
print("="*80)
btc['Saat'] = btc['Giriş Zamanı (UTC+3)'].dt.hour
saatlik = btc.groupby('Saat').agg(
    İşlem=('Bilet No','count'),
    BUY=('Yön', lambda x: (x=='BUY').sum()),
    SELL=('Yön', lambda x: (x=='SELL').sum()),
    WinRate=('Kazanç','mean'),
    ToplamUSD=('Net Getiri (USD)','sum')
).round(2)
print(saatlik)

# Tüm işlemler için zaman dilimi
print("\n" + "="*80)
print("9. TÜM PARİTELER - İŞLEM ZAMAN DİLİMLERİ")
print("="*80)
df['Saat'] = df['Giriş Zamanı (UTC+3)'].dt.hour
for parite in sorted(df['Parite'].unique()):
    sub = df[df['Parite']==parite]
    print(f"\n{parite}: ilk işlem {sub['Giriş Zamanı (UTC+3)'].min()}, son işlem {sub['Giriş Zamanı (UTC+3)'].max()}")
    print(sub.groupby('Saat').size().sort_index().to_dict())

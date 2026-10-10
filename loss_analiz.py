import pandas as pd
import numpy as np
import re
from datetime import datetime

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)

# CSV'yi oku
df = pd.read_csv(r'D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv', sep=';', encoding='utf-8-sig')

# Temizlik
df.columns = [c.strip() for c in df.columns]

# Tarih/saat ayristirma
df['Giriş Zamanı (UTC+3)'] = pd.to_datetime(df['Giriş Zamanı (UTC+3)'])
df['Çıkış Zamanı (UTC+3)'] = pd.to_datetime(df['Çıkış Zamanı (UTC+3)'])
df['Giriş Tarihi'] = df['Giriş Zamanı (UTC+3)'].dt.date
df['Giriş Saat'] = df['Giriş Zamanı (UTC+3)'].dt.hour
df['Giriş Dakika'] = df['Giriş Zamanı (UTC+3)'].dt.minute

# Süreyi saniyeye çevir
def sure_to_sn(sure_str):
    if pd.isna(sure_str):
        return np.nan
    sure_str = str(sure_str)
    saat = re.search(r'(\d+) sa', sure_str)
    dakika = re.search(r'(\d+) dk', sure_str)
    saniye = re.search(r'(\d+) sn', sure_str)
    toplam = 0
    if saat:
        toplam += int(saat.group(1)) * 3600
    if dakika:
        toplam += int(dakika.group(1)) * 60
    if saniye:
        toplam += int(saniye.group(1))
    return toplam

df['Süre (sn)'] = df['Süre'].apply(sure_to_sn)
df['Süre (dk)'] = df['Süre (sn)'] / 60

# Sayisal kolonlari temizle
for col in ['Giriş Fiyatı', 'Çıkış Fiyatı', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)']:
    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.'), errors='coerce')

print("=" * 70)
print("ERKAN - LOSS ISLEMLERI SINYAL KALITESI ANALIZI")
print("=" * 70)

print("\n" + "=" * 70)
print("1. GENEL BAKIS")
print("=" * 70)
print(f"Toplam islem sayisi: {len(df)}")
print(f"Tarih araligi: {df['Giriş Zamanı (UTC+3)'].min()} - {df['Giriş Zamanı (UTC+3)'].max()}")
print("\nSonuc dagilimi:")
print(df['Sonuç'].value_counts())
print(f"Win rate: {(df['Sonuç']=='KAZANÇ (WIN)').mean()*100:.1f}%")
print("\nParite dagilimi:")
print(df['Parite'].value_counts())
print("\nStrateji dagilimi:")
print(df['Strateji'].value_counts())

# Sadece 09-10-2026 islemleri
df_09 = df[df['Giriş Tarihi'] == pd.to_datetime('2026-10-09').date()].copy()
print(f"\n09-10-2026 girisli islem sayisi: {len(df_09)} / {len(df)}")
print(f"09-10-2026 LOSS sayisi: {(df_09['Sonuç']=='KAYIP (LOSS)').sum()}")
print(f"09-10-2026 Win rate: {(df_09['Sonuç']=='KAZANÇ (WIN)').mean()*100:.1f}%")

# LOSS islemleri
loss_df = df[df['Sonuç'] == 'KAYIP (LOSS)'].copy()
print("\n" + "=" * 70)
print("2. LOSS ISLEMLERI GRUPLAMA")
print("=" * 70)
print(f"Toplam LOSS islem sayisi: {len(loss_df)}")
print(f"Toplam pip kaybi: {loss_df['Kâr/Zarar (Pip)'].sum():.1f}")
print(f"Toplam USD kaybi: {loss_df['Net Getiri (USD)'].sum():.2f}")
print(f"Ortalama pip kaybi (islem basina): {loss_df['Kâr/Zarar (Pip)'].mean():.1f}")
print(f"Ortalama USD kaybi (islem basina): {loss_df['Net Getiri (USD)'].mean():.2f}")

# Parite bazinda LOSS ozeti
parite_loss = loss_df.groupby('Parite').agg({
    'Bilet No': 'count',
    'Kâr/Zarar (Pip)': 'sum',
    'Net Getiri (USD)': 'sum',
    'Süre (dk)': 'mean'
}).rename(columns={'Bilet No': 'Loss Sayisi'})
parite_loss['Ort. Pip Kaybi'] = (loss_df.groupby('Parite')['Kâr/Zarar (Pip)'].mean()).round(1)
parite_loss['Ort. USD Kaybi'] = (loss_df.groupby('Parite')['Net Getiri (USD)'].mean()).round(2)
parite_loss = parite_loss[['Loss Sayisi', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)', 'Ort. Pip Kaybi', 'Ort. USD Kaybi', 'Süre (dk)']]
parite_loss.columns = ['Loss Sayisi', 'Toplam Pip', 'Toplam USD', 'Ort. Pip', 'Ort. USD', 'Ort. Sure (dk)']
print("\nParite bazinda LOSS ozeti:")
print(parite_loss)

# Yon bazinda LOSS
yon_loss = loss_df.groupby(['Parite', 'Yön']).agg({
    'Bilet No': 'count',
    'Kâr/Zarar (Pip)': ['sum', 'mean'],
    'Net Getiri (USD)': ['sum', 'mean']
}).round(2)
yon_loss.columns = ['Loss Sayisi', 'Toplam Pip', 'Ort. Pip', 'Toplam USD', 'Ort. USD']
print("\nParite + Yon bazinda LOSS:")
print(yon_loss)

# Saat araligi bazinda
loss_df['Saat Araligi'] = loss_df['Giriş Saat'].apply(lambda x: f"{x:02d}:00-{(x+1)%24:02d}:00")
saat_loss = loss_df.groupby(['Parite', 'Saat Araligi', 'Yön']).agg({
    'Bilet No': 'count',
    'Kâr/Zarar (Pip)': ['sum', 'mean'],
    'Net Getiri (USD)': ['sum', 'mean']
}).round(2)
saat_loss.columns = ['Loss Sayisi', 'Toplam Pip', 'Ort. Pip', 'Toplam USD', 'Ort. USD']
print("\nParite + Saat Araligi + Yon bazinda LOSS:")
print(saat_loss)

print("\n" + "=" * 70)
print("3. HER PARITE ICIN EN SIK KAYIP VEREN SAAT ARALIKLARI VE YONLER")
print("=" * 70)
for parite in loss_df['Parite'].unique():
    p_loss = loss_df[loss_df['Parite'] == parite]
    print(f"\n--- {parite} ---")
    print(f"Toplam LOSS: {len(p_loss)}")
    
    saat_yon = p_loss.groupby(['Saat Araligi', 'Yön']).size().reset_index(name='Loss Sayisi')
    saat_yon = saat_yon.sort_values('Loss Sayisi', ascending=False)
    print("Saat + Yon (en sik kayip verenler):")
    print(saat_yon.head(5).to_string(index=False))
    
    # Sadece saat
    saat = p_loss.groupby('Saat Araligi').agg({
        'Bilet No': 'count',
        'Kâr/Zarar (Pip)': 'sum',
        'Net Getiri (USD)': 'sum'
    }).sort_values('Bilet No', ascending=False).head(3)
    saat.columns = ['Loss Sayisi', 'Toplam Pip', 'Toplam USD']
    print("En tehlikeli saat araliklari:")
    print(saat)

# Yon dagilimi
print("\n" + "=" * 70)
print("4. LOSS YON DAGILIMI VE STRATEJI ANALIZI")
print("=" * 70)
print("Loss yon dagilimi (toplam):")
print(loss_df['Yön'].value_counts())
print("\nLoss yon dagilimi (pariteye gore):")
print(pd.crosstab(loss_df['Parite'], loss_df['Yön'], margins=True))
print("\nLoss strateji dagilimi:")
print(loss_df['Strateji'].value_counts())

print("\n" + "=" * 70)
print("5. ARDISIK KAYIPLAR VE YON DEGISIMLERI (WHIPSAAW/REVENGE)")
print("=" * 70)

# Tum islemleri zamana gore sirala
df_sorted = df.sort_values('Giriş Zamanı (UTC+3)').reset_index(drop=True)

# Ardindan gelen kayiplari bul - tum islemler arasi
df_sorted['Onceki Sonuc'] = df_sorted['Sonuç'].shift(1)
df_sorted['Onceki Parite'] = df_sorted['Parite'].shift(1)
df_sorted['Onceki Yon'] = df_sorted['Yön'].shift(1)

# Ardindan hemen loss gelen loss'lar (genel)
consec_loss = df_sorted[(df_sorted['Sonuç'] == 'KAYIP (LOSS)') & (df_sorted['Onceki Sonuc'] == 'KAYIP (LOSS)')]
print(f"Ard arda gelen LOSS cifti sayisi (genel): {len(consec_loss)}")

# Ayni paritede ardindan loss gelen loss
same_par_consec = consec_loss[consec_loss['Parite'] == consec_loss['Onceki Parite']]
print(f"Ayni paritede ard arda LOSS: {len(same_par_consec)}")

# Whipsaw/Revenge tanimi: onceki loss ile ayni parite, yon durumuna gore
revenge_same = same_par_consec[same_par_consec['Yön'] == same_par_consec['Onceki Yon']]
revenge_flip = same_par_consec[same_par_consec['Yön'] != same_par_consec['Onceki Yon']]
print(f"Ayni yonde devam (revenge same): {len(revenge_same)}")
print(f"Yon degistirerek tekrar giris (whipsaw flip): {len(revenge_flip)}")

print("\nWhipsaw/Yon degisimi detaylari:")
for idx, row in revenge_flip.iterrows():
    print(f"  {row['Giriş Zamanı (UTC+3)']} | {row['Parite']} | Onceki: {row['Onceki Yon']} -> Simdi: {row['Yön']} | Pip: {row['Kâr/Zarar (Pip)']} | USD: {row['Net Getiri (USD)']}")

print("\nAyni yonde devam detaylari:")
for idx, row in revenge_same.iterrows():
    print(f"  {row['Giriş Zamanı (UTC+3)']} | {row['Parite']} | Yon: {row['Yön']} | Pip: {row['Kâr/Zarar (Pip)']} | USD: {row['Net Getiri (USD)']}")

# Parite bazinda ardisik loss analizi
print("\n--- Parite bazinda ardisik loss ozeti ---")
for parite in loss_df['Parite'].unique():
    p_df = df_sorted[df_sorted['Parite'] == parite].copy()
    p_df['Onceki Sonuc'] = p_df['Sonuç'].shift(1)
    p_df['Onceki Yon'] = p_df['Yön'].shift(1)
    p_loss = p_df[p_df['Sonuç'] == 'KAYIP (LOSS)']
    consec = p_loss[p_loss['Onceki Sonuc'] == 'KAYIP (LOSS)']
    same_dir = consec[consec['Yön'] == consec['Onceki Yon']]
    flip_dir = consec[consec['Yön'] != consec['Onceki Yon']]
    print(f"{parite}: Ard loss={len(consec)}, Ayni yon={len(same_dir)}, Yon degisim={len(flip_dir)}")

print("\n" + "=" * 70)
print("6. GIRIS-CIKIS FIYAT HAREKETI ANALIZI")
print("=" * 70)

# Fiyat hareketi hesapla
# BUY: cikis > giris ise lehte, cikis < giris ise aleyhte
# SELL: cikis < giris ise lehte, cikis > giris ise aleyhte
loss_df['Fiyat Hareketi'] = np.where(
    loss_df['Yön'] == 'BUY',
    loss_df['Çıkış Fiyatı'] - loss_df['Giriş Fiyatı'],
    loss_df['Giriş Fiyatı'] - loss_df['Çıkış Fiyatı']
)
loss_df['Fiyat Yonu'] = np.where(loss_df['Fiyat Hareketi'] < 0, 'Aleyhte', 'Lehte')

print("Loss islemlerinde fiyat yonu (giris -> cikis):")
print(loss_df['Fiyat Yonu'].value_counts())

print("\nParite + Yon bazinda ortalama fiyat hareketi (pozitif = aleyhte gitmis):")
fiyat_hareketi = loss_df.groupby(['Parite', 'Yön'])['Fiyat Hareketi'].agg(['mean', 'count']).round(2)
print(fiyat_hareketi)

# Giriş zamanlamasi mi exit hatasi mi?
loss_df['Hata Tipi'] = loss_df.apply(lambda row: 
    'Giris Zamanlamasi (kisa sureli ters)' if row['Süre (dk)'] <= 3 else
    ('Exit/Trailing (uzun sure sonra ters)' if row['Süre (dk)'] >= 10 else 'Belirsiz/Arada'), axis=1)

print("\nLoss'larin hata tipi dagilimi:")
print(loss_df['Hata Tipi'].value_counts())

print("\nHata tipi x Parite:")
print(pd.crosstab(loss_df['Parite'], loss_df['Hata Tipi'], margins=True))

print("\nCok kisa surede (< 2 dk) zarar eden islemler (muhtemelen hemen ters gitmis):")
kisa = loss_df[loss_df['Süre (dk)'] < 2].sort_values('Net Getiri (USD)')
print(kisa[['Parite', 'Yön', 'Giriş Fiyatı', 'Çıkış Fiyatı', 'Süre', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)', 'Çıkış Nedeni']].to_string(index=False))

print("\n" + "=" * 70)
print("7. BTCUSD vs XAUUSD KARSILASTIRMASI")
print("=" * 70)

for parite in ['BTCUSD', 'XAUUSD']:
    p_all = df[df['Parite'] == parite]
    p_loss = loss_df[loss_df['Parite'] == parite]
    print(f"\n--- {parite} ---")
    print(f"Toplam islem: {len(p_all)}, Win: {(p_all['Sonuç']=='KAZANÇ (WIN)').sum()}, Loss: {(p_all['Sonuç']=='KAYIP (LOSS)').sum()}")
    print(f"Win rate: {(p_all['Sonuç']=='KAZANÇ (WIN)').mean()*100:.1f}%")
    print(f"Toplam pip getirisi: {p_all['Kâr/Zarar (Pip)'].sum():.1f}")
    print(f"Toplam USD getirisi: {p_all['Net Getiri (USD)'].sum():.2f}")
    print(f"Loss yuzdesi: {len(p_loss)/len(p_all)*100:.1f}%")
    print(f"Loss'larda ort. pip kaybi: {p_loss['Kâr/Zarar (Pip)'].mean():.1f}")
    print(f"Loss'larda ort. USD kaybi: {p_loss['Net Getiri (USD)'].mean():.2f}")
    print(f"Loss'larda ort. sure: {p_loss['Süre (dk)'].mean():.1f} dk")
    print(f"Loss yon dagilimi:\n{p_loss['Yön'].value_counts()}")
    print(f"Loss saat dagilimi (en sik 3):\n{p_loss.groupby('Saat Araligi').size().sort_values(ascending=False).head(3)}")

print("\n" + "=" * 70)
print("8. EN KOTU 10 GIRIS")
print("=" * 70)

worst10 = loss_df.nsmallest(10, 'Net Getiri (USD)')[['Parite', 'Yön', 'Giriş Fiyatı', 'Çıkış Fiyatı', 
                                                       'Giriş Zamanı (UTC+3)', 'Çıkış Zamanı (UTC+3)', 
                                                       'Süre', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)', 
                                                       'Çıkış Nedeni', 'Strateji', 'Saat Araligi']]
print(worst10.to_string(index=False))

print("\nEn kotu 10 girisin ortak ozellikleri:")
print("Parite dagilimi:", worst10['Parite'].value_counts().to_dict())
print("Yon dagilimi:", worst10['Yön'].value_counts().to_dict())
print("Saat araligi dagilimi:", worst10['Saat Araligi'].value_counts().head(3).to_dict())
print("Strateji:", worst10['Strateji'].value_counts().to_dict())
print("Ortalama sure:", worst10['Süre (dk)'].mean(), "dk")
print("Ortalama pip kaybi:", worst10['Kâr/Zarar (Pip)'].mean())
print("Ortalama USD kaybi:", worst10['Net Getiri (USD)'].mean())

print("\n" + "=" * 70)
print("9. CIKARIMLAR (VERIYE DAYALI)")
print("=" * 70)

# Bazı hesaplamalar
btc_buy_loss = len(loss_df[(loss_df['Parite']=='BTCUSD') & (loss_df['Yön']=='BUY')])
btc_total_buy = len(df[(df['Parite']=='BTCUSD') & (df['Yön']=='BUY')])
btc_sell_loss = len(loss_df[(loss_df['Parite']=='BTCUSD') & (loss_df['Yön']=='SELL')])
btc_total_sell = len(df[(df['Parite']=='BTCUSD') & (df['Yön']=='SELL')])

xau_sell_loss = len(loss_df[(loss_df['Parite']=='XAUUSD') & (loss_df['Yön']=='SELL')])
xau_total_sell = len(df[(df['Parite']=='XAUUSD') & (df['Yön']=='SELL')])
xau_buy_loss = len(loss_df[(loss_df['Parite']=='XAUUSD') & (loss_df['Yön']=='BUY')])
xau_total_buy = len(df[(df['Parite']=='XAUUSD') & (df['Yön']=='BUY')])

us30_buy_loss = len(loss_df[(loss_df['Parite']=='US30') & (loss_df['Yön']=='BUY')])
us30_total_buy = len(df[(df['Parite']=='US30') & (df['Yön']=='BUY')])

print(f"\nBTCUSD BUY loss orani: {btc_buy_loss}/{btc_total_buy} = {btc_buy_loss/btc_total_buy*100:.1f}%")
print(f"BTCUSD SELL loss orani: {btc_sell_loss}/{btc_total_sell} = {btc_sell_loss/btc_total_sell*100:.1f}%")
print(f"XAUUSD SELL loss orani: {xau_sell_loss}/{xau_total_sell} = {xau_sell_loss/xau_total_sell*100:.1f}%")
print(f"XAUUSD BUY loss orani: {xau_buy_loss}/{xau_total_buy} = {xau_buy_loss/xau_total_buy*100:.1f}%")
print(f"US30 BUY loss orani: {us30_buy_loss}/{us30_total_buy} = {us30_buy_loss/us30_total_buy*100:.1f}%")

# En kotu saatler
print("\nEn kotu saat araliklari (tum loss'lar):")
print(loss_df.groupby('Saat Araligi').agg({'Bilet No':'count', 'Net Getiri (USD)':'sum'}).sort_values('Bilet No', ascending=False).head(5))

# Cikis nedeni
print("\nLoss cikis nedeni dagilimi:")
print(loss_df['Çıkış Nedeni'].value_counts())

# Kazanc ve kayip ortalamalari karsilastirmasi
print("\nKazanc ve kayip ortalamalari:")
win_df = df[df['Sonuç'] == 'KAZANÇ (WIN)']
print(f"WIN ort. pip: {win_df['Kâr/Zarar (Pip)'].mean():.1f}, LOSS ort. pip: {loss_df['Kâr/Zarar (Pip)'].mean():.1f}")
print(f"WIN ort. USD: {win_df['Net Getiri (USD)'].mean():.2f}, LOSS ort. USD: {loss_df['Net Getiri (USD)'].mean():.2f}")
print(f"WIN ort. sure: {win_df['Süre (dk)'].mean():.1f} dk, LOSS ort. sure: {loss_df['Süre (dk)'].mean():.1f} dk")

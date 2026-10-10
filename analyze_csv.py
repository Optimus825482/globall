import pandas as pd
import numpy as np
import re
from datetime import datetime

file_path = r"D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv"
df = pd.read_csv(file_path, sep=';', quotechar='"')

# --- SÜRE DÖNÜŞÜMÜ: "33 dk 45 sn" -> dakika ---
def sure_to_minutes(s):
    if pd.isna(s):
        return np.nan
    s = str(s).strip()
    # örnek: "33 dk 45 sn", "170 dk 15 sn", "2 dk 53 sn"
    pattern = r'(?:(\d+)\s*sa(?:at)?)?\s*(?:(\d+)\s*dk)?\s*(?:(\d+)\s*sn)?'
    m = re.match(pattern, s)
    if not m:
        return np.nan
    hours = int(m.group(1)) if m.group(1) else 0
    mins = int(m.group(2)) if m.group(2) else 0
    secs = int(m.group(3)) if m.group(3) else 0
    return hours * 60 + mins + secs / 60.0

df['SureDakika'] = df['Süre'].apply(sure_to_minutes)

# --- PIP HESAPLAMASI: Giriş-Çıkış farkı ---
# Pip çarpanları (her sembol için 1 pip kaç fiyat birimi)
pip_multipliers = {
    'GBPUSD': 0.0001,
    'XAUUSD': 0.1,
    'BTCUSD': 1.0,
    'US30': 1.0
}

def compute_pip_diff(row):
    sym = row['Parite']
    mult = pip_multipliers.get(sym, 1.0)
    entry = row['Giriş Fiyatı']
    exit_ = row['Çıkış Fiyatı']
    direction = row['Yön']
    diff = exit_ - entry
    if direction == 'SELL':
        diff = -diff
    pip_diff = diff / mult
    return pip_diff

df['HesaplananPipFarki'] = df.apply(compute_pip_diff, axis=1)
df['PipFarkiAbs'] = df['HesaplananPipFarki'].abs()

# --- TEMEL İSTATİSTİKLER ---
print("=" * 70)
print("1. ÇIKIŞ NEDENİ DAĞILIMI")
print("=" * 70)
exit_counts = df['Çıkış Nedeni'].value_counts()
exit_ratios = df['Çıkış Nedeni'].value_counts(normalize=True) * 100
for reason in exit_counts.index:
    print(f"{reason}: {exit_counts[reason]} işlem ({exit_ratios[reason]:.1f}%)")

print("\n" + "=" * 70)
print("2. SL/TP SEVİYELERİ DURUMU")
print("=" * 70)
print("SL Seviyesi '-' olan işlem sayısı:", (df['SL Seviyesi'] == '-').sum(), "/", len(df))
print("TP Seviyesi '-' olan işlem sayısı:", (df['TP Seviyesi'] == '-').sum(), "/", len(df))
print("Her ikisi de '-' olan işlem sayısı:", ((df['SL Seviyesi'] == '-') & (df['TP Seviyesi'] == '-')).sum())
print("\nHesaplanan Pip Farkı İstatistikleri (Giriş-Çıkış):")
print(df['HesaplananPipFarki'].describe())

print("\nKayıpların büyüklük dağılımı (Pip):")
losses = df[df['Sonuç'] == 'KAYIP (LOSS)']['Kâr/Zarar (Pip)']
print(losses.describe())

print("\nKazançların büyüklük dağılımı (Pip):")
wins = df[df['Sonuç'] == 'KAZANÇ (WIN)']['Kâr/Zarar (Pip)']
print(wins.describe())

print("\n" + "=" * 70)
print("3. PARİTE BAŞINA ORTALAMA İŞLEM SÜRESİ (Kazanan vs Kaybeden)")
print("=" * 70)
summary = df.groupby(['Parite', 'Sonuç'])['SureDakika'].agg(['mean', 'median', 'count']).reset_index()
summary_pivot = summary.pivot(index='Parite', columns='Sonuç', values='mean')
print(summary_pivot.to_string())

print("\nParite başına genel ortalama süre:")
print(df.groupby('Parite')['SureDakika'].agg(['mean', 'median', 'max', 'count']).to_string())

# Uzun süren işlemler genelde kazanç mı kayıp mı?
print("\nUzun süren işlemlerin sonuç dağılımı (üst %25):")
upper_q = df['SureDakika'].quantile(0.75)
long_trades = df[df['SureDakika'] >= upper_q]
print(long_trades['Sonuç'].value_counts())
print(f"Üst %25 eşik değeri: {upper_q:.1f} dk")

print("\n" + "=" * 70)
print("4. RİSK/ÖDÜL PROFİLİ (Parite Başına)")
print("=" * 70)
risk_reward = []
for sym in df['Parite'].unique():
    sub = df[df['Parite'] == sym]
    avg_win = sub[sub['Sonuç'] == 'KAZANÇ (WIN)']['Kâr/Zarar (Pip)'].mean()
    avg_loss = sub[sub['Sonuç'] == 'KAYIP (LOSS)']['Kâr/Zarar (Pip)'].mean()
    avg_loss_abs = abs(avg_loss) if pd.notna(avg_loss) else np.nan
    rr_ratio = avg_win / avg_loss_abs if avg_loss_abs and avg_loss_abs != 0 else np.nan
    win_count = (sub['Sonuç'] == 'KAZANÇ (WIN)').sum()
    loss_count = (sub['Sonuç'] == 'KAYIP (LOSS)').sum()
    win_rate = win_count / (win_count + loss_count) * 100 if (win_count + loss_count) > 0 else np.nan
    risk_reward.append({
        'Parite': sym,
        'Win Sayısı': win_count,
        'Loss Sayısı': loss_count,
        'Win Rate %': win_rate,
        'Ort Kazanç (pip)': avg_win,
        'Ort Kayıp (pip)': avg_loss,
        '|Ort Kayıp| (pip)': avg_loss_abs,
        'R/R Oranı': rr_ratio
    })
rr_df = pd.DataFrame(risk_reward)
print(rr_df.to_string(index=False))

print("\n" + "=" * 70)
print("5. ERKEN STOP / KÂR BIRAKMA BELİRTİLERİ")
print("=" * 70)
# 1 dk altı kazanan/kaybeden işlemler
sub_1min = df[df['SureDakika'] <= 1]
print("1 dk ve altı süren işlemler:")
print(sub_1min['Sonuç'].value_counts())

# Kazanan işlemlerin süre dağılımı
win_dur = df[df['Sonuç'] == 'KAZANÇ (WIN)']['SureDakika']
loss_dur = df[df['Sonuç'] == 'KAYIP (LOSS)']['SureDakika']
print(f"\nKazanan işlem ortalama süre: {win_dur.mean():.1f} dk, medyan: {win_dur.median():.1f} dk")
print(f"Kaybeden işlem ortalama süre: {loss_dur.mean():.1f} dk, medyan: {loss_dur.median():.1f} dk")

# Büyük kazanç potansiyeli olan işlemler: en yüksek pip kazançları ve süreleri
print("\nEn yüksek pip kazançları (ilk 10):")
top_wins = df[df['Sonuç'] == 'KAZANÇ (WIN)'].nlargest(10, 'Kâr/Zarar (Pip)')[['Parite', 'Yön', 'SureDakika', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)', 'Çıkış Nedeni']]
print(top_wins.to_string(index=False))

print("\nEn büyük pip kayıpları (ilk 10):")
top_losses = df[df['Sonuç'] == 'KAYIP (LOSS)'].nsmallest(10, 'Kâr/Zarar (Pip)')[['Parite', 'Yön', 'SureDakika', 'Kâr/Zarar (Pip)', 'Net Getiri (USD)', 'Çıkış Nedeni']]
print(top_losses.to_string(index=False))

# Kazanan işlemler arasında çok kısa sürenlerin oranı
very_short_wins = df[(df['Sonuç'] == 'KAZANÇ (WIN)') & (df['SureDakika'] <= 2)]
print(f"\n2 dk ve altı süren KAZANÇ işlem sayısı: {len(very_short_wins)} / {len(df[df['Sonuç'] == 'KAZANÇ (WIN)'])}")

# Kaybedenlerin süreleri daha mı uzun?
from scipy import stats
t_stat, p_val = stats.ttest_ind(win_dur.dropna(), loss_dur.dropna())
print(f"\nKazanan vs Kaybeden süre t-testi: t={t_stat:.3f}, p={p_val:.4f}")

print("\n" + "=" * 70)
print("6. HARD GUARDRAIL KURALLARI DEĞERLENDİRMESİ")
print("=" * 70)
# Maksimum açık kalma süresi (örnek: 240 dk / 4 saat)
max_duration_threshold = 240
exceeded = df[df['SureDakika'] > max_duration_threshold]
print(f"{max_duration_threshold} dk (4 saat) üzerinde açık kalan işlem sayısı: {len(exceeded)}")
if len(exceeded) > 0:
    print(exceeded[['Parite', 'Yön', 'SureDakika', 'Sonuç', 'Kâr/Zarar (Pip)', 'Çıkış Nedeni']].to_string(index=False))

# Peş peşe 2+ stop sonrası cooldown kontrolü
# Önce zaman sırasına göre sırala
df['GirisZamaniDT'] = pd.to_datetime(df['Giriş Zamanı (UTC+3)'])
df_sorted = df.sort_values('GirisZamaniDT').reset_index(drop=True)

print("\n--- Peş peşe STOP (SL) sonrası COOLDOWN kontrolü ---")
for sym in df_sorted['Parite'].unique():
    for direction in ['BUY', 'SELL']:
        sub = df_sorted[(df_sorted['Parite'] == sym) & (df_sorted['Yön'] == direction)].copy()
        if len(sub) < 3:
            continue
        # stop çıkış nedenleri
        stop_reasons = ['🛑 Zarar Durdur (SL)', '🛑 Zarar (SL/Piyasa)']
        sub['IsStop'] = sub['Çıkış Nedeni'].isin(stop_reasons)
        sub['PrevIsStop'] = sub['IsStop'].shift(1)
        sub['PrevPrevIsStop'] = sub['IsStop'].shift(2)
        # 2 önceki işlem de stop ise ve bu işlem hemen (örn 30 dk içinde) açılmışsa
        sub['Consec2StopsBefore'] = sub['PrevIsStop'] & sub['PrevPrevIsStop']
        sub['TimeSincePrev'] = sub['GirisZamaniDT'].diff().dt.total_seconds() / 60
        suspicious = sub[(sub['Consec2StopsBefore'] == True) & (sub['TimeSincePrev'] <= 30)]
        if len(suspicious) > 0:
            print(f"\n{sym} {direction}: {len(suspicious)} işlem, 2 peş peşe stop sonrası 30 dk içinde tekrar girmiş:")
            print(suspicious[['GirisZamaniDT', 'Çıkış Nedeni', 'Sonuç', 'Kâr/Zarar (Pip)', 'SureDakika']].to_string(index=False))

print("\n" + "=" * 70)
print("7. DYNAMIC EXIT ARCHITECT VERİYE DAYALI GÖZLEMLER")
print("=" * 70)
print("SL/TP seviyeleri loglanmamış ('-'): Risk parametreleri görünürde sabit değil, dinamik veya log dışı.")
print("Çıkış nedenlerinin %89'u SL tabanlı. Bu, koruma odaklı ama muhtemelen sıkı stoplar olduğunu gösteriyor.")
print("Scalper Close sadece 6 işlem (%3.2): Dinamik/otomatik kâr alma mekanizması az kullanılmış.")
print("Büyük kayıpların varlığı (örn BTC -159 pip) sabit pip stoplarının volatiliteye uygun olmadığını düşündürüyor.")

print("\n" + "=" * 70)
print("8. ÖZET İSTATİSTİKLER")
print("=" * 70)
print(f"Toplam işlem: {len(df)}")
print(f"Genel kazanma oranı: {(df['Sonuç'] == 'KAZANÇ (WIN)').sum() / len(df) * 100:.1f}%")
print(f"Toplam Net Getiri (USD): {df['Net Getiri (USD)'].sum():.2f}")
print(f"Ortalama işlem getirisi (USD): {df['Net Getiri (USD)'].mean():.2f}")
print(f"Ortalama kazanç (pip): {wins.mean():.1f}")
print(f"Ortalama kayıp (pip): {losses.mean():.1f}")
print(f"Genel R/R oranı: {wins.mean() / abs(losses.mean()):.2f}")

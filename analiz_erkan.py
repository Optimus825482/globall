import pandas as pd
import numpy as np

# 1. CSV'yi oku ve dogrula
df = pd.read_csv(r'D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv', sep=';', encoding='utf-8')
print(f"Dosyadaki toplam islem sayisi: {len(df)}")
print(f"Sutunlar: {df.columns.tolist()}")
print()

# Tarih formatlarini duzelt (ISO format: 2026-10-09 20:20:50)
df['Giris Zamani (UTC+3)'] = pd.to_datetime(df['Giriş Zamanı (UTC+3)'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
df['Cikis Zamani (UTC+3)'] = pd.to_datetime(df['Çıkış Zamanı (UTC+3)'], format='%Y-%m-%d %H:%M:%S', errors='coerce')

# Sayisal sutunlari duzelt (nokta ondalik ayiraci)
df['Net Getiri (USD)'] = df['Net Getiri (USD)'].astype(float)
df['Kar/Zarar (Pip)'] = df['Kâr/Zarar (Pip)'].astype(float)

# Win/loss bool
df['is_win'] = df['Sonuç'].str.contains('KAZANÇ', na=False)
df['is_loss'] = df['Sonuç'].str.contains('KAYIP', na=False)

# Saat sutunu (UTC+3)
df['saat'] = df['Giris Zamani (UTC+3)'].dt.hour

# Sadece 2026-10-09 tarihli islemleri filtrele
df['tarih'] = df['Giris Zamani (UTC+3)'].dt.date
df = df[df['tarih'] == pd.to_datetime('2026-10-09').date()].copy()
print(f"2026-10-09 tarihli islem sayisi: {len(df)}")
print()

# Yardimci metrik fonksiyonu
def metrics(group_df):
    total = len(group_df)
    wins = group_df[group_df['is_win']]
    losses = group_df[group_df['is_loss']]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total * 100 if total > 0 else 0
    loss_rate = loss_count / total * 100 if total > 0 else 0
    net_usd = group_df['Net Getiri (USD)'].sum()
    pip_total = group_df['Kar/Zarar (Pip)'].sum()
    avg_win = wins['Net Getiri (USD)'].mean() if win_count > 0 else 0
    avg_loss = losses['Net Getiri (USD)'].mean() if loss_count > 0 else 0
    max_win = wins['Net Getiri (USD)'].max() if win_count > 0 else 0
    max_loss = losses['Net Getiri (USD)'].min() if loss_count > 0 else 0
    avg_win_pip = wins['Kar/Zarar (Pip)'].mean() if win_count > 0 else 0
    avg_loss_pip = losses['Kar/Zarar (Pip)'].mean() if loss_count > 0 else 0
    expectancy_usd = (win_rate/100 * avg_win) - (loss_rate/100 * abs(avg_loss))
    expectancy_pip = (win_rate/100 * avg_win_pip) - (loss_rate/100 * abs(avg_loss_pip))
    return {
        'Islem Sayisi': total,
        'Win': win_count,
        'Loss': loss_count,
        'Win Rate %': round(win_rate, 2),
        'Net Getiri USD': round(net_usd, 2),
        'Pip Toplam': round(pip_total, 2),
        'Ort Kazanc USD': round(avg_win, 2),
        'Ort Kayip USD': round(avg_loss, 2),
        'En Buyuk Kazanc USD': round(max_win, 2),
        'En Buyuk Kayip USD': round(max_loss, 2),
        'Expectancy USD': round(expectancy_usd, 2),
        'Expectancy Pip': round(expectancy_pip, 2)
    }

# 2. Parite bazinda
print("=" * 80)
print("PARITE BAZINDA PERFORMANS")
print("=" * 80)
pair_metrics = []
for parite in ['BTCUSD', 'XAUUSD', 'US30', 'GBPUSD']:
    sub = df[df['Parite'] == parite]
    if len(sub) > 0:
        m = metrics(sub)
        pair_metrics.append((parite, m))
        print(f"\n{parite}:")
        for k, v in m.items():
            print(f"  {k}: {v}")

# 3. Yon bazinda
print("\n" + "=" * 80)
print("YON BAZINDA PERFORMANS")
print("=" * 80)
for yon in ['BUY', 'SELL']:
    sub = df[df['Yön'] == yon]
    if len(sub) > 0:
        m = metrics(sub)
        print(f"\n{yon}:")
        for k, v in m.items():
            print(f"  {k}: {v}")

# 4. Saat bazinda dagilim
print("\n" + "=" * 80)
print("SAAT BAZINDA DAGILIM (UTC+3)")
print("=" * 80)
saat_df = df.groupby('saat').agg(
    Islem=('Bilet No', 'count'),
    Win=('is_win', 'sum'),
    Loss=('is_loss', 'sum'),
    Net_USD=('Net Getiri (USD)', 'sum'),
    Pip_Toplam=('Kar/Zarar (Pip)', 'sum')
).reset_index()
saat_df['Win Rate %'] = (saat_df['Win'] / saat_df['Islem'] * 100).round(2)
saat_df = saat_df.sort_values('saat')
print(saat_df.to_string(index=False))

# 5. Cikis nedeni dagilimi
print("\n" + "=" * 80)
print("CIKIS NEDENI DAGILIMI")
print("=" * 80)
exit_df = df.groupby('Çıkış Nedeni').agg(
    Islem=('Bilet No', 'count'),
    Win=('is_win', 'sum'),
    Loss=('is_loss', 'sum'),
    Net_USD=('Net Getiri (USD)', 'sum'),
    Pip_Toplam=('Kar/Zarar (Pip)', 'sum')
).reset_index()
exit_df['Win Rate %'] = (exit_df['Win'] / exit_df['Islem'] * 100).round(2)
exit_df = exit_df.sort_values('Islem', ascending=False)
print(exit_df.to_string(index=False))

# 6. Kumulatif zaman serisi ve max drawdown
print("\n" + "=" * 80)
print("KUMULATIF NET GETIRI VE DRAWDOWN")
print("=" * 80)
df_sorted = df.sort_values('Giris Zamani (UTC+3)').reset_index(drop=True)
df_sorted['kumulatif'] = df_sorted['Net Getiri (USD)'].cumsum()
running_max = df_sorted['kumulatif'].cummax()
drawdown = df_sorted['kumulatif'] - running_max
max_drawdown = drawdown.min()
max_dd_idx = drawdown.idxmin()
peak_idx = running_max.iloc[:max_dd_idx+1].idxmax()
print(f"Son kumulatif getiri: {df_sorted['kumulatif'].iloc[-1]:.2f} USD")
print(f"Maksimum Drawdown: {max_drawdown:.2f} USD")
print(f"Peak zaman: {df_sorted.loc[peak_idx, 'Giris Zamani (UTC+3)']}")
print(f"Trough zaman: {df_sorted.loc[max_dd_idx, 'Giris Zamani (UTC+3)']}")

# 7. Genel expectancy
print("\n" + "=" * 80)
print("GENEL EXPECTANCY")
print("=" * 80)
genel = metrics(df)
print(f"Genel Expectancy USD: {genel['Expectancy USD']}")
print(f"Genel Expectancy Pip: {genel['Expectancy Pip']}")

# 8. Ozet
print("\n" + "=" * 80)
print("OZET")
print("=" * 80)
print(f"Toplam islem: {genel['Islem Sayisi']}")
print(f"Win: {genel['Win']} | Loss: {genel['Loss']} | Win Rate: {genel['Win Rate %']}%")
print(f"Toplam Net Getiri: {genel['Net Getiri USD']} USD")
print(f"Toplam Pip: {genel['Pip Toplam']}")
print(f"Ortalama Kazanc: {genel['Ort Kazanc USD']} USD")
print(f"Ortalama Kayip: {genel['Ort Kayip USD']} USD")
print(f"En Buyuk Kazanc: {genel['En Buyuk Kazanc USD']} USD")
print(f"En Buyuk Kayip: {genel['En Buyuk Kayip USD']} USD")
print(f"Max Drawdown: {max_drawdown:.2f} USD")

pair_results = {p: m['Net Getiri USD'] for p, m in pair_metrics}
kazananlar = sorted([p for p, v in pair_results.items() if v > 0], key=lambda x: pair_results[x], reverse=True)
zarar_edenler = sorted([p for p, v in pair_results.items() if v < 0], key=lambda x: pair_results[x])
print(f"Kazandiran pariteler: {', '.join(kazananlar) if kazananlar else 'Yok'}")
print(f"Zarar ettiren pariteler: {', '.join(zarar_edenler) if zarar_edenler else 'Yok'}")

print(f"\nEn karli saat: {int(saat_df.loc[saat_df['Net_USD'].idxmax(), 'saat'])}:00 ({saat_df['Net_USD'].max():.2f} USD)")
print(f"En zararli saat: {int(saat_df.loc[saat_df['Net_USD'].idxmin(), 'saat'])}:00 ({saat_df['Net_USD'].min():.2f} USD)")
print(f"En yuksek win rate saati: {int(saat_df.loc[saat_df['Win Rate %'].idxmax(), 'saat'])}:00 (%{saat_df['Win Rate %'].max()})")

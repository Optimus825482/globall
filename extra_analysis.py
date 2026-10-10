import pandas as pd
import numpy as np
import re

file_path = r"D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv"
df = pd.read_csv(file_path, sep=';', quotechar='"')

def sure_to_minutes(s):
    if pd.isna(s):
        return np.nan
    s = str(s).strip()
    pattern = r'(?:(\d+)\s*sa(?:at)?)?\s*(?:(\d+)\s*dk)?\s*(?:(\d+)\s*sn)?'
    m = re.match(pattern, s)
    if not m:
        return np.nan
    hours = int(m.group(1)) if m.group(1) else 0
    mins = int(m.group(2)) if m.group(2) else 0
    secs = int(m.group(3)) if m.group(3) else 0
    return hours * 60 + mins + secs / 60.0

df['SureDakika'] = df['Süre'].apply(sure_to_minutes)

# SL ile kapanan işlemlerin kazanç/kayıp dağılımı
sl_reasons = ['🛑 Zarar Durdur (SL)', '🛑 Zarar (SL/Piyasa)']
sl_trades = df[df['Çıkış Nedeni'].isin(sl_reasons)]
print('SL ile kapanan toplam işlem:', len(sl_trades))
print('Bunların sonuç dağılımı:')
print(sl_trades['Sonuç'].value_counts())
print('\nYüzde:')
print((sl_trades['Sonuç'].value_counts(normalize=True) * 100).round(1))

print('\nSL ile kapanan KAZANÇ işlemlerinin pip dağılımı:')
sl_wins = sl_trades[sl_trades['Sonuç'] == 'KAZANÇ (WIN)']['Kâr/Zarar (Pip)']
print(sl_wins.describe())

print('\nSL ile kapanan KAYIP işlemlerinin pip dağılımı:')
sl_losses = sl_trades[sl_trades['Sonuç'] == 'KAYIP (LOSS)']['Kâr/Zarar (Pip)']
print(sl_losses.describe())

print('\nParite bazında SL ile kapanan kazanç/kayıp sayıları:')
print(sl_trades.groupby(['Parite', 'Sonuç']).size().unstack(fill_value=0))

print('\nScalper Close ile kapanan işlemler:')
sc = df[df['Çıkış Nedeni'] == 'Scalper Close']
print(sc[['Parite', 'Yön', 'Süre', 'Kâr/Zarar (Pip)', 'Sonuç']].to_string(index=False))

print('\nTP ile kapanan işlemler:')
tp = df[df['Çıkış Nedeni'] == '🎯 Kâr Al (TP)']
print(tp.groupby('Parite').size())
print(tp[['Parite', 'Yön', 'Süre', 'Kâr/Zarar (Pip)', 'Sonuç']].to_string(index=False))

# Pip farkı ile Kâr/Zarar (Pip) arasındaki farkın kontrolü
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
    return diff / mult

df['HesaplananPipFarki'] = df.apply(compute_pip_diff, axis=1)
df['PipFarkFarki'] = df['Kâr/Zarar (Pip)'] - df['HesaplananPipFarki']
print('\nKâr/Zarar(Pip) ile Hesaplanan Pip Farkı arasındaki fark:')
print(df['PipFarkFarki'].describe())
print('\nİlk 10 farklı olan:')
print(df[['Parite', 'Yön', 'Lot', 'Giriş Fiyatı', 'Çıkış Fiyatı', 'Kâr/Zarar (Pip)', 'HesaplananPipFarki', 'PipFarkFarki']].head(10).to_string(index=False))

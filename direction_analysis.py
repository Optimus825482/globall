import pandas as pd
file_path = r"D:\scalperagent_global\forex_scalper_islemler_2026-10-10.csv"
df = pd.read_csv(file_path, sep=';', quotechar='"')
print('Parite + Yön bazinda sonuc:')
print(df.groupby(['Parite', 'Yön', 'Sonuç']).size().unstack(fill_value=0))
print('\nParite + Yön bazinda ortalama Kar/Zarar (Pip):')
print(df.groupby(['Parite', 'Yön'])['Kâr/Zarar (Pip)'].mean().round(1))
print('\nParite + Yön bazinda toplam Kar/Zarar (Pip):')
print(df.groupby(['Parite', 'Yön'])['Kâr/Zarar (Pip)'].sum().round(1))
print('\nParite + Yön bazinda Net Getiri (USD) toplami:')
print(df.groupby(['Parite', 'Yön'])['Net Getiri (USD)'].sum().round(2))

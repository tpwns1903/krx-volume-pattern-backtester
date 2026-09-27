import sys
sys.path.insert(0, '.')
import pandas as pd
from src.patterns.volume_pattern import VolumeInflowDeclinePattern

def make_ohlcv(volumes, start='2024-01-01'):
    n = len(volumes)
    dates = pd.date_range(start=start, periods=n, freq='B')
    return pd.DataFrame({
        'date': dates,
        'open': [10000] * n,
        'high': [10500] * n,
        'low': [9500] * n,
        'close': [10000] * n,
        'volume': volumes,
    })

base_vols = [1000] * 25
vols = base_vols + [2100, 2500, 2000, 1500, 5000]
df = make_ohlcv(vols)

# Step-by-step trace
df2 = df.copy().reset_index(drop=True)
df2['ma_vol'] = df2['volume'].shift(1).rolling(window=20).mean()

ma_window = 20
multiplier = 2.0
phase2_min = 1
phase2_max = 3
min_vol = 10000  # <--- CHECK THIS!

print('min_volume check:')
print(f'  day1_vol = 2100, min_vol = {min_vol}')
print(f'  day1_vol < min_vol? {2100 < min_vol}')
print('-> min_volume=10000 is blocking signals with day1 vol=2100!')

"""调试 get_multi_close"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import get_data, generate_synthetic, YAHOO_TICKERS
import pandas as pd

tickers = ['GC=F', 'CL=F', 'HG=F', 'GLD']
closes = {}
for t in tickers:
    df, src = get_data(t, '2y')
    print(f'{t}: {len(df)} rows, src={src}, idx[0]={df.index[0].date()}, idx[-1]={df.index[-1].date()}')
    closes[t] = df['Close']

close_df = pd.DataFrame(closes)
print(f'\nBefore dropna: {close_df.shape}')
print(f'NaN counts: {close_df.isna().sum().to_dict()}')
thresh = int(len(close_df) * 0.8)
print(f'thresh={thresh}')
close_df2 = close_df.dropna(thresh=thresh)
print(f'After dropna(thresh={thresh}): {close_df2.shape}')

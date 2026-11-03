"""IC / Rank IC labels and diagnostics only; no portfolio execution or return metrics."""
import numpy as np
import pandas as pd
from src.core.config_validator import KEYS


def factor_analysis(processed, market, calendar, config):
    # 输入因子、行情、交易日历 -> 股票因子明细与日频 IC；分层成交由执行框架处理。
    """Exact t -> t+1 labels and IC / Rank IC diagnostics."""
    prices = market.pivot(index='trade_date', columns='stock_code', values='close_post').reindex(calendar)
    labels = (prices.shift(-1) / prices - 1).stack(future_stack=True)#pivot，计算收益率
    labels.index.names = KEYS
    out = processed.dropna(subset=['factor_value']).sort_values(
        ['trade_date', 'factor_value', 'stock_code'], ascending=[True, False, True]).copy()
    out['forward_ret_1d'] = labels.reindex(pd.MultiIndex.from_frame(out[KEYS])).to_numpy()
    rows = []
    for day, group in out.groupby('trade_date'):
        valid = group[['factor_value', 'forward_ret_1d']].replace([np.inf, -np.inf], np.nan).dropna()
        row = {'trade_date': day, 'n': len(valid), 'ic_raw': np.nan, 'rank_ic_raw': np.nan}
        if len(valid) >= config['factor']['min_cross_section']:
            row['ic_raw'] = valid.factor_value.corr(valid.forward_ret_1d)
            row['rank_ic_raw'] = valid.factor_value.corr(valid.forward_ret_1d, method='spearman')
        rows.append(row)#计算评估指标
    ic = pd.DataFrame(rows).set_index('trade_date').loc[config['start_date']:config['end_date']]
    for name in ['ic', 'rank_ic']:#缩尾
        s = ic[f'{name}_raw']
        lo, hi = s.dropna().quantile([config['ic']['lower_quantile'], config['ic']['upper_quantile']], interpolation='linear')
        ic[name] = s.clip(lo, hi) if config['ic']['winsorize'] else s
    return out, ic

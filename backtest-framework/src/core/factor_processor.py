"""Load a trusted factor-value module, verify its identities and preprocess its values."""
import importlib

import numpy as np
import pandas as pd

from src.core.config_validator import KEYS


def load_factor(config):
    module_name = config['factor']['module']
    if not isinstance(module_name, str) or not module_name.strip():
        raise ValueError('factor.module 必须指定独立的 Python 因子模块。')
    module = importlib.import_module(module_name)
    if not isinstance(getattr(module, 'FACTOR_ID', None), str) or not module.FACTOR_ID.strip():
        raise ValueError('因子模块必须声明非空 FACTOR_ID。')
    columns = getattr(module, 'REQUIRED_COLUMNS', None)
    if not isinstance(columns, (tuple, list)) or not all(isinstance(c, str) and c for c in columns):
        raise ValueError('因子模块必须声明 REQUIRED_COLUMNS 字段列表。')
    if not callable(getattr(module, 'calculate_factor', None)):
        raise ValueError('因子模块必须提供 calculate_factor(data, parameters)。')
    return module


def calculate_factor_values(data, factor_module, parameters):
    """Accept only date/code/factor_raw from the plugin; preserve the original input prices."""
    missing = set(factor_module.REQUIRED_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError('因子输入缺少字段：' + ', '.join(sorted(missing)))
    output = factor_module.calculate_factor(data.copy(deep=True), dict(parameters))
    if not isinstance(output, pd.DataFrame) or not set(KEYS + ['factor_raw']).issubset(output.columns):
        raise ValueError('因子输出必须含 trade_date、stock_code、factor_raw 三列。')
    output = output[KEYS + ['factor_raw']].copy()
    output['trade_date'] = pd.to_datetime(output.trade_date, errors='raise')
    if output.duplicated(KEYS).any():
        raise ValueError('因子输出存在重复日期／证券身份。')
    expected = pd.MultiIndex.from_frame(data[KEYS])
    actual = pd.MultiIndex.from_frame(output[KEYS])
    if len(actual) != len(expected) or len(actual.difference(expected)) or len(expected.difference(actual)):
        raise ValueError('因子输出身份与输入不一致；缺失因子值应保留原行并使用 NaN。')
    output['factor_raw'] = pd.to_numeric(output.factor_raw, errors='raise')
    return data.merge(output, on=KEYS, how='left', validate='one_to_one')


def process_factor(market, universe, factor_module, config):
    # Calculate on configured warmup history first; preprocess only current dynamic members.
    values = calculate_factor_values(market, factor_module, config['factor'].get('parameters', {}))
    panel = universe.merge(values, on=KEYS, how='left', validate='one_to_one')
    panel['market_capital'] = np.log(panel.market_cap_cny.where(panel.market_cap_cny > 0))
    panel['sector'] = panel.sw_level1
    eligible = (panel.is_st.eq(False) & panel.is_special_risk.eq(False)
                & panel.is_suspended_full_day.eq(False) & panel.trade_status.isin(['交易', 'XD', 'XR', 'DR', 'N'])
                & panel.listed_trade_day_number.ge(60) & np.isfinite(panel.factor_raw)
                & panel.close_post.gt(0) & np.isfinite(panel.market_capital) & panel.sector.notna())
    return preprocess_factor(panel.loc[eligible].sort_values(KEYS).reset_index(drop=True), config['factor'])


def preprocess_factor(frame, config):
    #预处理，传入df[交易日期，代码，原始因子值，市值对数，行业] -> [处理值*3]
    data = frame.copy()
    data['factor_value'] = data.factor_raw.replace([np.inf, -np.inf], np.nan)
    if config['mad_enabled']:#mad
        for _, index in data.groupby('trade_date').groups.items():
            s = data.loc[index, 'factor_value'].dropna()
            median = s.median()
            mad = (s - median).abs().median()
            if len(s) >= 3 and mad > 0:
                width = config['mad_threshold'] * mad
                data.loc[index, 'factor_value'] = s.clip(median - width, median + width)
    data['factor_winsorized'] = data.factor_value
    for _, index in data.groupby('trade_date').groups.items():#联合中性化ols回归
        group = data.loc[index].dropna(subset=['factor_value', 'market_capital', 'sector']).sort_values('stock_code')
        data.loc[index, 'factor_value'] = np.nan
        if len(group) < config['min_cross_section']:
            continue
        y = group.factor_value.astype(float)
        if config['neutralization_enabled']:
            x = pd.concat([group.market_capital, pd.get_dummies(group.sector.astype(str), drop_first=True)], axis=1).astype(float)
            x = x.loc[:, x.nunique() > 1]
            x = np.column_stack([np.ones(len(x)), x.values])
            if len(y) <= x.shape[1]:
                raise ValueError('中性化截面自由度不足')
            beta, *_ = np.linalg.lstsq(x, y.values, rcond=None)
            y = pd.Series(y.values - x @ beta, index=y.index)
        if config['normalization_enabled']:
            y = (y - y.mean()) / y.std() if y.std() > 1e-14 else y * 0
        data.loc[y.index, 'factor_value'] = y
    return data

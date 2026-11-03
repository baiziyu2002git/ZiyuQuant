"""Cross-sectional grouping, rebalance scheduling and long-short research spread."""
import pandas as pd
from src.core.config_validator import DEFAULT_REBALANCE_PERIOD
from src.core.data_loader import load_execution_data
from src.backtest.execution_engine import simulate_portfolios
import numpy as np


def assign_quantiles(factor, groups):
    data = factor.dropna(subset=['factor_value']).sort_values(
        ['trade_date', 'factor_value', 'stock_code'], ascending=[True, False, True], kind='mergesort').copy()
    data['quantile'] = data.groupby('trade_date').factor_value.transform(
        lambda s: pd.qcut(np.arange(len(s)), min(groups, len(s)), labels=False) + 1).astype(int)
    return data


def run_quantile_backtest(factor, config):
    period = config['backtest']['rebalance_config'].get('rebalance_period', DEFAULT_REBALANCE_PERIOD)
    groups = config['groups']
    dates = pd.DatetimeIndex(factor.trade_date.unique()).sort_values()[::period]
    targets = assign_quantiles(factor.loc[factor.trade_date.isin(dates)], groups)
    market, calendar = load_execution_data(config, factor)
    cost = config['transaction_cost']
    rate = cost['fee_rate'] + cost['slippage'] if cost['enabled'] else 0.
    execution = simulate_portfolios(targets, market, calendar, groups, rate)
    gross, net = execution['gross_returns'], execution['net_returns']
    long_col, short_col = 'Q1_ret', f'Q{groups}_ret'
    ls_gross = gross[long_col] - gross[short_col]
    ls_net = ls_gross - execution['cost_returns'][long_col] - execution['cost_returns'][short_col]
    ls_net.name = 'long_short_net_ret'
    return {'quantile_returns': gross, 'net_quantile_returns': net,
            'long_short_portfolio': {'returns': ls_gross}, 'long_short_net_returns': ls_net,
            'execution': execution,
            'summary_stats': {'execution_enabled': True, 'rebalance_period': period, 'periods_per_year': 252}}

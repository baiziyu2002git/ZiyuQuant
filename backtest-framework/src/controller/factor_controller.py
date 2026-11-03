"""Generic orchestration: factor values -> IC -> execution -> metrics -> saved outputs."""
from pathlib import Path

import pandas as pd

from src.core.config_validator import ROOT, KEYS, DEFAULT_REBALANCE_PERIOD
from src.core.data_loader import load_project_data
from src.core.factor_processor import load_factor, process_factor
from src.backtest.signal_analyzer import factor_analysis
from src.backtest.quantile_calculator import assign_quantiles, run_quantile_backtest
from src.backtest.metric_calculator import compound_monthly, calculate_return_metrics
from src.backtest.chart_generator import create_figures


def run_research(config):
    """Run IC diagnostics and executed quantile portfolios; save only calculation outputs."""
    print('[1/3] Loading input data and computing IC...', flush=True)
    factor_module = load_factor(config)
    market, universe, benchmark = load_project_data(config, factor_module.REQUIRED_COLUMNS)
    processed = process_factor(market, universe, factor_module, config)
    calendar = benchmark.loc[config['warmup_start']:config['end_date']].index
    if processed.empty or calendar.empty:
        raise ValueError('所选日期没有可用因子样本或基准交易日历。')
    factor, ic = factor_analysis(processed, market, calendar, config)
    factor = assign_quantiles(factor.loc[factor.trade_date >= pd.Timestamp(config['start_date'])], config['groups'])
    if factor.empty:
        raise ValueError('研究区间没有通过筛选的因子样本。')
    factor['is_evaluation_signal'] = factor.trade_date.ge(pd.Timestamp(config['start_date']))
    print('[2/3] Running quantile portfolio execution...', flush=True)
    quantile_results = run_quantile_backtest(factor, config)
    execution = quantile_results['execution']
    names = {f'Q{i}_ret': f'Q{i}' for i in range(1, config['groups'] + 1)}
    daily = quantile_results['net_quantile_returns'].rename(columns=names).copy()
    daily['long_short'] = quantile_results['long_short_net_returns']
    gross = quantile_results['quantile_returns'].rename(columns=names).copy()
    gross['long_short'] = quantile_results['long_short_portfolio']['returns']
    turnover = execution['turnover'].rename(columns=names).copy()
    costs = execution['cost_returns'].rename(columns=names).copy()
    for frame in (turnover, costs):
        frame['long_short'] = frame.Q1 + frame[f'Q{config["groups"]}']
    period = config['backtest']['rebalance_config'].get('rebalance_period', DEFAULT_REBALANCE_PERIOD)
    signal_dates = pd.DatetimeIndex(factor.trade_date.unique()).sort_values()[::period]
    factor['is_rebalance_signal'] = factor.trade_date.isin(signal_dates)
    first_position = calendar.get_loc(daily.index[0])
    initial_date = calendar[first_position - 1] if first_position > 0 else daily.index[0] - pd.Timedelta(days=1)
    daily['benchmark'] = benchmark.close.pct_change(fill_method=None).reindex(daily.index)
    monthly = compound_monthly(daily)
    summary = pd.DataFrame([{**calculate_return_metrics(daily.long_short), 'factor': factor_module.FACTOR_ID,
        'ic': ic.ic.mean(), 'rank_ic': ic.rank_ic.mean(), 'icir': ic.ic.mean() / ic.ic.std(),
        'rank_icir': ic.rank_ic.mean() / ic.rank_ic.std(), 'trade_days': len(daily), 'months': len(monthly),
        'rebalance_period': period,
        'upper_limit_blocked_orders': int(execution['orders'].reason.eq('upper_limit').sum()),
        'lower_limit_blocked_orders': int(execution['orders'].reason.eq('lower_limit').sum())}])
    quantile_metrics = pd.DataFrame([{'portfolio': col, **calculate_return_metrics(daily[col])}
        for col in [f'Q{i}' for i in range(1, config['groups'] + 1)] + ['long_short', 'benchmark']])
    #保存结果
    print('[3/3] Writing calculation results and figures...', flush=True)
    output = ROOT / Path(config['results_dir']).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(KEYS + ['close_post'] + list(factor_module.REQUIRED_COLUMNS)
        + ['factor_raw', 'factor_winsorized', 'factor_value', 'market_capital', 'sector', 'quantile',
           'forward_ret_1d', 'is_evaluation_signal', 'is_rebalance_signal']))
    factor[columns].to_parquet(output / 'factor_values.parquet', index=False)
    for name, frame in [('daily_ic', ic), ('daily_returns', daily), ('gross_daily_returns', gross),
                        ('turnover', turnover), ('cost_returns', costs),
                        ('monthly_returns', monthly)]:
        frame.to_csv(output / f'{name}.csv', index_label='month' if name.startswith('monthly') else 'trade_date')
    for name, frame in [('summary', summary), ('quantile_metrics', quantile_metrics)]:
        frame.to_csv(output / f'{name}.csv', index=False)
    for name in ('ledger', 'orders', 'positions'):
        execution[name].to_parquet(output / f'execution_{name}.parquet', index=False)
    create_figures(output, daily, monthly, ic, initial_date, config['groups'])
    print(summary.to_string(index=False))
    return {'factor_values': factor, 'daily_ic': ic, 'daily_returns': daily,
            'summary': summary, 'quantile_metrics': quantile_metrics, 'execution': execution}

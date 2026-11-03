"""Read only the four configured data inputs; no factor formula or performance logic."""
from pathlib import Path
import pandas as pd

from src.core.config_validator import ROOT, KEYS
from src.backtest.execution_engine import classify_execution_status

def read_partitions(folder, columns, start, end, codes=None):
    # 输入：分区目录、所需列、起止日期、可选股票代码 -> 输出：筛选并合并后的 DataFrame
    frames = []
    filters = [('trade_date', '>=', start.date()), ('trade_date', '<=', end.date())]
    if codes is not None:
        filters.append(('stock_code', 'in', list(codes)))
    folder = Path(folder)
    paths = [folder] if folder.is_file() else sorted(folder.glob('*/data_0.parquet'))
    for path in paths:
        if '=' in path.parent.name and not start.year <= int(path.parent.name.split('=')[-1]) <= end.year:
            continue
        frames.append(pd.read_parquet(path, columns=columns, filters=filters))
    if not frames:
        raise ValueError('未找到 Parquet 输入；请核对配置的数据字段、文件格式及日期覆盖。')
    result = pd.concat(frames, ignore_index=True)
    result['trade_date'] = pd.to_datetime(result.trade_date)
    return result


def data_path(config, key):
    """All external inputs come exclusively from named YAML fields."""
    root = Path(config['data_root']).expanduser()
    if not root.is_absolute():
        root = ROOT / root
    path = root / Path(config['data_paths'][key]).expanduser()
    if not path.exists():
        raise FileNotFoundError(f'未找到 data_paths.{key} 对应的数据文件或目录。')
    return path


def load_project_data(config, factor_columns):
    """Load warmup history, dynamic membership and benchmark without computing a factor."""
    warmup, end = pd.Timestamp(config['warmup_start']), pd.Timestamp(config['end_date'])
    benchmark = pd.read_parquet(data_path(config, 'benchmark'), columns=['trade_date', 'close'])
    benchmark.trade_date = pd.to_datetime(benchmark.trade_date)
    benchmark = benchmark.set_index('trade_date').sort_index()
    universe = pd.read_parquet(data_path(config, 'universe'), columns=KEYS)
    universe.trade_date = pd.to_datetime(universe.trade_date)
    universe = universe[universe.trade_date.between(warmup, end)]
    columns = list(dict.fromkeys(KEYS + ['close_post', 'market_cap_cny', 'sw_level1',
        'is_st', 'is_special_risk', 'is_suspended_full_day', 'listed_trade_day_number'] + list(factor_columns)))
    market = read_partitions(data_path(config, 'market_data'), columns, warmup, end, universe.stock_code.unique())
    status = read_partitions(data_path(config, 'status_data'), KEYS + ['trade_status'], warmup, end, universe.stock_code.unique())
    market = market.merge(status, on=KEYS, how='outer', validate='one_to_one')
    return market.sort_values(KEYS).reset_index(drop=True), universe, benchmark


def load_execution_data(config, factor):
    #读取合并数据（mrkt+status）
    start, end = factor.trade_date.agg(['min', 'max'])
    codes = factor.stock_code.unique()
    market = read_partitions(data_path(config, 'market_data'), KEYS + [
        'close_raw', 'close_post', 'is_suspended_full_day', 'is_intraday_halt'], start, end, codes)
    status = read_partitions(data_path(config, 'status_data'), KEYS + [
        'high_limit', 'low_limit', 'trade_status'], start, end, codes)
    market = market.merge(status, on=KEYS, how='outer', validate='one_to_one')
    market.loc[market.trade_status.eq('停牌'), 'is_suspended_full_day'] = True
    market = classify_execution_status(market)
    benchmark = pd.read_parquet(data_path(config, 'benchmark'), columns=['trade_date', 'close'])
    benchmark.trade_date = pd.to_datetime(benchmark.trade_date)#获取交易日历
    benchmark = benchmark.set_index('trade_date').close.sort_index().loc[start:end]
    return market, benchmark.index

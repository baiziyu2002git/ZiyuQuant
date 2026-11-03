"""Portable YAML input validation."""
from pathlib import Path
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
KEYS = ["trade_date", "stock_code"]
DEFAULT_REBALANCE_PERIOD = 5


def load_config(path):
    """Read portable YAML; reference labels are documentation, not usable data paths."""
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(config.get('data_paths'), dict):
        raise ValueError('配置必须包含 data_paths 数据字段映射。')
    fields = {'data_root': config.get('data_root'), 'results_dir': config.get('results_dir')}
    fields.update({f'data_paths.{key}': config['data_paths'].get(key)
                   for key in ('market_data', 'status_data', 'universe', 'benchmark')})
    missing = [key for key, value in fields.items()
               if not isinstance(value, str) or not value.strip() or value.strip().startswith('参考')]
    if missing:
        raise ValueError('尚未配置数据字段：' + ', '.join(missing) + '；请用自备数据替换参考说明。')
    for key in ('warmup_start', 'start_date', 'end_date'):
        config[key] = str(pd.Timestamp(config[key]).date())
    if not config['warmup_start'] <= config['start_date'] <= config['end_date']:
        raise ValueError('日期须满足 warmup_start <= start_date <= end_date。')
    period = config['backtest']['rebalance_config'].get('rebalance_period', DEFAULT_REBALANCE_PERIOD)
    if type(period) is not int or period < 1:
        raise ValueError('rebalance_period 必须为正整数交易日数。')
    if type(config.get('groups')) is not int or config['groups'] < 2:
        raise ValueError('groups 必须为至少 2 的整数。')
    factor = config.get('factor', {})
    if not isinstance(factor.get('module'), str) or not factor['module'].strip():
        raise ValueError('factor.module 必须指定独立的 Python 因子模块。')
    if not isinstance(factor.get('parameters', {}), dict):
        raise ValueError('factor.parameters 必须为参数映射。')
    return config

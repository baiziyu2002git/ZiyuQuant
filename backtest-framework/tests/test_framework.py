"""Deterministic toy-data checks; these are not investment-performance evidence."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config_validator import load_config
from src.controller.factor_controller import run_research
from src.backtest.signal_analyzer import factor_analysis
from src.backtest.execution_engine import classify_execution_status, simulate_portfolios


def small_config():
    return {
        'data_root': '', 'data_paths': {},
        'start_date': '2024-01-02', 'end_date': '2024-01-11', 'warmup_start': '2024-01-02',
        'groups': 2, 'backtest': {'rebalance_config': {'rebalance_period': 2}},
        'transaction_cost': {'enabled': False, 'fee_rate': 0.0, 'slippage': 0.0},
        'factor': {'module': 'factor_lib.qlib013', 'parameters': {}, 'mad_enabled': True, 'mad_threshold': 3.0, 'neutralization_enabled': False,
                   'normalization_enabled': True, 'min_cross_section': 2},
        'ic': {'winsorize': False, 'lower_quantile': 0.01, 'upper_quantile': 0.99},
        'results_dir': 'results/test',
    }


def execution_fixture():
    dates = pd.date_range('2024-01-02', periods=3, freq='B')
    rows = [dict(trade_date=day, stock_code=stock, close_raw=price, close_post=price,
                 high_limit=20.0, low_limit=1.0, trade_status='交易',
                 is_suspended_full_day=False, is_intraday_halt=False)
            for day, prices in zip(dates, [[10.0, 10.0], [10.0, 10.0], [11.0, 9.0]])
            for stock, price in zip(['A', 'B'], prices)]
    targets = pd.DataFrame({'trade_date': [dates[0], dates[0]], 'stock_code': ['A', 'B'], 'quantile': [1, 2]})
    return dates, pd.DataFrame(rows), targets


class CoreCalculationTests(unittest.TestCase):
    def test_ic_uses_exact_next_calendar_day_without_filling_gaps(self):
        dates = pd.date_range('2024-01-02', periods=3, freq='B')
        market = pd.DataFrame([
            dict(trade_date=day, stock_code=stock, close_post=price)
            for day, prices in zip(dates, [[100, 100, 100, 100], [110, 120, 90, np.nan], [121, 108, 99, 100]])
            for stock, price in zip(['A', 'B', 'C', 'D'], prices)
        ])
        processed = market[['trade_date', 'stock_code']].copy()
        processed['factor_value'] = [1.0, 2.0, -1.0, 9.0] * 3
        panel, ic = factor_analysis(processed, market, dates, small_config())
        panel = panel.set_index(['trade_date', 'stock_code'])
        self.assertAlmostEqual(ic.loc[dates[0], 'ic_raw'], 1.0)
        self.assertAlmostEqual(ic.loc[dates[0], 'rank_ic_raw'], 1.0)
        self.assertEqual(ic.loc[dates[0], 'n'], 3)
        self.assertTrue(pd.isna(panel.loc[(dates[0], 'D'), 'forward_ret_1d']))
        self.assertTrue(pd.isna(panel.loc[(dates[1], 'D'), 'forward_ret_1d']))
        self.assertEqual(ic.loc[dates[2], 'n'], 0)
        self.assertTrue(pd.isna(ic.loc[dates[2], 'ic_raw']))

    def test_signal_executes_next_day_and_preserves_cash_and_holdings(self):
        dates, market, targets = execution_fixture()
        result = simulate_portfolios(targets, classify_execution_status(market), dates, 2, 0.0)
        np.testing.assert_allclose(result['net_returns']['Q1_ret'], [0.0, 0.0, 0.1], atol=1e-14)
        np.testing.assert_allclose(result['net_returns']['Q2_ret'], [0.0, 0.0, -0.1], atol=1e-14)
        self.assertTrue(result['orders']['trade_date'].eq(dates[1]).all())
        self.assertTrue(result['orders']['signal_date'].eq(dates[0]).all())
        self.assertTrue(result['positions']['trade_date'].ne(dates[0]).all())
        ledger = result['ledger']
        np.testing.assert_allclose(ledger.nav, ledger.cash + ledger.holdings_value, atol=1e-14)

    def test_price_limits_and_suspensions_keep_directional_restrictions(self):
        _, market, _ = execution_fixture()
        market = market.iloc[:3].copy()
        market['close_raw'] = [20.0, 1.0, 10.0]
        market.loc[market.index[2], 'is_suspended_full_day'] = True
        status = classify_execution_status(market)
        self.assertEqual(status.can_buy.tolist(), [False, True, False])
        self.assertEqual(status.can_sell.tolist(), [True, False, False])
        self.assertEqual(status.iloc[0].buy_reason, 'upper_limit')
        self.assertEqual(status.iloc[1].sell_reason, 'lower_limit')
        self.assertEqual(status.iloc[2].buy_reason, 'suspended')

    def test_fees_reduce_both_sides_of_research_spread(self):
        dates, market, targets = execution_fixture()
        result = simulate_portfolios(targets, classify_execution_status(market), dates, 2, 0.02)
        expected_cost = 1.0 / 101.0
        np.testing.assert_allclose(result['cost_returns'].iloc[1], [expected_cost, expected_cost], atol=1e-14)
        np.testing.assert_allclose(result['net_returns'].iloc[1], [-expected_cost, -expected_cost], atol=1e-14)
        spread = result['gross_returns'].Q1_ret - result['gross_returns'].Q2_ret - result['cost_returns'].sum(axis=1)
        self.assertAlmostEqual(spread.iloc[1], -2.0 / 101.0)
        self.assertAlmostEqual(result['orders'].fee.sum(), 2.0 / 101.0)

    def test_unconfirmed_missing_holding_price_fails_instead_of_zeroing_assets(self):
        dates, market, targets = execution_fixture()
        market.loc[(market.trade_date == dates[2]) & market.stock_code.eq('A'), 'close_post'] = np.nan
        with self.assertRaisesRegex(ValueError, '持仓缺少可靠估值'):
            simulate_portfolios(targets, classify_execution_status(market), dates, 2, 0.0)


class PublicationInterfaceTests(unittest.TestCase):
    def test_reference_config_fails_before_reading_data_or_creating_results(self):
        with self.assertRaisesRegex(ValueError, '尚未配置.*data_root'):
            load_config(ROOT / 'config/config.yaml')

    def test_output_reference_is_rejected_before_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = small_config()
            config['data_root'] = 'inputs'
            config['data_paths'] = {key: f'{key}.parquet' for key in ('market_data', 'status_data', 'universe', 'benchmark')}
            config['results_dir'] = '参考：计算结果输出目录'
            path = Path(temporary) / 'config.yaml'
            path.write_text(yaml.safe_dump(config), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '尚未配置.*results_dir'):
                load_config(path)

    def test_custom_yaml_runs_with_only_four_declared_data_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dates = pd.bdate_range('2024-01-02', periods=8)
            codes = ['A', 'B', 'C', 'D']
            market = pd.DataFrame([
                dict(trade_date=day, stock_code=code, close_raw=10 + i * step, close_post=10 + i * step,
                     vwap_post=(10 + i * step) * ratio, market_cap_cny=cap, sw_level1=sector,
                     is_st=False, is_special_risk=False, is_suspended_full_day=False,
                     is_intraday_halt=False, listed_trade_day_number=200)
                for i, day in enumerate(dates)
                for code, step, ratio, cap, sector in zip(codes, [0.1, 0.2, -0.05, 0.05],
                                                        [0.98, 0.99, 1.01, 1.02],
                                                        [1e9, 2e9, 3e9, 4e9], ['X', 'X', 'Y', 'Y'])
            ])
            status = market[['trade_date', 'stock_code']].assign(trade_status='交易', high_limit=100.0, low_limit=0.1)
            universe = market[['trade_date', 'stock_code']]
            benchmark = pd.DataFrame({'trade_date': dates, 'close': np.arange(100.0, 108.0)})
            for name, frame in [('market', market), ('status', status), ('universe', universe), ('benchmark', benchmark)]:
                frame.to_parquet(directory / f'{name}.parquet', index=False)
            config = deepcopy(small_config())
            config.update(data_root=str(directory), results_dir=str(directory / 'output'))
            config['data_paths'] = {key: f'{name}.parquet' for key, name in
                                    [('market_data', 'market'), ('status_data', 'status'),
                                     ('universe', 'universe'), ('benchmark', 'benchmark')]}
            path = directory / 'config.yaml'
            path.write_text(yaml.safe_dump(config), encoding='utf-8')
            validated = load_config(path)
            with redirect_stdout(io.StringIO()) as progress:
                result = run_research(validated)
            self.assertIn('[3/3]', progress.getvalue())
            self.assertEqual(set(result['daily_returns'].columns), {'Q1', 'Q2', 'long_short', 'benchmark'})
            self.assertEqual(len(result['daily_ic']), 8)
            self.assertEqual(len(result['daily_returns']), 8)
            self.assertEqual(result['daily_returns'].index[0], dates[0])
            np.testing.assert_allclose(result['daily_returns']['Q1'].iloc[:2], [0.0, 0.0], atol=1e-14)
            self.assertEqual(set(result['quantile_metrics'].portfolio), {'Q1', 'Q2', 'long_short', 'benchmark'})
            expected = {'daily_ic.csv', 'daily_returns.csv', 'gross_daily_returns.csv', 'monthly_returns.csv',
                        'turnover.csv', 'cost_returns.csv', 'summary.csv', 'quantile_metrics.csv',
                        'factor_values.parquet', 'execution_ledger.parquet', 'execution_orders.parquet',
                        'execution_positions.parquet', 'figures/strategy_overview.png', 'figures/quantile_analysis.png'}
            produced = {str(p.relative_to(directory / 'output')) for p in (directory / 'output').rglob('*') if p.is_file()}
            self.assertEqual(produced, expected)
            saved = pd.read_csv(directory / 'output/daily_returns.csv', index_col='trade_date', parse_dates=True)
            pd.testing.assert_frame_equal(saved, result['daily_returns'], check_freq=False, atol=1e-14, rtol=1e-14)
            completed = subprocess.run([sys.executable, '-B', str(ROOT / 'main.py'), '--config', str(path)],
                                       capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('[3/3]', completed.stdout)

            # A second source has no VWAP dependency; replace only YAML selection and input fields.
            market = market.drop(columns='vwap_post')
            market['custom_signal'] = market.stock_code.map({'A': 1.0, 'B': 2.0, 'C': 3.0, 'D': 4.0})
            market.to_parquet(directory / 'market.parquet', index=False)
            module_name = 'replacement_factor_for_integration'
            (directory / (module_name + '.py')).write_text(
                'FACTOR_ID = "custom_signal_example"\n'
                'REQUIRED_COLUMNS = ("custom_signal",)\n'
                'def calculate_factor(data, parameters):\n'
                '    out = data[["trade_date", "stock_code"]].copy()\n'
                '    out["factor_raw"] = data.custom_signal * parameters["scale"]\n'
                '    return out.iloc[::-1]\n', encoding='utf-8')
            config['factor'].update(module=module_name, parameters={'scale': -2.0})
            config['results_dir'] = str(directory / 'replacement_output')
            path.write_text(yaml.safe_dump(config), encoding='utf-8')
            sys.path.insert(0, temporary)
            try:
                with redirect_stdout(io.StringIO()):
                    alternative = run_research(load_config(path))
                self.assertEqual(alternative['summary'].factor.iloc[0], 'custom_signal_example')
                ordered = alternative['factor_values'].sort_values(['trade_date', 'stock_code'])
                np.testing.assert_allclose(ordered.factor_raw, [-2.0, -4.0, -6.0, -8.0] * 8)
                self.assertNotIn('vwap_post', alternative['factor_values'].columns)
            finally:
                sys.path.remove(temporary)
                sys.modules.pop(module_name, None)


if __name__ == '__main__':
    unittest.main()

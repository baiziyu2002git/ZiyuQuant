"""Optional checks for the independent factor-value interface and module boundaries."""
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FactorInterfaceTests(unittest.TestCase):
    def processor(self):
        try:
            return importlib.import_module('src.core.factor_processor')
        except ModuleNotFoundError as error:
            self.fail(f'An independent factor-value interface is required: {error.name}')

    def market(self):
        return pd.DataFrame({'trade_date': pd.to_datetime(['2024-01-02', '2024-01-02']),
                             'stock_code': ['A', 'B'], 'close_post': [10.0, 20.0],
                             'vwap_post': [11.0, 18.0], 'custom_signal': [2.0, 5.0]})

    def with_plugin(self, directory, body):
        name = 'test_factor_' + uuid.uuid4().hex
        path = Path(directory) / (name + '.py')
        path.write_text('FACTOR_ID = "custom_example"\nREQUIRED_COLUMNS = ("custom_signal",)\n'
                        'def calculate_factor(data, parameters):\n' + body, encoding='utf-8')
        sys.path.insert(0, directory)
        self.addCleanup(lambda: sys.path.remove(directory))
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return self.processor().load_factor({'factor': {'module': name, 'parameters': {'scale': -3}}})

    def test_example_source_runs_without_importing_the_framework(self):
        path = ROOT / 'factor_lib/qlib013.py'
        self.assertTrue(path.is_file(), 'The example factor must live outside the framework')
        spec = importlib.util.spec_from_file_location('example_factor', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = module.calculate_factor(self.market(), {})
        self.assertEqual(set(output.columns), {'trade_date', 'stock_code', 'factor_raw'})
        np.testing.assert_allclose(output.factor_raw, [1.1, 0.9], atol=1e-14)
        self.assertEqual(module.FACTOR_ID, 'qlib_alpha013')

    def test_replacement_factor_parameters_and_reordered_rows_bind_by_identity(self):
        processor = self.processor()
        with tempfile.TemporaryDirectory() as directory:
            module = self.with_plugin(directory,
                '    out = data[["trade_date", "stock_code"]].copy()\n'
                '    out["factor_raw"] = data.custom_signal * parameters["scale"]\n'
                '    return out.iloc[::-1]\n')
            result = processor.calculate_factor_values(self.market(), module, {'scale': -3})
            self.assertEqual(result.stock_code.tolist(), ['A', 'B'])
            np.testing.assert_allclose(result.factor_raw, [-6.0, -15.0], atol=1e-14)
            self.assertEqual(module.REQUIRED_COLUMNS, ('custom_signal',))

    def test_missing_or_duplicated_factor_identity_is_rejected(self):
        processor = self.processor()
        for returned in ('out.iloc[:1]', 'out.iloc[[0, 0]]'):
            with self.subTest(returned=returned), tempfile.TemporaryDirectory() as directory:
                module = self.with_plugin(directory,
                    '    out = data[["trade_date", "stock_code"]].copy()\n'
                    '    out["factor_raw"] = data.custom_signal\n'
                    f'    return {returned}\n')
                with self.assertRaisesRegex(ValueError, '因子输出.*(身份|重复)'):
                    processor.calculate_factor_values(self.market(), module, {})

    def test_factor_cannot_overwrite_execution_prices_by_mutating_its_input(self):
        processor = self.processor()
        original = self.market()
        with tempfile.TemporaryDirectory() as directory:
            module = self.with_plugin(directory,
                '    data["close_post"] = 999.0\n'
                '    out = data[["trade_date", "stock_code"]].copy()\n'
                '    out["factor_raw"] = data.custom_signal\n'
                '    return out\n')
            result = processor.calculate_factor_values(original, module, {})
            np.testing.assert_allclose(original.close_post, [10.0, 20.0])
            np.testing.assert_allclose(result.close_post, [10.0, 20.0])

    def test_performance_script_accepts_a_return_series_independently(self):
        try:
            metrics = importlib.import_module('src.backtest.metric_calculator')
        except ModuleNotFoundError as error:
            self.fail(f'An independent return-performance script is required: {error.name}')
        result = metrics.calculate_return_metrics(pd.Series([0.1, -0.1]))
        self.assertAlmostEqual(result['total_return'], -0.01)
        self.assertAlmostEqual(result['max_drawdown'], -0.1)
        self.assertAlmostEqual(result['win_rate'], 0.5)


if __name__ == '__main__':
    unittest.main()

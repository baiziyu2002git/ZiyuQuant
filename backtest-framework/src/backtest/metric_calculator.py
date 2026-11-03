"""Return-series performance only; no factor formula, IC or portfolio construction."""
import numpy as np
import pandas as pd


def compound_monthly(returns):
    return (1 + returns).resample('ME').prod(min_count=1) - 1


def calculate_return_metrics(returns):
    returns = returns.dropna()
    nav = pd.concat([pd.Series([1.]), (1 + returns).cumprod().reset_index(drop=True)], ignore_index=True)
    std = returns.std()
    return {'annual_return': float(nav.iloc[-1] ** (252 / len(returns)) - 1),
            'volatility': float(std * np.sqrt(252)),
            'sharpe_ratio': float(returns.mean() / std * np.sqrt(252)) if std else 0.,
            'max_drawdown': float((nav / nav.cummax() - 1).min()),
            'total_return': float(nav.iloc[-1] - 1), 'win_rate': float(returns.gt(0).mean())}

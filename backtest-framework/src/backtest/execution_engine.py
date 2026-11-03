"""Cash, holdings, next-day fills, price limits and transaction costs."""
import numpy as np
import pandas as pd
from src.core.config_validator import KEYS


def classify_execution_status(data):
    #涨跌停过过滤
    # 用未复权价格判断方向性限制，复权价格仅用于持仓计价。
    data = data.copy()
    raw = pd.to_numeric(data.close_raw, errors='coerce')
    upper = pd.to_numeric(data.high_limit, errors='coerce')
    lower = pd.to_numeric(data.low_limit, errors='coerce')
    price_ok = np.isfinite(raw) & raw.gt(0)
    limits_ok = np.isfinite(upper) & np.isfinite(lower) & lower.gt(0) & upper.gt(lower)
    suspended = data.is_suspended_full_day.eq(True) | data.trade_status.eq('停牌')
    state_ok = (data.trade_status.isin(['交易', 'XD', 'XR', 'DR', 'N'])
                & data.is_suspended_full_day.eq(False) & data.is_intraday_halt.eq(False))
    base = price_ok & limits_ok & state_ok & ~suspended
    at_upper = raw.ge(upper - 1e-8)
    at_lower = raw.le(lower + 1e-8)
    data['can_buy'] = base & ~at_upper
    data['can_sell'] = base & ~at_lower
    data['confirmed_suspended'] = suspended
    reason = np.select([suspended, ~state_ok, ~price_ok, ~limits_ok],
                       ['suspended', 'unknown_status', 'missing_price', 'missing_limit'], default='')
    data['buy_reason'] = np.where(base & at_upper, 'upper_limit', reason)
    data['sell_reason'] = np.where(base & at_lower, 'lower_limit', reason)
    return data


def simulate_portfolios(targets, market, calendar, num_quantiles, round_trip_cost):
    # 分层回测持仓维护
    if not np.isfinite(round_trip_cost) or not 0 <= round_trip_cost < 2:
        raise ValueError('双边成本率必须在[0,2)')
    calendar = pd.DatetimeIndex(calendar).sort_values().unique()
    if targets.duplicated(KEYS).any() or market.duplicated(KEYS).any():
        raise ValueError('执行器输入重复日期/股票键')
    stocks = pd.Index(sorted(set(market.stock_code) | set(targets.stock_code)))#持仓

    def matrix(column, default=None):
        frame = market.pivot(index='trade_date', columns='stock_code', values=column).reindex(index=calendar, columns=stocks)
        return (frame.fillna(default) if default is not None else frame).to_numpy()
    #回测矩阵
    prices = matrix('close_post').astype(float)
    buy_ok, sell_ok = matrix('can_buy', False).astype(bool), matrix('can_sell', False).astype(bool)
    suspended = matrix('confirmed_suspended', False).astype(bool)
    buy_reason, sell_reason = matrix('buy_reason', 'unknown_status'), matrix('sell_reason', 'unknown_status')
    targets = targets.copy()
    targets.trade_date = pd.to_datetime(targets.trade_date)
    signal_dates = pd.DatetimeIndex(targets.trade_date.unique())
    positions = calendar.get_indexer(signal_dates)
    if (positions < 0).any():
        raise ValueError('信号不在全局交易日历')
    schedule = {int(i + 1): date for date, i in zip(signal_dates, positions) if i + 1 < len(calendar)}
    net = pd.DataFrame(0., index=calendar, columns=[f'Q{q}_ret' for q in range(1, num_quantiles + 1)])
    gross, turns, costs = net.copy(), net.copy(), net.copy()
    orders, ledger, holdings = [], [], []
    side_cost = round_trip_cost / 2
    for q in range(1, num_quantiles + 1):
        shares = np.zeros(len(stocks))
        cash, previous_nav = 1., 1.
        last_mark = np.full(len(stocks), np.nan)
        for i, date in enumerate(calendar):
            exact = prices[i]
            valid = np.isfinite(exact) & (exact > 0)
            mark = np.where(valid, exact, np.where(suspended[i], last_mark, np.nan))
            held = shares > 1e-14
            if (held & ~np.isfinite(mark)).any():
                raise ValueError(f'持仓缺少可靠估值: {date} {stocks[held & ~np.isfinite(mark)].tolist()}')
            last_mark = np.where(np.isfinite(mark), mark, last_mark)
            values = np.where(held, shares * np.nan_to_num(mark), 0.)
            pre_nav = cash + values.sum()
            if pre_nav <= 0 or not np.isfinite(pre_nav):
                raise ValueError('执行组合净资产非正或非有限')
            gross_return = pre_nav / previous_nav - 1
            traded, cost, blocked_buy, blocked_sell = 0., 0., 0., 0.
            if i in schedule:
                date_targets = targets[(targets.trade_date == schedule[i]) & targets['quantile'].eq(q)]
                weight = np.zeros(len(stocks))
                if len(date_targets):
                    weight[stocks.get_indexer(date_targets.stock_code)] = 1 / len(date_targets)
                desired = pre_nav * weight
                sell_need = np.maximum(values - desired, 0.)
                sell = np.where(sell_ok[i] & valid, sell_need, 0.)
                blocked_sell = float((sell_need - sell).sum())
                shares -= np.divide(sell, exact, out=np.zeros_like(sell), where=valid)
                cash += sell.sum() * (1 - side_cost)
                buy_need = np.maximum(desired - (values - sell), 0.)
                allowed = np.where(buy_ok[i] & valid, buy_need, 0.)
                scale = min(1., cash / (allowed.sum() * (1 + side_cost))) if allowed.sum() else 0.
                buy = allowed * max(scale, 0.)
                blocked_buy = float((buy_need - allowed).sum())
                shares += np.divide(buy, exact, out=np.zeros_like(buy), where=valid)
                cash -= buy.sum() * (1 + side_cost)
                traded = float(buy.sum() + sell.sum())
                cost = traded * side_cost
                #遍历买入和卖出
                for side, requested, filled, why, ok in (
                    ('sell', sell_need, sell, sell_reason[i], sell_ok[i] & valid),
                    ('buy', buy_need, buy, buy_reason[i], buy_ok[i] & valid),
                ):
                    for j in np.flatnonzero(requested > 1e-12):#遍历有交易需求的股票
                        reason = str(why[j]) if not ok[j] else ('cash_budget' if requested[j] - filled[j] > 1e-12 else 'filled')
                        orders.append(dict(trade_date=date, signal_date=schedule[i], quantile=q, stock_code=stocks[j], side=side,
                                           requested=float(requested[j]), filled=float(filled[j]), blocked=float(requested[j] - filled[j]),
                                           reason=reason or 'missing_price', fee=float(filled[j] * side_cost)))
            values = np.where(shares > 1e-14, shares * np.nan_to_num(mark), 0.)
            frozen = float(values[~sell_ok[i]].sum())
            nav = float(cash + values.sum())
            if cash < -1e-10 or (shares < -1e-10).any() or not np.isclose(nav, pre_nav - cost, atol=1e-10, rtol=1e-10):
                raise AssertionError('现金/持仓/资产守恒失败')
            col = f'Q{q}_ret'
            net.loc[date, col] = nav / previous_nav - 1
            gross.loc[date, col] = gross_return
            turns.loc[date, col] = traded / (2 * pre_nav)#换手率计算
            costs.loc[date, col] = cost / previous_nav
            ledger.append(dict(trade_date=date, quantile=q, pre_nav=float(pre_nav), nav=nav, cash=float(cash),
                               holdings_value=float(values.sum()), cost=cost, traded=traded, frozen_value=frozen,
                               blocked_buy=blocked_buy, blocked_sell=blocked_sell))
            for j in np.flatnonzero(shares > 1e-14):
                holdings.append(dict(trade_date=date, quantile=q, stock_code=stocks[j], units=float(shares[j]), value=float(values[j])))
            previous_nav = nav
    return {'net_returns': net, 'gross_returns': gross, 'turnover': turns, 'cost_returns': costs,
            'ledger': pd.DataFrame(ledger),
            'orders': pd.DataFrame(orders, columns=['trade_date', 'signal_date', 'quantile', 'stock_code', 'side', 'requested', 'filled', 'blocked', 'reason', 'fee']),
            'positions': pd.DataFrame(holdings, columns=['trade_date', 'quantile', 'stock_code', 'units', 'value'])}

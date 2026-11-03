# 中低频因子分层回测框架

独立运行的 Python 研究框架，只包含因子预处理、IC／Rank IC 计算和分层组合回测，不包含 App 工程源码或私有数据。计算不依赖其他项目，也不联网下载数据。

通用框架与因子源码分开。默认只附一个独立因子源码：Qlib Alpha158 的 VWAP0，`factor = vwap_post / close_post`。换因子时，只需准备另一个因子模块并修改 YAML 选择，不需要修改 IC、分层或绩效脚本。日频数据用于逐日计价，`rebalance_period` 控制每隔多少个交易日调仓，适合中低频研究。

## 文件分工

```text
main.py                              统一运行入口
factor_lib/
  qlib013.py                         独立因子源码：只输出因子值
config/
  config.yaml                        数据用途、因子选择、研究与回测配置
src/
  core/
    config_validator.py              配置检查
    data_loader.py                   读取数据与交易日历
    factor_processor.py              因子接口、身份校验及截面预处理
  backtest/
    signal_analyzer.py               IC / Rank IC
    quantile_calculator.py           分层、调仓与多空研究价差
    execution_engine.py              成交限制、现金、持仓与费用
    metric_calculator.py             绩效评估：收益、波动、Sharpe、回撤等
    chart_generator.py               只根据计算结果绘图
  controller/
    factor_controller.py             串联流程、汇总并保存结果
tests/                               可选自动化自检，不参与正常回测
```

正常运行只调用 `main.py`。因子文件不负责读取配置、IC、分层、交易、绩效或保存结果；这些职责由通用框架统一完成。各模块可以独立导入使用，但不需要逐个作为命令运行。

## 独立因子接口

每个因子模块只需声明 `FACTOR_ID`、`REQUIRED_COLUMNS`，并提供 `calculate_factor(data, parameters)`。完整示例见 `factor_lib/qlib013.py`。

- `FACTOR_ID`：因子独立标识，用于结果身份，不在框架中写死。
- `REQUIRED_COLUMNS`：公式需要的行情字段，框架据此加载额外列；例如示例声明 `close_post`、`vwap_post`。
- `data`：本次股票池涉及证券在配置预热区间内的历史长表，含交易日期、证券代码和所需字段。
- `parameters`：YAML 中 `factor.parameters` 的参数映射，默认空映射。
- 返回值：含 `trade_date`、`stock_code`、`factor_raw` 的 DataFrame。必须保留输入的日期／证券身份；缺失因子值使用 NaN，不删除行。

框架按日期与证券代码绑定结果，返回行顺序可以不同，但重复、丢失或新增身份会被拒绝。只接收因子值，不接收因子返回的行情价格覆盖原始执行价格。随后才按当日动态股票池筛选并执行截面预处理。

YAML 用 `factor.module` 选择 Python 模块，默认 `factor_lib.qlib013`；这不是作者机器上的文件位置。只加载自己已审核、信任的因子源码，普通 Python 模块入口不提供执行沙盒，也不自动验证是否使用未来数据。

## 运行

建议使用 Python 3.10 或更新版本。在项目根目录执行：

```bash
python -m pip install -r requirements.txt
python main.py --config config/config.yaml
```

运行前，必须将 YAML 中的“参考：...”替换为自己准备的数据位置。模板只说明需要什么数据，不包含作者的数据位置，也不会自动寻找或替换其他数据来源。未配置时，程序直接提示缺少的数据字段，不启动回测。

`data_paths` 中的相对位置按 `data_root` 解析，也可以为各项指定自备数据的独立位置；相对的 `data_root` 按本项目根目录解析。`results_dir` 只说明输出用途，也须替换为自己指定的输出位置；相对输出位置按本项目根目录解析。重复运行会覆盖该输出目录中的同名计算结果。

## 必需数据与字段

全部输入使用 Parquet 格式；行情与状态可为单个文件，也可为 `year=YYYY/data_0.parquet` 的年度分区目录。证券代码使用字符串，保留前导零和市场后缀；日期使用日期或时间戳类型。同一输入中的交易日期／证券代码组合必须唯一。

| YAML 字段 | 参考数据 | 必需列 |
| --- | --- | --- |
| `data_paths.market_data` | 全A股票日行情、日市值、行业与风险标记 | `trade_date`, `stock_code`, `close_raw`, `close_post`, `market_cap_cny`, `sw_level1`, `is_st`, `is_special_risk`, `is_suspended_full_day`, `is_intraday_halt`, `listed_trade_day_number` |
| `data_paths.status_data` | 全A股票日交易状态与涨跌停价 | `trade_date`, `stock_code`, `trade_status`, `high_limit`, `low_limit` |
| `data_paths.universe` | 逐交易日动态股票池成分 | `trade_date`, `stock_code` |
| `data_paths.benchmark` | 基准指数日行情及完整交易日历 | `trade_date`, `close` |

字段含义：

- `close_raw`、`high_limit`、`low_limit`：未复权价格，用于判断涨跌停等成交限制，单位必须一致。
- `close_post`、`vwap_post`：同一后复权口径的收盘价、成交量加权均价；不得混用不同复权方式。
- `market_cap_cny`：当日市值，单位为元；中性化使用其自然对数。
- `sw_level1`：当日行业分类，字符串或可转换为字符串的分类值。
- `is_st`、`is_special_risk`、`is_suspended_full_day`、`is_intraday_halt`：布尔标记，未知状态不能写成已确认的正常交易。
- `listed_trade_day_number`：截至当日已上市的交易日数。
- `trade_status`：正常可交易状态为 `交易`、`XD`、`XR`、`DR`、`N`；停牌使用 `停牌`。其他状态限制交易。
- 基准的 `trade_date` 同时作为完整交易日历；`close` 为真实指数收盘点位，不能删除缺行情的交易日来构造日历。

行情文件还需包含所选因子在 `REQUIRED_COLUMNS` 中声明的额外字段。默认示例需要 `vwap_post`；不使用该字段的其他因子不要求提供它。预热起点由 `warmup_start` 指定，不自动补造更早历史。

本框架只读这些输入，不附带供应商数据。数据使用与再分发权限由使用者自行核对。

## IC 与预处理口径

先按当日动态股票池取样，排除 ST、特殊风险、整日停牌、上市不足 60 个交易日和必要字段无效的股票。逐日处理顺序为：MAD 去极值 → 市值／行业 OLS 残差中性化 → 截面 z-score。各步骤由 YAML 开关控制；MAD 使用中位数 ± 阈值 × MAD，不乘额外的尺度系数。

日频 IC 为 `factor(t)` 与 `close_post(t+1) / close_post(t) - 1` 的 Pearson 相关；Rank IC 为对应的 Spearman 相关。`t+1` 是交易日历中的下一日，缺失端点保留缺失，不跳过缺口寻找替代价格。

配置可对完整有效 IC 序列做分位缩尾，原始 `ic_raw`、`rank_ic_raw` 也会保存。此缩尾是研究期事后统计，扩展区间会改变边界，不能当作当时已知的在线信号。ICIR 为有效 IC 的均值除以样本标准差，不额外年化。

IC 的收盘至次日收盘标签，与下一交易日才成交的分层收益不是同一段持有收益；IC 为正不等于组合一定盈利，也不构成完整的未来信息认证。

## 分层回测口径

按因子降序排序，股票代码打破并列，再按排名分层。Q1 是最高因子值组，最后一层是最低组，目标等权。默认每 5 个交易日产生一次调仓信号，买卖均在下一交易日收盘尝试执行，不按已知当日收盘信号同价成交。

每层独立维护现金与持仓，初始净值为 1。非调仓日持仓自然漂移，逐日计价；期末不强制平仓。

- 涨停不买，跌停不卖；停牌、未知状态、缺少有效价格或涨跌停价也会限制交易。
- 卖不出的持仓继续保留；未成交订单仅在下一计划调仓日重新尝试。
- 仅明确停牌且缺价时沿用上次可靠估值；其他持仓缺少可靠估值时直接失败，不删除持仓、不把资产补零。
- `transaction_cost` 控制费用与滑点。沿用现有费率约定：`fee_rate + slippage` 为双边总率，执行时每侧取一半；默认关闭。

多空研究价差为“最高层毛收益 − 最低层毛收益 − 最高层成本收益 − 最低层成本收益”。不能用两层净收益直接相减代替，否则会把空头一侧的成本加回来。多空序列只是研究价差，不是含借券、保证金及融券费用的真实卖空账户。

绩效包括累计收益、年化收益、年化波动率、零基准 Sharpe、最大回撤与胜率。虽然低频调仓，组合仍逐日计价，年化按 252 个交易日计算。月收益为已有日收益逐日复利，缺失收益不补零；区间首尾可能为不完整月份，不能视为完整月的业绩。

## 输出

- `daily_ic.csv`：原始与缩尾后的 IC、Rank IC 及有效样本数。
- `factor_values.parquet`：逐日逐股的原始／处理后因子、收益标签、分层及调仓信号标记。
- `daily_returns.csv`、`monthly_returns.csv`：各层净收益、多空研究价差及基准收益。
- `gross_daily_returns.csv`、`turnover.csv`、`cost_returns.csv`：毛收益、成交换手与成本收益。
- `summary.csv`、`quantile_metrics.csv`：因子统计及分层绩效。
- `execution_ledger.parquet`、`execution_orders.parquet`、`execution_positions.parquet`：现金与净值、成交／受阻订单及持仓明细。
- `figures/strategy_overview.png`、`figures/quantile_analysis.png`：IC、净值、回撤及分层对照图。

仅保存计算数据与图表，不生成研究报告、演讲材料或其他文稿。

## 可选自检：tests 是做什么的

`tests/test_framework.py` 检查框架的日期、成交、费用及保存行为；`tests/test_factor_interface.py` 检查独立因子接口。它们不是因子源码或回测主程序，正常回测不需要运行。建议随仓库保留，方便修改代码后复查。

```bash
python -m unittest discover -s tests -v
```

测试使用明确的确定性小样本，覆盖精确日期标签、缺口、次日成交、涨跌停、费用、资产守恒，以及 YAML → 因子选择／参数 → 输入读取 → 结果保存。额外检查替换因子、额外输入字段、输出身份错配及输入修改隔离。测试样本不是供应商数据，不代表真实投资表现或真实区间验收。

## 限制

这是日频归一化研究账户，不是逐笔撮合或整手交易系统；未完整实现跨证券换股、退市清算及所有公司行动承接。扩展区间遇到无法可靠估值的持仓，应先补齐事件证据，不能为了得到完整曲线而删除持仓或无限前填。

输入数据的历史修订、当时可见性、动态股票池真实性及样本外稳健性需要另行验证。历史回测不构成实盘收益承诺。

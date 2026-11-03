"""Charts from existing calculation results; does not calculate factors or returns."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd


def create_figures(output, daily, monthly, ic, initial_date, groups):
    #接受数据绘图，输出净值对比，多空回撤，因子表现，收益热力图
    folder = output / 'figures'
    folder.mkdir(exist_ok=True)
    plt.rcParams.update({'figure.dpi': 140, 'axes.spines.top': False, 'axes.spines.right': False, 'font.size': 10})
    colors = ['#007f73', '#c74758', '#c59b2c', '#4f6a9a', '#797979']
    nav = pd.concat([pd.DataFrame(1., index=[initial_date], columns=daily.columns), (1 + daily).cumprod()])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    nav[['long_short', 'benchmark']].plot(ax=axes[0, 0], color=[colors[0], colors[3]])
    axes[0, 0].set(title='Long-short research spread and benchmark', ylabel='Growth of 1')
    drawdown = nav.long_short / nav.long_short.cummax() - 1
    axes[0, 1].fill_between(nav.index, drawdown, 0, color=colors[1], alpha=.4)
    axes[0, 1].set(title='Long-short drawdown', ylabel='Drawdown')
    axes[0, 1].xaxis.set_major_locator(mdates.YearLocator())
    axes[0, 1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ic[['ic', 'rank_ic']].rolling(60, min_periods=20).mean().plot(ax=axes[1, 0], color=[colors[0], colors[3]])
    axes[1, 0].axhline(0, color='#999999', linewidth=.6)
    axes[1, 0].set(title='IC and Rank IC: trailing 60-session mean', ylabel='Correlation')
    matrix = monthly.long_short.groupby([monthly.index.year, monthly.index.month]).first().unstack().reindex(columns=range(1, 13))
    scale = max(float(np.nanmax(np.abs(matrix.to_numpy()))), 1e-6)
    im = axes[1, 1].imshow(matrix, cmap='RdYlGn', vmin=-scale, vmax=scale, aspect='auto')
    axes[1, 1].set_xticks(range(12), range(1, 13))
    axes[1, 1].set_yticks(range(len(matrix)), matrix.index)
    axes[1, 1].set(title='Monthly long-short return', xlabel='Month')
    for i in range(len(matrix)):
        for j in range(12):
            if pd.notna(matrix.iloc[i, j]):
                axes[1, 1].text(j, i, f'{matrix.iloc[i, j]:.0%}', ha='center', va='center', fontsize=8)
    fig.colorbar(im, ax=axes[1, 1], shrink=.7)
    fig.tight_layout(); fig.savefig(folder / 'strategy_overview.png'); plt.close(fig)
    group_cols = [f'Q{i}' for i in range(1, groups + 1)] + ['long_short']
    labels = {'long_short': 'Long-Short'}
    styles = ['-'] * groups + ['--']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    palette = [colors[i % len(colors)] for i in range(groups)] + ['#222222']
    nav[group_cols].rename(columns=labels).plot(ax=axes[0], color=palette, style=styles)
    axes[0].set(title='Quantile portfolios and long-short research spread', ylabel='Growth of 1')
    nav[group_cols].div(nav.benchmark, axis=0).rename(columns=labels).plot(
        ax=axes[1], color=palette, style=styles)
    axes[1].set(title='NAV / benchmark NAV', ylabel='Relative wealth (initial = 1)')
    axes[1].axhline(1, color='#999999', linewidth=.6)
    fig.tight_layout(); fig.savefig(folder / 'quantile_analysis.png'); plt.close(fig)

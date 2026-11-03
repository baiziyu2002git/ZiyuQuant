"""Generic entry: YAML -> independent factor source -> IC and quantile backtest."""
from pathlib import Path
import argparse

from src.core.config_validator import ROOT, load_config
from src.controller.factor_controller import run_research


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/config.yaml', help='YAML configuration file')
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        run_research(config)
    except (ValueError, FileNotFoundError) as error:
        parser.exit(2, f'配置或输入数据错误：{error}\n')


if __name__ == "__main__":
    main()

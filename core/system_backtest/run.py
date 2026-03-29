"""CLI entrypoint for the canonical system replay backtest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loop import SystemReplayLoop
from .models import SystemBacktestConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live-like replay backtest for the canonical futures system.")
    parser.add_argument("--config", required=True, help="Path to the replay scenario YAML.")
    parser.add_argument("--timerange", required=True, help="Replay timerange formatted as <start>:<end>.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = SystemBacktestConfig.from_yaml(Path(args.config))
    loop = SystemReplayLoop(config=config)
    result = loop.run(timerange=args.timerange)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

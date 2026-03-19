"""Run the standard broad backtest bundle for one futures candidate."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
import zipfile

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
USER_DATA_DIR = REPO_ROOT / "trading" / "freqtrade" / "user_data"
RESULTS_DIR = USER_DATA_DIR / "backtest_results"
STANDARD_WINDOWS = [
    ("full_window", "20251119-20260319"),
    ("historical_window", "20251119-20251231"),
    ("mid_window", "20260101-20260214"),
    ("recent_window", "20260215-20260319"),
]


@dataclass(frozen=True)
class WindowResult:
    name: str
    timerange: str
    total_trades: int
    total_profit_pct: float
    drawdown_pct: float
    long_profit_pct: float
    short_profit_pct: float


def load_manifest(candidate_id: str) -> dict[str, Any]:
    manifest_path = REPO_ROOT / "research" / "candidates" / candidate_id / "strategy_manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Unknown candidate manifest: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def active_side_policy(manifest: dict[str, Any]) -> str:
    return str(manifest.get("active_side_policy") or manifest.get("allowed_sides") or "unknown")


def parked_short(manifest: dict[str, Any]) -> bool:
    policy = active_side_policy(manifest)
    return "parked_short" in policy or policy == "long"


def parked_long(manifest: dict[str, Any]) -> bool:
    policy = active_side_policy(manifest)
    return "parked_long" in policy or policy == "short"


def derive_verdict(manifest: dict[str, Any], windows: list[WindowResult]) -> tuple[str, list[str]]:
    notes: list[str] = []
    by_name = {window.name: window for window in windows}
    full_window = by_name["full_window"]
    recent_window = by_name["recent_window"]
    if full_window.total_profit_pct < 0:
        notes.append("Full window pozostaje ujemny.")
    if full_window.drawdown_pct > 1.0:
        notes.append("Full window drawdown przekracza 1.0%.")
    if recent_window.total_profit_pct <= 0:
        notes.append("Recent window nie jest dodatni.")
    if not parked_long(manifest) and full_window.long_profit_pct < 0:
        notes.append("Aktywna strona long szkodzi wynikowi.")
    if not parked_short(manifest) and full_window.short_profit_pct < 0:
        notes.append("Aktywna strona short szkodzi wynikowi.")
    if not notes:
        return "pass_for_limited_dry_run", []
    return "needs_rework", notes


def build_summary(manifest: dict[str, Any], windows: list[WindowResult]) -> dict[str, Any]:
    result, notes = derive_verdict(manifest, windows)
    payload = {
        "strategy_id": manifest["strategy_id"],
        "strategy_name": manifest["strategy_name"],
        "market_type": manifest["market_type"],
        "evaluation_scope": "broad_backtest_bundle",
        "broad_windows": [
            {
                "name": window.name,
                "timerange": window.timerange,
                "total_trades": window.total_trades,
                "total_profit_pct": round(window.total_profit_pct, 4),
                "drawdown_pct": round(window.drawdown_pct, 4),
                "long_profit_pct": round(window.long_profit_pct, 4),
                "short_profit_pct": round(window.short_profit_pct, 4),
            }
            for window in windows
        ],
        "gate_thresholds": {
            "limited_dry_run_candidate": {
                "full_window_total_profit_pct_min": 0.0,
                "full_window_drawdown_pct_max": 1.0,
                "recent_window_total_profit_pct_min": 0.0,
                "active_side_must_not_be_harmful": True,
            }
        },
        "result": result,
        "notes": notes,
    }
    policy_note = active_side_policy(manifest)
    if policy_note:
        payload["notes"].append(f"Active side policy: {policy_note}.")
    return payload


def _container_config_path(relative_path: str) -> str:
    prefix = "trading/freqtrade/user_data/"
    if not relative_path.startswith(prefix):
        raise ValueError(f"Unsupported backtest config path: {relative_path}")
    return "/freqtrade/user_data/" + relative_path.removeprefix(prefix)


def _read_result_archive(archive_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_path = archive_path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    with zipfile.ZipFile(archive_path) as bundle:
        json_name = next(
            (
                name
                for name in bundle.namelist()
                if name.endswith(".json") and not name.endswith("_config.json")
            ),
            None,
        )
        if json_name is None:
            raise RuntimeError(f"No result json found in backtest archive: {archive_path}")
        payload = json.loads(bundle.read(json_name))
    return payload, meta


def _run_window_backtest(
    *,
    candidate_id: str,
    strategy_name: str,
    config_path: str,
    window_name: str,
    timerange: str,
    compose_service: str,
) -> dict[str, Any]:
    export_dir = RESULTS_DIR / "_candidate_runner" / candidate_id / window_name
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    export_dir_container = "/freqtrade/user_data/" + str(export_dir.relative_to(USER_DATA_DIR))
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            compose_service,
            "backtesting",
            "--config",
            config_path,
            "--strategy",
            strategy_name,
            "--timerange",
            timerange,
            "--export",
            "trades",
            "--backtest-directory",
            export_dir_container,
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )
    archives = sorted(export_dir.glob("backtest-result-*.zip"))
    if not archives:
        raise RuntimeError(f"No backtest archive generated for {candidate_id} {window_name}.")
    payload, _ = _read_result_archive(archives[-1])
    return payload


def _extract_window_result(
    *,
    manifest: dict[str, Any],
    name: str,
    timerange: str,
    payload: dict[str, Any],
) -> WindowResult:
    strategy_results = payload["strategy"][manifest["strategy_name"]]
    long_profit = 0.0
    short_profit = 0.0
    enter_tag_results = strategy_results.get("results_per_enter_tag") or []
    if isinstance(enter_tag_results, dict):
        iterable = [
            {"key": key, **(details or {})}
            for key, details in enter_tag_results.items()
        ]
    else:
        iterable = [entry for entry in enter_tag_results if isinstance(entry, dict)]
    for details in iterable:
        tag_name = str(details.get("key", "")).lower()
        if tag_name == "total":
            continue
        profit = float(details.get("profit_total_pct", 0.0))
        if "short" in tag_name:
            short_profit += profit
        else:
            long_profit += profit
    return WindowResult(
        name=name,
        timerange=timerange,
        total_trades=int(strategy_results.get("total_trades", 0)),
        total_profit_pct=float(strategy_results.get("profit_total", 0.0)) * 100.0,
        drawdown_pct=float(strategy_results.get("max_drawdown_account", 0.0)) * 100.0,
        long_profit_pct=long_profit,
        short_profit_pct=short_profit,
    )


def run_candidate_backtests(candidate_id: str, *, compose_service: str = "freqtrade") -> dict[str, Any]:
    manifest = load_manifest(candidate_id)
    config_path = _container_config_path(str(manifest["backtest_config"]))
    strategy_name = str(manifest["strategy_name"])
    windows: list[WindowResult] = []
    for window_name, timerange in STANDARD_WINDOWS:
        payload = _run_window_backtest(
            candidate_id=candidate_id,
            strategy_name=strategy_name,
            config_path=config_path,
            window_name=window_name,
            timerange=timerange,
            compose_service=compose_service,
        )
        windows.append(
            _extract_window_result(
                manifest=manifest,
                name=window_name,
                timerange=timerange,
                payload=payload,
            )
        )

    summary = build_summary(manifest, windows)
    output_path = REPO_ROOT / str(manifest["broad_backtest_summary_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_id", help="Candidate id from research/candidates/<candidate_id>/")
    parser.add_argument(
        "--compose-service",
        default="freqtrade",
        help="Docker compose service used to run Freqtrade backtesting.",
    )
    args = parser.parse_args()
    result = run_candidate_backtests(args.candidate_id, compose_service=args.compose_service)
    print(json.dumps(result, indent=2, ensure_ascii=True))

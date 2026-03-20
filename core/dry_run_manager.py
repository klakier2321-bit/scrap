"""Dry-run bridge, snapshot pipeline, and smoke tests for Freqtrade runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from opentelemetry import trace

from .freqtrade_runtime import FreqtradeRuntimeClient, FreqtradeRuntimeError


tracer = trace.get_tracer(__name__)


class DryRunManager:
    """Builds read-only runtime snapshots for agents and operators."""

    def __init__(
        self,
        *,
        client: FreqtradeRuntimeClient,
        snapshots_dir: Path,
        smoke_dir: Path,
        stale_after_seconds: int = 180,
    ) -> None:
        self.client = client
        self.snapshots_dir = snapshots_dir
        self.smoke_dir = smoke_dir
        self.stale_after_seconds = stale_after_seconds
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.smoke_dir.mkdir(parents=True, exist_ok=True)

    def health(self, *, bot_status: dict[str, Any], logs: list[str]) -> dict[str, Any]:
        with tracer.start_as_current_span("DryRunManager.health"):
            latest_snapshot = self.latest_snapshot(bot_id=bot_status["bot_id"])
            latest_smoke = self.latest_smoke(bot_id=bot_status["bot_id"])
            warnings = self._extract_runtime_warnings(logs)

            bridge_status = "ok"
            blocking_reason = None
            runtime_mode = None
            dry_run_enabled = bool(bot_status.get("dry_run", False))
            api_authenticated = False

            if bot_status.get("state") != "running":
                bridge_status = "runtime_unavailable"
                blocking_reason = "bot_not_running"
            else:
                try:
                    self.client.ping()
                    config = self.client.show_config()
                    api_authenticated = True
                    dry_run_enabled = bool(config.get("dry_run", dry_run_enabled))
                    runtime_mode = str(config.get("runmode") or "").strip() or None
                    if not dry_run_enabled:
                        bridge_status = "dry_run_disabled"
                        blocking_reason = "dry_run_disabled"
                    elif runtime_mode == "webserver":
                        bridge_status = "webserver_only"
                        blocking_reason = "webserver_only"
                except FreqtradeRuntimeError as exc:
                    bridge_status = exc.code
                    blocking_reason = exc.code
                    warnings.append(exc.message)

            snapshot_available = latest_snapshot is not None
            snapshot_age_seconds = self._snapshot_age_seconds(latest_snapshot)
            snapshot_is_fresh = (
                snapshot_age_seconds is not None
                and snapshot_age_seconds <= float(self.stale_after_seconds)
            )

            ready = (
                bot_status.get("state") == "running"
                and bridge_status == "ok"
                and dry_run_enabled
                and runtime_mode not in {None, "webserver"}
                and snapshot_available
                and snapshot_is_fresh
            )
            if not ready and blocking_reason is None:
                if not snapshot_available:
                    blocking_reason = "snapshot_missing"
                elif not snapshot_is_fresh:
                    blocking_reason = "snapshot_stale"

            return {
                "bot_id": bot_status["bot_id"],
                "bot_state": bot_status.get("state", "unknown"),
                "dry_run": dry_run_enabled,
                "runtime_mode": runtime_mode or "brak danych",
                "bridge_status": bridge_status,
                "api_authenticated": api_authenticated,
                "ready": ready,
                "blocking_reason": blocking_reason,
                "snapshot_available": snapshot_available,
                "snapshot_age_seconds": snapshot_age_seconds,
                "last_snapshot_at": latest_snapshot.get("generated_at") if latest_snapshot else None,
                "last_smoke_status": latest_smoke.get("status") if latest_smoke else None,
                "last_smoke_at": latest_smoke.get("generated_at") if latest_smoke else None,
                "warnings": warnings[:10],
            }

    def create_snapshot(
        self,
        *,
        bot_status: dict[str, Any],
        logs: list[str],
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("DryRunManager.create_snapshot") as span:
            span.set_attribute("crypto.bot_id", bot_status["bot_id"])
            generated_at = datetime.now(timezone.utc).isoformat()
            ping = self.client.ping()
            config = self.client.show_config()
            balance = self.client.balance()
            profit = self.client.profit()
            trades_payload = self.client.trades()
            count_payload = self.client.count()
            performance_payload = self.client.performance()
            status_payload = self.client.status()
            runtime_mode = str(config.get("runmode") or "").strip() or "unknown"

            count_summary = self._count_summary(count_payload)
            open_trades = self._extract_open_trades(status_payload) or self._extract_open_trades(
                trades_payload
            )
            open_trades_count = len(open_trades)
            if open_trades_count == 0 and isinstance(count_summary.get("current_open_trades"), int):
                open_trades_count = int(count_summary["current_open_trades"])
            snapshot = {
                "bot_id": bot_status["bot_id"],
                "generated_at": generated_at,
                "source": "freqtrade_runtime_bridge",
                "bridge_status": "ok",
                "dry_run": bool(config.get("dry_run", bot_status.get("dry_run", False))),
                "runmode": runtime_mode,
                "strategy": config.get("strategy") or bot_status.get("strategy"),
                "config_summary": self._config_summary(config),
                "balance_summary": self._balance_summary(balance, config),
                "profit_summary": self._profit_summary(profit),
                "performance_summary": self._performance_summary(performance_payload),
                "trade_count_summary": count_summary,
                "open_trades_count": open_trades_count,
                "open_trades": open_trades,
                "runtime_warnings": self._extract_runtime_warnings(logs),
                "ping_status": ping.get("status", "unknown"),
                "snapshot_status": "ok",
                "snapshot_stale_after_seconds": self.stale_after_seconds,
            }
            self._persist_json(self._snapshot_path(bot_status["bot_id"], generated_at), snapshot)
            self._persist_json(self.snapshots_dir / f"latest-{bot_status['bot_id']}.json", snapshot)
            self._persist_json(self.snapshots_dir / "latest.json", snapshot)
            return snapshot

    def sync_snapshot_if_stale(
        self,
        *,
        bot_status: dict[str, Any],
        logs: list[str],
    ) -> dict[str, Any] | None:
        latest = self.latest_snapshot(bot_id=bot_status["bot_id"])
        if latest is not None:
            age = self._snapshot_age_seconds(latest)
            if age is not None and age <= float(self.stale_after_seconds):
                return latest
        try:
            return self.create_snapshot(bot_status=bot_status, logs=logs)
        except FreqtradeRuntimeError:
            return latest

    def latest_snapshot(self, *, bot_id: str | None = None) -> dict[str, Any] | None:
        path = self.snapshots_dir / (f"latest-{bot_id}.json" if bot_id else "latest.json")
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_snapshots(
        self,
        *,
        bot_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        pattern = f"{bot_id}-*.json" if bot_id else "*.json"
        snapshots = []
        for path in sorted(self.snapshots_dir.glob(pattern), reverse=True):
            if path.name.startswith("latest"):
                continue
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
            if len(snapshots) >= limit:
                break
        return snapshots

    def latest_smoke(self, *, bot_id: str | None = None) -> dict[str, Any] | None:
        path = self.smoke_dir / (f"latest-{bot_id}.json" if bot_id else "latest.json")
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def run_smoke_test(
        self,
        *,
        bot_status: dict[str, Any],
        logs: list[str],
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("DryRunManager.run_smoke_test") as span:
            span.set_attribute("crypto.bot_id", bot_status["bot_id"])
            steps: list[dict[str, Any]] = []
            warnings = self._extract_runtime_warnings(logs)
            generated_at = datetime.now(timezone.utc).isoformat()
            blocking_reason = None
            snapshot_path = None
            config: dict[str, Any] | None = None

            if bot_status.get("state") != "running":
                blocking_reason = "bot_not_running"
                steps.append(self._step("bot_running", False, "Bot container is not running."))
            else:
                steps.append(self._step("bot_running", True, "Bot container is running."))

            try:
                ping = self.client.ping()
                steps.append(self._step("bridge_ping", ping.get("status") == "pong", "Bridge ping responded."))
                config = self.client.show_config()
                steps.append(self._step("api_auth", True, "Control layer authenticated to Freqtrade API."))
            except FreqtradeRuntimeError as exc:
                blocking_reason = exc.code
                steps.append(self._step("bridge_ping", False, exc.message))
                smoke = self._build_smoke_result(
                    bot_id=bot_status["bot_id"],
                    generated_at=generated_at,
                    status="fail",
                    dry_run=bool(bot_status.get("dry_run", False)),
                    runtime_mode="brak danych",
                    blocking_reason=blocking_reason,
                    steps=steps,
                    warnings=warnings,
                    snapshot_path=snapshot_path,
                )
                self._persist_smoke(bot_status["bot_id"], generated_at, smoke)
                return smoke

            dry_run_enabled = bool(config.get("dry_run", bot_status.get("dry_run", False)))
            runtime_mode = str(config.get("runmode") or "").strip() or "unknown"
            steps.append(self._step("dry_run_enabled", dry_run_enabled, f"dry_run={dry_run_enabled}."))
            steps.append(
                self._step(
                    "runtime_mode",
                    runtime_mode != "webserver",
                    f"runmode={runtime_mode}.",
                )
            )
            if not dry_run_enabled:
                blocking_reason = "dry_run_disabled"
            elif runtime_mode == "webserver":
                blocking_reason = "webserver_only"

            required_runtime_paths = [
                ("balance", self.client.balance),
                ("profit", self.client.profit),
                ("trades", self.client.trades),
                ("count", self.client.count),
                ("performance", self.client.performance),
            ]
            for step_name, loader in required_runtime_paths:
                try:
                    loader()
                    steps.append(self._step(step_name, True, f"Endpoint '{step_name}' responded."))
                except FreqtradeRuntimeError as exc:
                    if blocking_reason is None:
                        blocking_reason = exc.code
                    steps.append(self._step(step_name, False, exc.message))

            if blocking_reason is None:
                try:
                    snapshot = self.create_snapshot(bot_status=bot_status, logs=logs)
                    snapshot_path = self._snapshot_path(
                        bot_status["bot_id"],
                        snapshot["generated_at"],
                    ).as_posix()
                    steps.append(self._step("snapshot", True, "Runtime snapshot generated successfully."))
                except FreqtradeRuntimeError as exc:
                    blocking_reason = exc.code
                    steps.append(self._step("snapshot", False, exc.message))

            smoke = self._build_smoke_result(
                bot_id=bot_status["bot_id"],
                generated_at=generated_at,
                status="pass" if blocking_reason is None else "fail",
                dry_run=dry_run_enabled,
                runtime_mode=runtime_mode,
                blocking_reason=blocking_reason,
                steps=steps,
                warnings=warnings,
                snapshot_path=snapshot_path,
            )
            self._persist_smoke(bot_status["bot_id"], generated_at, smoke)
            return smoke

    def _snapshot_path(self, bot_id: str, generated_at: str) -> Path:
        timestamp = generated_at.replace(":", "-")
        return self.snapshots_dir / f"{bot_id}-{timestamp}.json"

    def _smoke_path(self, bot_id: str, generated_at: str) -> Path:
        timestamp = generated_at.replace(":", "-")
        return self.smoke_dir / f"{bot_id}-{timestamp}.json"

    def _persist_smoke(self, bot_id: str, generated_at: str, payload: dict[str, Any]) -> None:
        self._persist_json(self._smoke_path(bot_id, generated_at), payload)
        self._persist_json(self.smoke_dir / f"latest-{bot_id}.json", payload)
        self._persist_json(self.smoke_dir / "latest.json", payload)

    def _persist_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    def _config_summary(self, config: dict[str, Any]) -> dict[str, Any]:
        exchange = config.get("exchange")
        pair_whitelist = config.get("pair_whitelist") or []
        pair_blacklist = config.get("pair_blacklist") or []
        return {
            "exchange": exchange,
            "strategy": config.get("strategy"),
            "stake_currency": config.get("stake_currency"),
            "stake_amount": config.get("stake_amount"),
            "timeframe": config.get("timeframe"),
            "max_open_trades": config.get("max_open_trades"),
            "short_allowed": bool(config.get("short_allowed", False)),
            "pair_whitelist_count": len(pair_whitelist),
            "pair_blacklist_count": len(pair_blacklist),
        }

    def _balance_summary(self, balance: Any, config: dict[str, Any]) -> dict[str, Any]:
        if isinstance(balance, dict):
            currencies = balance.get("currencies") or balance.get("balances") or []
            available = balance.get("available_capital")
            if available is None:
                available = balance.get("free")
            total = balance.get("total")
            if total is None:
                total = balance.get("total_bot")
            return {
                "stake_currency": config.get("stake_currency"),
                "available": available,
                "total": total,
                "currencies_count": len(currencies) if isinstance(currencies, list) else 0,
                "currencies": currencies if isinstance(currencies, list) else [],
            }
        return {
            "stake_currency": config.get("stake_currency"),
            "available": None,
            "total": None,
            "currencies_count": 0,
            "currencies": [],
        }

    def _profit_summary(self, profit: Any) -> dict[str, Any]:
        if isinstance(profit, dict):
            closed_trade_count = profit.get("closed_trade_count")
            if closed_trade_count is None:
                closed_trade_count = profit.get("trade_count")
            return {
                "trade_count": closed_trade_count or 0,
                "profit_closed_coin": profit.get("profit_closed_coin"),
                "profit_closed_ratio": profit.get("profit_closed_ratio"),
                "profit_all_coin": profit.get("profit_all_coin"),
                "profit_all_ratio": profit.get("profit_all_ratio"),
                "bot_start_date": profit.get("bot_start_date"),
            }
        return {
            "trade_count": 0,
            "profit_closed_coin": None,
            "profit_closed_ratio": None,
            "profit_all_coin": None,
            "profit_all_ratio": None,
            "bot_start_date": None,
        }

    def _performance_summary(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, list):
            top_pairs = []
            for item in payload[:10]:
                if not isinstance(item, dict):
                    continue
                top_pairs.append(
                    {
                        "pair": item.get("pair") or item.get("symbol"),
                        "profit_ratio": item.get("profit_ratio"),
                        "profit_abs": item.get("profit_abs"),
                        "count": item.get("count"),
                    }
                )
            return {
                "pair_count": len(payload),
                "top_pairs": top_pairs,
            }
        return {
            "pair_count": 0,
            "top_pairs": [],
        }

    def _count_summary(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return {
                "current_open_trades": payload.get("current"),
                "max_open_trades": payload.get("max"),
                "total_open_trades_stakes": payload.get("total_open_trades_stakes", payload.get("total_stake")),
            }
        return {
            "current_open_trades": None,
            "max_open_trades": None,
            "total_open_trades_stakes": None,
        }

    def _extract_open_trades(self, payload: Any) -> list[dict[str, Any]]:
        trades = payload.get("trades") if isinstance(payload, dict) else payload
        if not isinstance(trades, list):
            return []
        open_trades = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            if not bool(trade.get("is_open", False)):
                continue
            open_trades.append(
                {
                    "trade_id": trade.get("trade_id") or trade.get("id"),
                    "pair": trade.get("pair"),
                    "side": trade.get("side") or ("short" if trade.get("is_short") else "long"),
                    "is_short": bool(trade.get("is_short", False)),
                    "leverage": trade.get("leverage"),
                    "stake_amount": trade.get("stake_amount"),
                    "amount": trade.get("amount"),
                    "open_rate": trade.get("open_rate"),
                    "current_rate": trade.get("current_rate"),
                    "profit_ratio": trade.get("profit_ratio"),
                    "profit_abs": trade.get("profit_abs"),
                    "open_date": trade.get("open_date"),
                }
            )
        return open_trades

    def _extract_runtime_warnings(self, logs: list[str]) -> list[str]:
        warnings = []
        for line in reversed(logs):
            normalized = line.strip()
            if (
                " - WARNING - " in normalized
                or " - ERROR - " in normalized
                or " - CRITICAL - " in normalized
                or re.search(r"'type':\s*warning\b", normalized, flags=re.IGNORECASE)
                or re.search(r'"type":\s*"warning"', normalized, flags=re.IGNORECASE)
            ):
                warnings.append(normalized)
            if len(warnings) >= 10:
                break
        return list(reversed(warnings))

    def _snapshot_age_seconds(self, snapshot: dict[str, Any] | None) -> float | None:
        if snapshot is None:
            return None
        generated_at = snapshot.get("generated_at")
        if not generated_at:
            return None
        try:
            generated_dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            return None
        return max(0.0, round((datetime.now(timezone.utc) - generated_dt).total_seconds(), 2))

    def _build_smoke_result(
        self,
        *,
        bot_id: str,
        generated_at: str,
        status: str,
        dry_run: bool,
        runtime_mode: str,
        blocking_reason: str | None,
        steps: list[dict[str, Any]],
        warnings: list[str],
        snapshot_path: str | None,
    ) -> dict[str, Any]:
        return {
            "bot_id": bot_id,
            "generated_at": generated_at,
            "status": status,
            "dry_run": dry_run,
            "runtime_mode": runtime_mode,
            "blocking_reason": blocking_reason,
            "steps": steps,
            "warnings": warnings[:10],
            "snapshot_path": snapshot_path,
        }

    @staticmethod
    def _step(name: str, passed: bool, detail: str) -> dict[str, Any]:
        return {
            "name": name,
            "passed": passed,
            "detail": detail,
        }

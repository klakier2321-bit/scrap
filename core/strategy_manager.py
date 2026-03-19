"""Strategy and backtest data helpers for the control layer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any
import zipfile

from opentelemetry import trace
import yaml


tracer = trace.get_tracer(__name__)


class StrategyManager:
    """Provides read-only access to strategy and backtest assets."""

    def __init__(
        self,
        user_data_dir: Path | None = None,
        reports_dir: Path | None = None,
        dry_run_snapshots_dir: Path | None = None,
    ) -> None:
        self.user_data_dir = user_data_dir or (
            Path(__file__).resolve().parents[1]
            / "trading"
            / "freqtrade"
            / "user_data"
        )
        self.reports_dir = reports_dir or (
            Path(__file__).resolve().parents[1]
            / "data"
            / "ai_control"
            / "strategy_reports"
        )
        self.dry_run_snapshots_dir = dry_run_snapshots_dir or (
            self.reports_dir.parent / "dry_run_snapshots"
        )
        default_repo_root = self.user_data_dir.parents[2]
        workspace_root = Path("/workspace")
        if not (default_repo_root / "research").exists() and (workspace_root / "research").exists():
            self.repo_root = workspace_root
        else:
            self.repo_root = default_repo_root
        self.research_dir = self.repo_root / "research"

    def list_data_files(self) -> list[str]:
        data_dir = self.user_data_dir / "data"
        if not data_dir.exists():
            return []
        return sorted(
            str(path.relative_to(self.user_data_dir))
            for path in data_dir.rglob("*")
            if path.is_file()
        )

    def list_strategies(self) -> list[str]:
        strategies_dir = self.user_data_dir / "strategies"
        if not strategies_dir.exists():
            return []
        return sorted(path.name for path in strategies_dir.glob("*.py"))

    def discover_sample_strategy_name(self) -> str | None:
        sample_strategy = self.user_data_dir / "strategies" / "sample_strategy.py"
        if not sample_strategy.exists():
            return None
        content = sample_strategy.read_text(encoding="utf-8")
        match = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content)
        return match.group(1) if match else None

    def summary(self) -> dict[str, Any]:
        return {
            "data_files": self.list_data_files(),
            "strategies": self.list_strategies(),
            "sample_strategy": self.discover_sample_strategy_name(),
        }

    def latest_strategy_report(self, strategy_name: str | None = None) -> dict[str, Any] | None:
        with tracer.start_as_current_span("StrategyManager.latest_strategy_report") as span:
            backtest_payload = self._load_latest_backtest_payload()
            if backtest_payload is None:
                return None

            archive_path, payload, meta = backtest_payload
            strategy_payload = self._select_strategy_payload(payload, strategy_name)
            if strategy_payload is None:
                return None

            selected_strategy_name, strategy_results = strategy_payload
            span.set_attribute("crypto.strategy_name", selected_strategy_name)
            span.set_attribute("crypto.source_archive", archive_path.name)
            current_run_id = (meta.get(selected_strategy_name) or {}).get("run_id")
            persisted_report = self._load_persisted_latest_report(selected_strategy_name)
            if (
                persisted_report is not None
                and persisted_report.get("source_archive") == archive_path.name
                and persisted_report.get("source_run_id") == current_run_id
            ):
                return persisted_report

            report = self._build_strategy_report(
                strategy_name=selected_strategy_name,
                strategy_results=strategy_results,
                archive_path=archive_path,
                meta=meta,
            )
            self._persist_strategy_report(report)
            return report

    def list_strategy_reports(
        self,
        strategy_name: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.reports_dir.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in self.reports_dir.glob("*.json"):
            if path.name.startswith("latest"):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if strategy_name and payload.get("strategy_name") != strategy_name:
                continue
            reports.append(payload)
        reports.sort(key=lambda item: str(item.get("generated_at", "")), reverse=True)
        return reports[:limit]

    def latest_dry_run_snapshot(self, bot_id: str = "freqtrade") -> dict[str, Any] | None:
        snapshot_path = self.dry_run_snapshots_dir / f"latest-{bot_id}.json"
        if not snapshot_path.exists():
            return None
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def list_dry_run_snapshots(
        self,
        bot_id: str = "freqtrade",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.dry_run_snapshots_dir.exists():
            return []
        snapshots: list[dict[str, Any]] = []
        for path in sorted(self.dry_run_snapshots_dir.glob(f"{bot_id}-*.json"), reverse=True):
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
            if len(snapshots) >= limit:
                break
        return snapshots

    def latest_strategy_assessment(
        self,
        strategy_name: str | None = None,
    ) -> dict[str, Any] | None:
        if strategy_name:
            assessment_path = self._assessments_dir() / f"latest-{strategy_name}.json"
        else:
            assessment_path = self._assessments_dir() / "latest.json"
        if not assessment_path.exists():
            return None
        return json.loads(assessment_path.read_text(encoding="utf-8"))

    def list_candidate_manifests(self) -> list[dict[str, Any]]:
        candidates_dir = self.research_dir / "candidates"
        if not candidates_dir.exists():
            return []
        manifests: list[dict[str, Any]] = []
        for path in sorted(candidates_dir.glob("*/strategy_manifest.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            payload["_manifest_path"] = str(path.relative_to(self.repo_root))
            manifests.append(payload)
        manifests.sort(key=lambda item: str(item.get("strategy_id", "")))
        return manifests

    def get_candidate_manifest(self, candidate_id: str) -> dict[str, Any] | None:
        for manifest in self.list_candidate_manifests():
            if manifest.get("strategy_id") == candidate_id:
                return manifest
        return None

    def build_candidate_assessment(
        self,
        candidate_id: str,
        *,
        dry_run_health: dict[str, Any] | None = None,
        dry_run_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self.get_candidate_manifest(candidate_id)
        if manifest is None:
            raise KeyError(f"Unknown candidate_id: {candidate_id}")

        summary = self._load_optional_json(manifest.get("broad_backtest_summary_path"))
        risk_report = self._load_optional_json(manifest.get("risk_report_path"))
        promotion_decision = self._load_optional_markdown_metadata(
            manifest.get("promotion_decision_path")
        )

        lifecycle_status = str(manifest.get("status") or "unknown")
        active_side_policy = str(
            manifest.get("active_side_policy")
            or manifest.get("allowed_sides")
            or "unknown"
        )
        candidate_bot_id = manifest.get("candidate_bot_id")

        broad_status = self._derive_broad_backtest_status(summary)
        risk_status = self._derive_risk_gate_status(risk_report, promotion_decision)
        dry_run_status = self._derive_dry_run_gate_status(
            lifecycle_status=lifecycle_status,
            candidate_bot_id=candidate_bot_id,
            dry_run_health=dry_run_health,
            dry_run_snapshot=dry_run_snapshot,
            promotion_decision=promotion_decision,
        )

        blocked_reasons: list[str] = []
        if summary is None:
            blocked_reasons.append("Brakuje broad_backtest_summary.json dla kandydata.")
        elif broad_status != "pass":
            blocked_reasons.extend(str(note) for note in summary.get("notes", []))

        if risk_report is None:
            blocked_reasons.append("Brakuje risk_report.json dla kandydata.")
        elif risk_status not in {"ready", "warn"}:
            gate = risk_report.get("promotion_gate")
            if gate:
                blocked_reasons.append(f"Risk gate: {gate}.")

        if candidate_bot_id and lifecycle_status == "limited_dry_run_candidate":
            if dry_run_health is None:
                blocked_reasons.append("Brakuje health danych dla candidate dry-run bota.")
            elif not dry_run_health.get("ready", False):
                blocked_reasons.append(
                    "Candidate dry-run bot nie jest jeszcze gotowy albo nie ma swiezego snapshotu."
                )

        reason = promotion_decision.get("reason")
        if reason and reason not in blocked_reasons and broad_status != "pass":
            blocked_reasons.append(reason)

        return {
            "candidate_id": candidate_id,
            "strategy_name": manifest.get("strategy_name"),
            "market_type": manifest.get("market_type"),
            "lifecycle_status": lifecycle_status,
            "active_side_policy": active_side_policy,
            "allowed_sides": manifest.get("allowed_sides"),
            "candidate_bot_id": candidate_bot_id,
            "broad_backtest_status": broad_status,
            "risk_gate_status": risk_status,
            "dry_run_gate_status": dry_run_status,
            "overall_decision": promotion_decision.get("promotion_decision")
            or self._derive_candidate_decision(
                lifecycle_status=lifecycle_status,
                broad_status=broad_status,
                risk_status=risk_status,
                dry_run_status=dry_run_status,
            ),
            "next_step": promotion_decision.get("next_step")
            or self._default_candidate_next_step(
                lifecycle_status=lifecycle_status,
                broad_status=broad_status,
                dry_run_status=dry_run_status,
            ),
            "blocked_reasons": blocked_reasons,
            "manifest_path": manifest.get("_manifest_path"),
            "broad_backtest_summary_path": manifest.get("broad_backtest_summary_path"),
            "risk_report_path": manifest.get("risk_report_path"),
            "promotion_decision_path": manifest.get("promotion_decision_path"),
        }

    def get_assessment_for_report(
        self,
        strategy_name: str,
        source_run_id: str | None,
        source_archive: str | None,
    ) -> dict[str, Any] | None:
        assessment_path = self._assessments_dir() / f"{strategy_name}-{source_run_id or 'latest'}.json"
        if not assessment_path.exists():
            return None
        assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
        if assessment.get("source_archive") != source_archive:
            return None
        return assessment

    def persist_strategy_assessment(
        self,
        report: dict[str, Any],
        assessment: dict[str, Any],
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("StrategyManager.persist_strategy_assessment") as span:
            strategy_name = report["strategy_name"]
            source_run_id = report.get("source_run_id") or "latest"
            span.set_attribute("crypto.strategy_name", strategy_name)
            span.set_attribute("crypto.source_run_id", source_run_id)
            payload = {
                "strategy_name": strategy_name,
                "source_run_id": report.get("source_run_id"),
                "source_archive": report.get("source_archive"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **assessment,
            }
            assessments_dir = self._assessments_dir()
            assessments_dir.mkdir(parents=True, exist_ok=True)
            assessment_path = assessments_dir / f"{strategy_name}-{source_run_id}.json"
            assessment_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            (assessments_dir / f"latest-{strategy_name}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            (assessments_dir / "latest.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            return payload

    @staticmethod
    def merge_report_with_assessment(
        report: dict[str, Any],
        assessment: dict[str, Any] | None,
        readiness_gate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if assessment is None:
            merged = dict(report)
        else:
            merged = dict(report)
            merged["assessment_summary"] = assessment.get("summary")
            merged["assessment_recommendation"] = assessment.get("recommendation")
            merged["assessment_risk_level"] = assessment.get("risk_level")
            merged["assessment_generated_at"] = assessment.get("generated_at")
        if readiness_gate is not None:
            merged["readiness_gate"] = readiness_gate
            merged["readiness_status"] = readiness_gate.get("overall_status")
            merged["readiness_decision"] = readiness_gate.get("overall_decision")
            merged["readiness_summary"] = readiness_gate.get("summary")
        return merged

    def _load_latest_backtest_payload(self) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
        results_dir = self.user_data_dir / "backtest_results"
        marker_file = results_dir / ".last_result.json"
        if not marker_file.exists():
            return None

        marker = json.loads(marker_file.read_text(encoding="utf-8"))
        latest_archive_name = marker.get("latest_backtest")
        if not latest_archive_name:
            return None

        archive_path = results_dir / latest_archive_name
        if not archive_path.exists():
            return None

        meta_path = results_dir / latest_archive_name.replace(".zip", ".meta.json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

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
                return None
            payload = json.loads(bundle.read(json_name))

        return archive_path, payload, meta

    @staticmethod
    def _select_strategy_payload(
        payload: dict[str, Any],
        strategy_name: str | None,
    ) -> tuple[str, dict[str, Any]] | None:
        strategies = payload.get("strategy", {})
        if not strategies:
            return None
        if strategy_name:
            selected = strategies.get(strategy_name)
            if selected is None:
                return None
            return strategy_name, selected
        first_strategy_name = next(iter(strategies))
        return first_strategy_name, strategies[first_strategy_name]

    @staticmethod
    def _select_periodic_entries(strategy_results: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
        periodic_breakdown = strategy_results.get("periodic_breakdown") or {}
        for basis in ("day", "week", "month", "year"):
            entries = periodic_breakdown.get(basis)
            if isinstance(entries, list) and entries:
                return basis, entries
        return None, []

    @staticmethod
    def _compute_stability_score(entries: list[dict[str, Any]]) -> float | None:
        if not entries:
            return None
        profitable_periods = sum(1 for entry in entries if float(entry.get("profit_abs", 0.0)) > 0.0)
        return round(profitable_periods / len(entries), 4)

    def _build_strategy_report(
        self,
        *,
        strategy_name: str,
        strategy_results: dict[str, Any],
        archive_path: Path,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        timeframe = str(strategy_results.get("timeframe", "unknown"))
        profit_pct = float(strategy_results.get("profit_total", 0.0))
        absolute_profit = float(strategy_results.get("profit_total_abs", 0.0))
        drawdown_pct = float(strategy_results.get("max_drawdown_account", 0.0))
        drawdown_abs = float(strategy_results.get("max_drawdown_abs", 0.0))
        total_trades = int(strategy_results.get("total_trades", 0))
        win_rate = float(strategy_results.get("winrate", 0.0))
        breakdown_basis, breakdown_entries = self._select_periodic_entries(strategy_results)
        stability_score = self._compute_stability_score(breakdown_entries)
        evaluation = self._evaluate_strategy(
            profit_pct=profit_pct,
            drawdown_pct=drawdown_pct,
            total_trades=total_trades,
            win_rate=win_rate,
            stability_score=stability_score,
        )

        strategy_meta = meta.get(strategy_name, {})
        return {
            "strategy_name": strategy_name,
            "timeframe": timeframe,
            "backtest_start": str(strategy_results.get("backtest_start", "")),
            "backtest_end": str(strategy_results.get("backtest_end", "")),
            "profit_pct": profit_pct,
            "absolute_profit": absolute_profit,
            "drawdown_pct": drawdown_pct,
            "drawdown_abs": drawdown_abs,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "stability_score": stability_score,
            "stage_candidate": evaluation["stage_candidate"],
            "evaluation_status": evaluation["evaluation_status"],
            "rejection_reasons": evaluation["rejection_reasons"],
            "periodic_breakdown_basis": breakdown_basis,
            "source_run_id": strategy_meta.get("run_id"),
            "source_archive": archive_path.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _evaluate_strategy(
        *,
        profit_pct: float,
        drawdown_pct: float,
        total_trades: int,
        win_rate: float,
        stability_score: float | None,
    ) -> dict[str, Any]:
        rejection_reasons: list[str] = []
        if profit_pct <= 0:
            rejection_reasons.append("Profit strategy is not positive.")
        if drawdown_pct > 0.05:
            rejection_reasons.append("Drawdown exceeds the rejection threshold of 5%.")
        if total_trades < 20:
            rejection_reasons.append("Number of trades is below the minimum rejection floor of 20.")

        review_reasons: list[str] = []
        if profit_pct < 0.01:
            review_reasons.append("Profit is below the promotion threshold of 1%.")
        if drawdown_pct > 0.03:
            review_reasons.append("Drawdown is above the promotion threshold of 3%.")
        if total_trades < 30:
            review_reasons.append("Number of trades is below the promotion threshold of 30.")
        if win_rate < 0.50:
            review_reasons.append("Win rate is below the promotion threshold of 50%.")
        if stability_score is None:
            review_reasons.append(
                "Missing periodic breakdown data. The strategy cannot be promoted automatically."
            )
        elif stability_score < 0.60:
            review_reasons.append("Stability score is below the promotion threshold of 0.60.")

        stage_candidate = (
            profit_pct >= 0.01
            and drawdown_pct <= 0.03
            and total_trades >= 30
            and win_rate >= 0.50
            and stability_score is not None
            and stability_score >= 0.60
        )

        if stage_candidate:
            evaluation_status = "candidate_for_next_stage"
            reasons = []
        elif rejection_reasons:
            evaluation_status = "rejected"
            reasons = rejection_reasons
        else:
            evaluation_status = "needs_manual_review"
            reasons = review_reasons

        return {
            "stage_candidate": stage_candidate,
            "evaluation_status": evaluation_status,
            "rejection_reasons": reasons,
        }

    def _load_persisted_latest_report(self, strategy_name: str) -> dict[str, Any] | None:
        latest_report_path = self.reports_dir / f"latest-{strategy_name}.json"
        if not latest_report_path.exists():
            return None
        return json.loads(latest_report_path.read_text(encoding="utf-8"))

    def _load_optional_json(self, relative_path: str | None) -> dict[str, Any] | None:
        if not relative_path:
            return None
        path = self.repo_root / relative_path
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_optional_markdown_metadata(self, relative_path: str | None) -> dict[str, str]:
        if not relative_path:
            return {}
        path = self.repo_root / relative_path
        if not path.exists():
            return {}
        metadata: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ") or ":" not in stripped:
                continue
            key, value = stripped[2:].split(":", 1)
            metadata[key.strip()] = value.strip()
        return metadata

    @staticmethod
    def _derive_broad_backtest_status(summary: dict[str, Any] | None) -> str:
        if summary is None:
            return "blocked"
        result = str(summary.get("result") or "").strip().lower()
        if result == "pass_for_limited_dry_run":
            return "pass"
        if result in {"needs_rework", "fail", "failed"}:
            return "fail"
        if result == "rejected":
            return "rejected"
        return "blocked"

    @staticmethod
    def _derive_risk_gate_status(
        risk_report: dict[str, Any] | None,
        promotion_decision: dict[str, str],
    ) -> str:
        if promotion_decision.get("risk_gate"):
            return promotion_decision["risk_gate"]
        if risk_report is None:
            return "blocked"
        gate = str(risk_report.get("promotion_gate") or "").strip().lower()
        if gate == "ready_for_limited_dry_run":
            return "ready"
        status = str(risk_report.get("status") or "").strip().lower()
        if status in {"warn", "warning"}:
            return "warn"
        if status in {"ok", "pass", "ready"}:
            return "ready"
        if status:
            return status
        return "blocked"

    @staticmethod
    def _derive_dry_run_gate_status(
        *,
        lifecycle_status: str,
        candidate_bot_id: str | None,
        dry_run_health: dict[str, Any] | None,
        dry_run_snapshot: dict[str, Any] | None,
        promotion_decision: dict[str, str],
    ) -> str:
        if lifecycle_status != "limited_dry_run_candidate":
            return promotion_decision.get("dry_run_gate", "not_started")
        if not candidate_bot_id:
            return "blocked"
        if dry_run_health is None or dry_run_snapshot is None:
            return "blocked"
        if dry_run_health.get("ready"):
            return "ready"
        return "warn"

    @staticmethod
    def _derive_candidate_decision(
        *,
        lifecycle_status: str,
        broad_status: str,
        risk_status: str,
        dry_run_status: str,
    ) -> str:
        if lifecycle_status == "limited_dry_run_candidate" and dry_run_status == "ready":
            return "continue_limited_dry_run"
        if broad_status in {"blocked", "fail"}:
            return "build_broad_backtest_bundle_first"
        if risk_status not in {"ready", "warn"}:
            return "improve_risk_before_promotion"
        return "iterate_candidate"

    @staticmethod
    def _default_candidate_next_step(
        *,
        lifecycle_status: str,
        broad_status: str,
        dry_run_status: str,
    ) -> str:
        if lifecycle_status == "limited_dry_run_candidate" and dry_run_status != "ready":
            return "Uruchomic i potwierdzic osobny candidate dry-run bot."
        if broad_status == "blocked":
            return "Zbudowac lub odswiezyc broad_backtest_summary.json."
        if broad_status == "fail":
            return "Przerobic logike kandydata i uruchomic kolejny broad backtest bundle."
        return "Kontynuowac candidate loop i aktualizowac evidence bundle."

    def _assessments_dir(self) -> Path:
        return self.reports_dir / "assessments"

    def _persist_strategy_report(self, report: dict[str, Any]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        run_id = report.get("source_run_id") or "latest"
        strategy_name = report["strategy_name"]
        report_name = f"{strategy_name}-{run_id}.json"
        report_path = self.reports_dir / report_name
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        (self.reports_dir / f"latest-{strategy_name}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        (self.reports_dir / "latest.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

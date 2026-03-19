"""Canonical derivatives feed for regime detection and control-layer gating."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _normalize_pair_to_stem(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_").replace("-", "_")


def _read_feather_records(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    frame = pd.read_feather(path)
    if "date" in frame.columns:
        frame = frame.sort_values("date")
    return frame.to_dict("records")


class DerivativesFeed:
    """Builds canonical derivatives snapshots from vendor data or local proxy inputs."""

    def __init__(
        self,
        *,
        user_data_dir: Path,
        output_dir: Path,
        vendor_input_dir: Path,
        universe: list[str] | None = None,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.market_data_dir = user_data_dir / "data" / "binance" / "futures"
        self.output_dir = output_dir
        self.vendor_input_dir = vendor_input_dir
        self.universe = universe or ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    def latest_report(self) -> dict[str, Any] | None:
        path = self.output_dir / "latest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.output_dir.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in sorted(self.output_dir.glob("derivatives-*.json"), reverse=True):
            reports.append(json.loads(path.read_text(encoding="utf-8")))
            if len(reports) >= limit:
                break
        return reports

    def generate_report(self) -> dict[str, Any]:
        vendor_payload = self._load_vendor_payload()
        if vendor_payload is not None:
            report = self._canonicalize_vendor_payload(vendor_payload)
        else:
            report = self._build_proxy_report()
        self._write_report(report)
        return report

    def _load_vendor_payload(self) -> dict[str, Any] | None:
        latest_path = self.vendor_input_dir / "latest.json"
        if not latest_path.exists():
            return None
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _canonicalize_vendor_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbols = []
        input_symbols = payload.get("symbols") or []
        for item in input_symbols:
            if not isinstance(item, dict):
                continue
            pair = str(item.get("pair") or "").strip()
            if not pair:
                continue
            open_interest = _safe_float(item.get("open_interest"), None)
            oi_change_pct = _safe_float(item.get("open_interest_change_pct"), None)
            oi_acceleration = _safe_float(item.get("oi_acceleration"), None)
            price_change_pct = _safe_float(item.get("price_change_pct"), 0.0) or 0.0
            funding_bps = _safe_float(item.get("funding_bps"), None)
            liquidation_pressure_proxy = _safe_float(item.get("liquidation_pressure_proxy"), 0.0) or 0.0
            oi_price_agreement = self._derive_oi_price_agreement(
                price_change_pct=price_change_pct,
                oi_change_pct=oi_change_pct,
            )
            positioning_state = self._derive_positioning_state(
                price_change_pct=price_change_pct,
                oi_change_pct=oi_change_pct,
            )
            squeeze_risk = self._derive_squeeze_risk(
                price_change_pct=price_change_pct,
                oi_change_pct=oi_change_pct,
                funding_bps=funding_bps,
                liquidation_pressure_proxy=liquidation_pressure_proxy,
            )
            symbols.append(
                {
                    "pair": pair,
                    "open_interest": open_interest,
                    "open_interest_change_pct": oi_change_pct,
                    "oi_acceleration": oi_acceleration,
                    "price_change_pct": round(price_change_pct, 4),
                    "oi_price_agreement": oi_price_agreement,
                    "funding_bps": funding_bps,
                    "funding_extreme_flag": self._funding_extreme_flag(funding_bps),
                    "liquidation_pressure_proxy": round(liquidation_pressure_proxy, 4),
                    "positioning_state": positioning_state,
                    "squeeze_risk": squeeze_risk,
                    "vendor_fields_present": sorted(item.keys()),
                }
            )

        return {
            "generated_at": _now_iso(),
            "source": "external_vendor",
            "feed_status": "ok" if symbols else "missing",
            "vendor_available": bool(symbols),
            "universe": [item["pair"] for item in symbols],
            "symbols": symbols,
        }

    def _build_proxy_report(self) -> dict[str, Any]:
        symbols: list[dict[str, Any]] = []
        for pair in self.universe:
            stem = _normalize_pair_to_stem(pair)
            futures_1h = _read_feather_records(self.market_data_dir / f"{stem}-1h-futures.feather")
            mark_1h = _read_feather_records(self.market_data_dir / f"{stem}-1h-mark.feather")
            funding_path = self.market_data_dir / f"{stem}-1h-funding_rate.feather"
            funding_frame = _read_feather_records(funding_path) if funding_path.exists() else []
            latest = futures_1h[-1]
            previous = futures_1h[-2] if len(futures_1h) >= 2 else latest
            latest_close = _safe_float(latest.get("close"), 0.0) or 0.0
            previous_close = _safe_float(previous.get("close"), latest_close) or latest_close
            price_change_pct = 0.0
            if abs(previous_close) > 1e-9:
                price_change_pct = ((latest_close - previous_close) / previous_close) * 100.0
            volumes = [_safe_float(row.get("volume"), 0.0) or 0.0 for row in futures_1h[-24:]]
            latest_volume = volumes[-1] if volumes else 0.0
            volume_spike = latest_volume / max(median(volumes), 1e-9) if volumes else 1.0
            latest_mark = _safe_float((mark_1h[-1] if mark_1h else {}).get("close"), latest_close) or latest_close
            mark_premium_pct = ((latest_mark - latest_close) / max(latest_close, 1e-9)) * 100.0
            funding_bps = None
            if funding_frame:
                latest_funding = funding_frame[-1]
                for field_name in ("fundingRate", "funding_rate", "value", "close", "open"):
                    if field_name in latest_funding:
                        funding_bps = (_safe_float(latest_funding.get(field_name), 0.0) or 0.0) * 10000.0
                        break
            liquidation_pressure_proxy = min(
                1.0,
                abs(price_change_pct) * 0.12
                + max(0.0, volume_spike - 1.0) * 0.35
                + abs(mark_premium_pct) * 0.25,
            )
            symbols.append(
                {
                    "pair": pair,
                    "open_interest": None,
                    "open_interest_change_pct": None,
                    "oi_acceleration": None,
                    "price_change_pct": round(price_change_pct, 4),
                    "oi_price_agreement": "unknown",
                    "funding_bps": round(funding_bps, 4) if funding_bps is not None else None,
                    "funding_extreme_flag": self._funding_extreme_flag(funding_bps),
                    "liquidation_pressure_proxy": round(liquidation_pressure_proxy, 4),
                    "positioning_state": self._derive_proxy_positioning_state(
                        price_change_pct=price_change_pct,
                        funding_bps=funding_bps,
                        mark_premium_pct=mark_premium_pct,
                    ),
                    "squeeze_risk": self._derive_proxy_squeeze_risk(
                        funding_bps=funding_bps,
                        mark_premium_pct=mark_premium_pct,
                        liquidation_pressure_proxy=liquidation_pressure_proxy,
                    ),
                    "mark_premium_pct": round(mark_premium_pct, 4),
                    "volume_spike": round(volume_spike, 4),
                }
            )

        return {
            "generated_at": _now_iso(),
            "source": "external_vendor_proxy_fallback",
            "feed_status": "degraded_proxy",
            "vendor_available": False,
            "universe": [item["pair"] for item in symbols],
            "symbols": symbols,
        }

    @staticmethod
    def _funding_extreme_flag(funding_bps: float | None) -> bool:
        return abs(funding_bps or 0.0) >= 8.0

    @staticmethod
    def _derive_oi_price_agreement(*, price_change_pct: float, oi_change_pct: float | None) -> str:
        if oi_change_pct is None:
            return "unknown"
        if price_change_pct > 0 and oi_change_pct > 0:
            return "trend_supported_up"
        if price_change_pct < 0 and oi_change_pct > 0:
            return "trend_supported_down"
        if price_change_pct > 0 and oi_change_pct < 0:
            return "short_covering"
        if price_change_pct < 0 and oi_change_pct < 0:
            return "long_unwind"
        return "mixed"

    def _derive_positioning_state(self, *, price_change_pct: float, oi_change_pct: float | None) -> str:
        agreement = self._derive_oi_price_agreement(
            price_change_pct=price_change_pct,
            oi_change_pct=oi_change_pct,
        )
        mapping = {
            "trend_supported_up": "long_build",
            "trend_supported_down": "short_build",
            "short_covering": "short_covering",
            "long_unwind": "long_unwind",
        }
        return mapping.get(agreement, "mixed")

    @staticmethod
    def _derive_squeeze_risk(
        *,
        price_change_pct: float,
        oi_change_pct: float | None,
        funding_bps: float | None,
        liquidation_pressure_proxy: float,
    ) -> str:
        if oi_change_pct is None:
            return "unknown"
        score = 0.0
        if abs(price_change_pct) >= 1.0:
            score += 0.35
        if oi_change_pct <= -1.0:
            score += 0.35
        if abs(funding_bps or 0.0) >= 8.0:
            score += 0.2
        if liquidation_pressure_proxy >= 0.6:
            score += 0.2
        if score >= 0.75:
            return "high"
        if score >= 0.4:
            return "medium"
        return "low"

    @staticmethod
    def _derive_proxy_positioning_state(
        *,
        price_change_pct: float,
        funding_bps: float | None,
        mark_premium_pct: float,
    ) -> str:
        if price_change_pct < -0.5 and abs(mark_premium_pct) > 0.05:
            return "panic_downside_pressure"
        if price_change_pct > 0.5 and (funding_bps or 0.0) > 0:
            return "long_pressure_proxy"
        if price_change_pct < 0.5 and (funding_bps or 0.0) < 0:
            return "short_pressure_proxy"
        return "proxy_only"

    @staticmethod
    def _derive_proxy_squeeze_risk(
        *,
        funding_bps: float | None,
        mark_premium_pct: float,
        liquidation_pressure_proxy: float,
    ) -> str:
        score = 0.0
        if abs(funding_bps or 0.0) >= 8.0:
            score += 0.4
        if abs(mark_premium_pct) >= 0.1:
            score += 0.3
        if liquidation_pressure_proxy >= 0.6:
            score += 0.3
        if score >= 0.75:
            return "medium"
        return "low"

    def _write_report(self, report: dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = report["generated_at"].replace(":", "-")
        history_path = self.output_dir / f"derivatives-{stamp}.json"
        latest_path = self.output_dir / "latest.json"
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.output_dir, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(report, temp_file, ensure_ascii=True, indent=2)
        temp_path.replace(history_path)
        latest_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

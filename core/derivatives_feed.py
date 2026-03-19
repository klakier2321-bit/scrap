"""Canonical derivatives feed for regime detection and control-layer gating."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import requests
from statistics import median
from tempfile import NamedTemporaryFile
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _timestamp_ms_to_iso(value: Any) -> str | None:
    timestamp_ms = _safe_float(value, None)
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat()


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
        binance_enabled: bool = True,
        binance_base_url: str = "https://fapi.binance.com",
        binance_timeout_seconds: int = 8,
        binance_history_limit: int = 3,
        binance_period: str = "5m",
        stale_after_seconds: int = 900,
    ) -> None:
        self.user_data_dir = user_data_dir
        self.market_data_dir = user_data_dir / "data" / "binance" / "futures"
        self.output_dir = output_dir
        self.vendor_input_dir = vendor_input_dir
        self.universe = universe or ["BTC/USDT:USDT", "ETH/USDT:USDT"]
        self.binance_enabled = binance_enabled
        self.binance_base_url = binance_base_url.rstrip("/")
        self.binance_timeout_seconds = max(int(binance_timeout_seconds), 1)
        self.binance_history_limit = max(int(binance_history_limit), 2)
        self.binance_period = binance_period
        self.stale_after_seconds = max(int(stale_after_seconds), 60)

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
        vendor_payload = self._fetch_binance_vendor_payload()
        if vendor_payload is None:
            vendor_payload = self._load_vendor_payload()
        if vendor_payload is not None:
            report = self._canonicalize_vendor_payload(vendor_payload)
        else:
            report = self._build_proxy_report()
        self._write_report(report)
        return report

    def _fetch_binance_vendor_payload(self) -> dict[str, Any] | None:
        if not self.binance_enabled:
            return None

        symbols: list[dict[str, Any]] = []
        errors: list[str] = []
        for pair in self.universe:
            try:
                item = self._fetch_binance_symbol_payload(pair)
            except requests.RequestException as exc:
                errors.append(f"{pair}: {exc.__class__.__name__}")
                continue
            except (KeyError, ValueError, TypeError) as exc:
                errors.append(f"{pair}: {exc}")
                continue
            if item is not None:
                symbols.append(item)

        if not symbols:
            return None

        feed_status = "ok" if len(symbols) == len(self.universe) and not errors else "partial"
        fetched_at = _now_iso()
        source_timestamp = self._latest_symbol_timestamp(symbols)
        return {
            "source": "binance_futures_public_api",
            "feed_status": feed_status,
            "vendor_available": True,
            "vendor_name": "binance",
            "generated_at": fetched_at,
            "fetched_at": fetched_at,
            "source_timestamp": source_timestamp,
            "fetch_errors": errors,
            "symbols": symbols,
        }

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
                    "binance_symbol": item.get("binance_symbol"),
                    "taker_buy_sell_ratio": _safe_float(item.get("taker_buy_sell_ratio"), None),
                    "taker_imbalance": _safe_float(item.get("taker_imbalance"), None),
                    "long_short_account_ratio": _safe_float(item.get("long_short_account_ratio"), None),
                    "long_account_share": _safe_float(item.get("long_account_share"), None),
                    "short_account_share": _safe_float(item.get("short_account_share"), None),
                    "vendor_timestamp_ms": item.get("vendor_timestamp_ms"),
                    "liquidation_source_type": item.get("liquidation_source_type"),
                    "liquidation_event_confidence": item.get("liquidation_event_confidence"),
                }
            )

        fetched_at = payload.get("fetched_at") or payload.get("generated_at") or _now_iso()
        source_timestamp = payload.get("source_timestamp") or self._latest_symbol_timestamp(symbols)
        source = str(payload.get("source") or "external_vendor")
        feed_status = str(payload.get("feed_status") or ("ok" if symbols else "missing"))
        freshness = self._derive_freshness(
            fetched_at=fetched_at,
            source_timestamp=source_timestamp,
        )
        event_reliability = str(
            payload.get("event_reliability")
            or self._derive_event_reliability(
                source=source,
                feed_status=feed_status,
                is_stale=freshness["is_stale"],
            )
        )
        liquidation_source_type = str(
            payload.get("liquidation_source_type")
            or self._derive_liquidation_source_type(source=source)
        )
        liquidation_event_confidence = str(
            payload.get("liquidation_event_confidence")
            or self._derive_liquidation_event_confidence(
                event_reliability=event_reliability,
                liquidation_source_type=liquidation_source_type,
            )
        )
        return {
            "generated_at": payload.get("generated_at") or fetched_at,
            "fetched_at": fetched_at,
            "source_timestamp": source_timestamp,
            "age_seconds": freshness["age_seconds"],
            "is_stale": freshness["is_stale"],
            "source": str(payload.get("source") or "external_vendor"),
            "feed_status": feed_status,
            "vendor_available": bool(payload.get("vendor_available", bool(symbols))),
            "universe": [item["pair"] for item in symbols],
            "symbols": symbols,
            "vendor_name": payload.get("vendor_name"),
            "fetch_errors": payload.get("fetch_errors") or [],
            "event_reliability": event_reliability,
            "liquidation_source_type": liquidation_source_type,
            "liquidation_event_confidence": liquidation_event_confidence,
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
                    "liquidation_source_type": "proxy_from_local_market_data",
                    "liquidation_event_confidence": "low",
                    "mark_premium_pct": round(mark_premium_pct, 4),
                    "volume_spike": round(volume_spike, 4),
                }
            )

        fetched_at = _now_iso()
        source_timestamp = self._latest_proxy_source_timestamp()
        freshness = self._derive_freshness(
            fetched_at=fetched_at,
            source_timestamp=source_timestamp,
        )
        return {
            "generated_at": fetched_at,
            "fetched_at": fetched_at,
            "source_timestamp": source_timestamp,
            "age_seconds": freshness["age_seconds"],
            "is_stale": freshness["is_stale"],
            "source": "external_vendor_proxy_fallback",
            "feed_status": "degraded_proxy",
            "vendor_available": False,
            "universe": [item["pair"] for item in symbols],
            "symbols": symbols,
            "vendor_name": "proxy",
            "fetch_errors": [],
            "event_reliability": "low",
            "liquidation_source_type": "proxy_from_local_market_data",
            "liquidation_event_confidence": "low",
        }

    def _fetch_binance_symbol_payload(self, pair: str) -> dict[str, Any] | None:
        symbol = self._pair_to_binance_symbol(pair)
        open_interest_current = self._fetch_json(
            "/fapi/v1/openInterest",
            {"symbol": symbol},
        )
        open_interest_hist = self._sort_records_by_timestamp(
            self._fetch_json(
                "/futures/data/openInterestHist",
                {
                    "symbol": symbol,
                    "period": self.binance_period,
                    "limit": self.binance_history_limit,
                },
            )
        )
        funding_history = self._sort_records_by_timestamp(
            self._fetch_json(
                "/fapi/v1/fundingRate",
                {
                    "symbol": symbol,
                    "limit": self.binance_history_limit,
                },
            ),
            timestamp_keys=("fundingTime", "timestamp"),
        )
        taker_volume = self._sort_records_by_timestamp(
            self._fetch_json(
                "/futures/data/takerlongshortRatio",
                {
                    "symbol": symbol,
                    "period": self.binance_period,
                    "limit": self.binance_history_limit,
                },
            )
        )
        global_ratio = self._sort_records_by_timestamp(
            self._fetch_json(
                "/futures/data/globalLongShortAccountRatio",
                {
                    "symbol": symbol,
                    "period": self.binance_period,
                    "limit": self.binance_history_limit,
                },
            )
        )
        price_context = self._load_price_context(pair)

        latest_oi_record = open_interest_hist[-1] if open_interest_hist else {}
        previous_oi_record = open_interest_hist[-2] if len(open_interest_hist) >= 2 else latest_oi_record
        previous_previous_oi_record = open_interest_hist[-3] if len(open_interest_hist) >= 3 else previous_oi_record
        open_interest = _safe_float(
            open_interest_current.get("openInterest"),
            _safe_float(latest_oi_record.get("sumOpenInterest"), None),
        )
        latest_oi = _safe_float(latest_oi_record.get("sumOpenInterest"), open_interest)
        previous_oi = _safe_float(previous_oi_record.get("sumOpenInterest"), latest_oi)
        previous_previous_oi = _safe_float(previous_previous_oi_record.get("sumOpenInterest"), previous_oi)
        oi_change_pct = self._pct_change(latest_oi, previous_oi)
        previous_oi_change_pct = self._pct_change(previous_oi, previous_previous_oi)
        oi_acceleration = None
        if oi_change_pct is not None and previous_oi_change_pct is not None:
            oi_acceleration = oi_change_pct - previous_oi_change_pct

        latest_funding = funding_history[-1] if funding_history else {}
        funding_bps = None
        if latest_funding:
            funding_bps = (_safe_float(latest_funding.get("fundingRate"), 0.0) or 0.0) * 10000.0

        latest_taker = taker_volume[-1] if taker_volume else {}
        buy_sell_ratio = _safe_float(latest_taker.get("buySellRatio"), None)
        buy_vol = _safe_float(latest_taker.get("buyVol"), None)
        sell_vol = _safe_float(latest_taker.get("sellVol"), None)
        taker_imbalance = self._derive_taker_imbalance(
            buy_vol=buy_vol,
            sell_vol=sell_vol,
            buy_sell_ratio=buy_sell_ratio,
        )

        latest_global_ratio = global_ratio[-1] if global_ratio else {}
        long_short_account_ratio = _safe_float(latest_global_ratio.get("longShortRatio"), None)
        long_account_share = _safe_float(latest_global_ratio.get("longAccount"), None)
        short_account_share = _safe_float(latest_global_ratio.get("shortAccount"), None)

        price_change_pct = _safe_float(price_context.get("price_change_pct"), 0.0) or 0.0
        liquidation_pressure_proxy = self._derive_binance_liquidation_pressure_proxy(
            price_change_pct=price_change_pct,
            oi_change_pct=oi_change_pct,
            funding_bps=funding_bps,
            taker_imbalance=taker_imbalance,
            long_short_account_ratio=long_short_account_ratio,
        )
        vendor_timestamp_ms = (
            latest_global_ratio.get("timestamp")
            or latest_taker.get("timestamp")
            or latest_funding.get("fundingTime")
            or open_interest_current.get("time")
            or latest_oi_record.get("timestamp")
        )

        return {
            "pair": pair,
            "binance_symbol": symbol,
            "open_interest": open_interest,
            "open_interest_change_pct": oi_change_pct,
            "oi_acceleration": oi_acceleration,
            "price_change_pct": price_change_pct,
            "funding_bps": funding_bps,
            "liquidation_pressure_proxy": liquidation_pressure_proxy,
            "taker_buy_sell_ratio": buy_sell_ratio,
            "taker_imbalance": taker_imbalance,
            "long_short_account_ratio": long_short_account_ratio,
            "long_account_share": long_account_share,
            "short_account_share": short_account_share,
            "vendor_timestamp_ms": vendor_timestamp_ms,
            "liquidation_source_type": "proxy_from_binance_public_api",
            "liquidation_event_confidence": "medium",
        }

    def _fetch_json(self, path: str, params: dict[str, Any]) -> Any:
        response = requests.get(
            f"{self.binance_base_url}{path}",
            params=params,
            timeout=self.binance_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _derive_freshness(self, *, fetched_at: str, source_timestamp: str | None) -> dict[str, Any]:
        fetched_at_dt = _parse_iso(fetched_at)
        source_timestamp_dt = _parse_iso(source_timestamp)
        age_seconds = None
        if fetched_at_dt and source_timestamp_dt:
            age_seconds = max((fetched_at_dt - source_timestamp_dt).total_seconds(), 0.0)
        is_stale = bool(age_seconds is not None and age_seconds > self.stale_after_seconds)
        return {
            "age_seconds": round(age_seconds, 4) if age_seconds is not None else None,
            "is_stale": is_stale,
        }

    @staticmethod
    def _latest_symbol_timestamp(symbols: list[dict[str, Any]]) -> str | None:
        timestamp_values = [
            _safe_float(item.get("vendor_timestamp_ms"), None)
            for item in symbols
            if _safe_float(item.get("vendor_timestamp_ms"), None) is not None
        ]
        if not timestamp_values:
            return None
        return _timestamp_ms_to_iso(max(timestamp_values))

    def _latest_proxy_source_timestamp(self) -> str | None:
        timestamps: list[str] = []
        for pair in self.universe:
            stem = _normalize_pair_to_stem(pair)
            futures_path = self.market_data_dir / f"{stem}-1h-futures.feather"
            if not futures_path.exists():
                continue
            try:
                futures_1h = _read_feather_records(futures_path)
            except Exception:
                continue
            if futures_1h and futures_1h[-1].get("date"):
                timestamps.append(str(futures_1h[-1]["date"]))
        if not timestamps:
            return None
        ordered = sorted(
            (item for item in (_parse_iso(value) for value in timestamps) if item is not None),
            reverse=True,
        )
        if not ordered:
            return None
        return ordered[0].isoformat()

    @staticmethod
    def _derive_event_reliability(*, source: str, feed_status: str, is_stale: bool) -> str:
        if source == "binance_futures_public_api":
            reliability = "medium"
        elif source == "external_vendor":
            reliability = "medium"
        elif source == "replay_proxy":
            reliability = "low"
        else:
            reliability = "low"
        if feed_status == "partial" and reliability == "medium":
            reliability = "low"
        if is_stale and reliability == "medium":
            reliability = "low"
        return reliability

    @staticmethod
    def _derive_liquidation_source_type(*, source: str) -> str:
        if source == "binance_futures_public_api":
            return "proxy_from_binance_public_api"
        if source == "external_vendor":
            return "snapshot_defined_by_local_vendor"
        if source == "replay_proxy":
            return "proxy_from_replay_market_data"
        return "proxy_from_local_market_data"

    @staticmethod
    def _derive_liquidation_event_confidence(*, event_reliability: str, liquidation_source_type: str) -> str:
        if liquidation_source_type == "snapshot_defined_by_local_vendor":
            return "medium"
        if liquidation_source_type == "proxy_from_binance_public_api":
            return "medium" if event_reliability == "medium" else "low"
        return "low"

    def _load_price_context(self, pair: str) -> dict[str, float | None]:
        stem = _normalize_pair_to_stem(pair)
        futures_path = self.market_data_dir / f"{stem}-1h-futures.feather"
        if futures_path.exists():
            try:
                futures_1h = _read_feather_records(futures_path)
            except Exception:
                futures_1h = []
            if futures_1h:
                latest = futures_1h[-1]
                previous = futures_1h[-2] if len(futures_1h) >= 2 else latest
                latest_close = _safe_float(latest.get("close"), 0.0) or 0.0
                previous_close = _safe_float(previous.get("close"), latest_close) or latest_close
                return {
                    "price_change_pct": self._pct_change(latest_close, previous_close) or 0.0,
                }

        if self.binance_enabled:
            return self._fetch_binance_price_context(pair)

        return {
            "price_change_pct": 0.0,
        }

    def _fetch_binance_price_context(self, pair: str) -> dict[str, float | None]:
        symbol = self._pair_to_binance_symbol(pair)
        klines = self._fetch_json(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "1h",
                "limit": 2,
            },
        )
        if not isinstance(klines, list) or not klines:
            return {"price_change_pct": 0.0}
        latest = klines[-1]
        previous = klines[-2] if len(klines) >= 2 else latest
        latest_close = _safe_float(latest[4] if len(latest) > 4 else None, 0.0) or 0.0
        previous_close = _safe_float(previous[4] if len(previous) > 4 else None, latest_close) or latest_close
        return {
            "price_change_pct": self._pct_change(latest_close, previous_close) or 0.0,
        }

    @staticmethod
    def _pair_to_binance_symbol(pair: str) -> str:
        base_quote = pair.split(":", maxsplit=1)[0]
        return base_quote.replace("/", "").replace("-", "")

    @staticmethod
    def _sort_records_by_timestamp(
        records: Any,
        *,
        timestamp_keys: tuple[str, ...] = ("timestamp", "time"),
    ) -> list[dict[str, Any]]:
        if not isinstance(records, list):
            return []
        result = [item for item in records if isinstance(item, dict)]
        return sorted(
            result,
            key=lambda item: next(
                (
                    int(_safe_float(item.get(key), 0.0) or 0)
                    for key in timestamp_keys
                    if item.get(key) is not None
                ),
                0,
            ),
        )

    @staticmethod
    def _pct_change(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or abs(previous) <= 1e-9:
            return None
        return ((current - previous) / previous) * 100.0

    @staticmethod
    def _derive_taker_imbalance(
        *,
        buy_vol: float | None,
        sell_vol: float | None,
        buy_sell_ratio: float | None,
    ) -> float:
        if buy_vol is not None and sell_vol is not None and (buy_vol + sell_vol) > 1e-9:
            return (buy_vol - sell_vol) / (buy_vol + sell_vol)
        if buy_sell_ratio is not None:
            return (buy_sell_ratio - 1.0) / max(abs(buy_sell_ratio) + 1.0, 1e-9)
        return 0.0

    @staticmethod
    def _derive_binance_liquidation_pressure_proxy(
        *,
        price_change_pct: float,
        oi_change_pct: float | None,
        funding_bps: float | None,
        taker_imbalance: float,
        long_short_account_ratio: float | None,
    ) -> float:
        score = min(abs(price_change_pct) * 0.12, 0.35)
        score += min(abs(taker_imbalance) * 0.85, 0.25)
        if oi_change_pct is not None and oi_change_pct < 0:
            score += min(abs(oi_change_pct) * 0.06, 0.2)
        if abs(funding_bps or 0.0) >= 8.0:
            score += 0.1
        if long_short_account_ratio is not None:
            score += min(abs(long_short_account_ratio - 1.0) * 0.15, 0.1)
        return round(min(max(score, 0.0), 1.0), 4)

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

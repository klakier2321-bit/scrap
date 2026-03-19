"""Generate a sanitized control status report for executive monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
MONITORING_DIR = REPO_ROOT / "monitoring"
REPORTS_DIR = MONITORING_DIR / "reports"
ALLOWED_READ_DIRS = {
    "dry_run_snapshots": REPO_ROOT / "data" / "ai_control" / "dry_run_snapshots",
    "strategy_reports": REPO_ROOT / "data" / "ai_control" / "strategy_reports",
    "dry_run_smoke": REPO_ROOT / "data" / "ai_control" / "dry_run_smoke",
}
REQUIRED_FIELDS = {
    "dry_run_snapshots": {"generated_at", "dry_run", "snapshot_status", "runmode"},
    "strategy_reports": {"generated_at", "strategy_name", "evaluation_status"},
    "dry_run_smoke": {"status", "generated_at"},
}
SENSITIVE_KEYWORDS = {
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "private_key",
    "account_id",
    "wallet",
    "credential",
    "authorization",
}
PATH_PATTERN = re.compile(r"([A-Za-z]:)?/[^ \n\t]+")
URL_PATTERN = re.compile(r"https?://[^\s]+")
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
HEXISH_PATTERN = re.compile(r"\b[a-fA-F0-9]{24,}\b")


@dataclass(slots=True)
class SourceSnapshot:
    source_name: str
    file_count: int
    latest_file_name: str | None
    latest_generated_at: str | None
    latest_status: str | None
    issues: list[str]
    latest_record: dict[str, Any] | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_within_directory(path: Path, allowed_dir: Path) -> bool:
    try:
        path.resolve().relative_to(allowed_dir.resolve())
        return True
    except ValueError:
        return False


def _is_within_reports_dir(path: Path) -> bool:
    return _is_within_directory(path, REPORTS_DIR)


def _safe_filename(name: str) -> str:
    candidate = Path(name).name
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate).strip("._")
    return sanitized or "control_status.json"


def _sanitize_text(value: str) -> str:
    sanitized = PATH_PATTERN.sub("[sciezka]", value)
    sanitized = URL_PATTERN.sub("[url]", sanitized)
    sanitized = EMAIL_PATTERN.sub("[email]", sanitized)
    sanitized = HEXISH_PATTERN.sub("[token]", sanitized)
    for keyword in SENSITIVE_KEYWORDS:
        sanitized = re.sub(keyword, "[wrazliwe_pole]", sanitized, flags=re.IGNORECASE)
    return sanitized


def mask_sensitive(value: Any, *, key_hint: str = "") -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(keyword in lowered for keyword in SENSITIVE_KEYWORDS):
                masked[key] = "[masked]"
                continue
            masked[key] = mask_sensitive(item, key_hint=key)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(item, key_hint=key_hint) for item in value]
    if isinstance(value, str):
        lowered_hint = key_hint.lower()
        if any(keyword in lowered_hint for keyword in SENSITIVE_KEYWORDS):
            return "[masked]"
        return _sanitize_text(value)
    return value


def _read_json_records(base_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not base_dir.exists():
        return []
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(base_dir.glob("*.json")):
        if not path.is_file():
            continue
        if not _is_within_directory(path, base_dir):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append((path, data))
    return records


def load_snapshots() -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    return {name: _read_json_records(base_dir) for name, base_dir in ALLOWED_READ_DIRS.items()}


def validate_schema(source_name: str, records: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    issues: list[str] = []
    if not records:
        return [f"Brak plikow JSON dla zrodla {source_name}."]
    required = REQUIRED_FIELDS.get(source_name, set())
    latest_path, latest_record = records[-1]
    missing = sorted(field for field in required if field not in latest_record)
    if missing:
        issues.append(
            _sanitize_text(
                f"Plik {latest_path.name} nie zawiera wymaganych pol: {', '.join(missing)}."
            )
        )
    if source_name == "dry_run_snapshots":
        if latest_record.get("snapshot_status") not in {"fresh", "ok"}:
            issues.append("Najnowszy snapshot dry_run nie ma akceptowalnego statusu.")
    if source_name == "dry_run_smoke":
        if latest_record.get("status") != "pass":
            issues.append("Najnowszy smoke test dry_run nie zakonczyl sie statusem pass.")
    return [_sanitize_text(issue) for issue in issues]


def _source_snapshot(source_name: str, records: list[tuple[Path, dict[str, Any]]]) -> SourceSnapshot:
    issues = validate_schema(source_name, records)
    if not records:
        return SourceSnapshot(
            source_name=source_name,
            file_count=0,
            latest_file_name=None,
            latest_generated_at=None,
            latest_status="missing",
            issues=issues,
            latest_record=None,
        )

    latest_path, latest_record = records[-1]
    latest_generated_at = latest_record.get("generated_at") or latest_record.get("checked_at")
    latest_status = (
        latest_record.get("snapshot_status")
        or latest_record.get("evaluation_status")
        or latest_record.get("status")
    )
    return SourceSnapshot(
        source_name=source_name,
        file_count=len(records),
        latest_file_name=latest_path.name,
        latest_generated_at=latest_generated_at,
        latest_status=str(latest_status) if latest_status is not None else None,
        issues=issues,
        latest_record=mask_sensitive(latest_record),
    )


def produce_anonymized_json(report: dict[str, Any]) -> dict[str, Any]:
    return mask_sensitive(report)


def produce_summary_md(report: dict[str, Any]) -> str:
    lines = [
        "# Control Status",
        "",
        f"- Wygenerowano: {report['generated_at']}",
        f"- Status ogolny: {report['overall_status']}",
        f"- Podsumowanie: {report['summary']}",
        "",
        "## Zrodla",
        "",
    ]
    for source in report["sources"]:
        lines.extend(
            [
                f"### {source['source_name']}",
                f"- Liczba plikow: {source['file_count']}",
                f"- Najnowszy plik: {source['latest_file_name'] or 'brak'}",
                f"- Najnowszy znacznik czasu: {source['latest_generated_at'] or 'brak'}",
                f"- Status: {source['latest_status'] or 'brak'}",
            ]
        )
        if source["issues"]:
            lines.append("- Uwagi:")
            for issue in source["issues"]:
                lines.append(f"  - {issue}")
        else:
            lines.append("- Uwagi: brak krytycznych uwag.")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _atomic_write_text(out_path: Path, content: str) -> None:
    if not _is_within_reports_dir(out_path):
        raise ValueError("Write path must stay inside monitoring/reports/.")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=REPORTS_DIR) as handle:
        temp_path = Path(handle.name)
        try:
            handle.write(content)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    os.replace(temp_path, out_path)


def _atomic_write_json(out_path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def create_report() -> dict[str, Any]:
    loaded = load_snapshots()
    sources = [_source_snapshot(name, records) for name, records in loaded.items()]
    issue_count = sum(len(source.issues) for source in sources)
    overall_status = "ok" if issue_count == 0 else "warn"
    summary = (
        "Control plane i raporty wygladaja stabilnie."
        if issue_count == 0
        else f"Wykryto {issue_count} uwag wymagajacych sprawdzenia przed dalsza automatyzacja."
    )
    return {
        "generated_at": _now_iso(),
        "overall_status": overall_status,
        "summary": _sanitize_text(summary),
        "sources": [
            {
                "source_name": source.source_name,
                "file_count": source.file_count,
                "latest_file_name": source.latest_file_name,
                "latest_generated_at": source.latest_generated_at,
                "latest_status": source.latest_status,
                "issues": [_sanitize_text(issue) for issue in source.issues],
                "latest_record": source.latest_record,
            }
            for source in sources
        ],
    }


def write_report_files(report: dict[str, Any]) -> tuple[Path, Path]:
    summary_path = REPORTS_DIR / _safe_filename("control_status_SUMMARY.md")
    json_path = REPORTS_DIR / _safe_filename("control_status.json")
    _atomic_write_text(summary_path, produce_summary_md(report))
    _atomic_write_json(json_path, produce_anonymized_json(report))
    return summary_path, json_path


def main() -> int:
    report = create_report()
    write_report_files(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Campaign statistics, daily JSON logs, and export helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Literal


CampaignState = Literal["stopped", "running", "paused", "completed"]
DeliveryStatus = Literal["sent", "error"]

LOG_FIELDS = (
    "timestamp",
    "recipient",
    "smtp_used",
    "proxy_used",
    "subject",
    "status",
    "error_text",
    "control",
    "had_cc",
    "had_bcc",
)


class StatsError(RuntimeError):
    """Raised when stats or log operations fail."""


@dataclass(frozen=True)
class LogEntry:
    """One campaign log record."""

    timestamp: str
    recipient: str
    smtp_used: str
    proxy_used: str
    subject: str
    status: DeliveryStatus
    control: bool = False
    had_cc: bool = False
    had_bcc: bool = False
    error_text: str = ""

    def as_dict(self) -> dict[str, str | bool]:
        """Return JSON-ready log entry."""
        data: dict[str, str | bool] = {
            "timestamp": self.timestamp,
            "recipient": self.recipient,
            "smtp_used": self.smtp_used,
            "proxy_used": self.proxy_used,
            "subject": self.subject,
            "status": self.status,
            "control": self.control,
            "had_cc": self.had_cc,
            "had_bcc": self.had_bcc,
        }
        if self.status == "error":
            data["error_text"] = self.error_text
        return data

    def as_csv_row(self) -> dict[str, str | bool]:
        """Return CSV-ready row with stable columns."""
        data = self.as_dict()
        data.setdefault("error_text", "")
        return {field_name: data.get(field_name, "") for field_name in LOG_FIELDS}


@dataclass
class SMTPStats:
    """Per-SMTP session statistics."""

    email: str
    sent: int = 0
    errors: int = 0
    status: str = "unknown"
    last_activity: str = ""


@dataclass
class ProxyStats:
    """Per-proxy session statistics."""

    address: str
    used: int = 0
    errors: int = 0
    status: str = "unknown"


@dataclass(frozen=True)
class GlobalStats:
    """Global campaign metrics."""

    sent_total: int
    queued: int
    errors: int
    speed_per_minute: float
    started_at: str
    current_time: str
    eta: str
    total_recipients: int
    processed: int
    progress_ratio: float
    state: CampaignState


@dataclass(frozen=True)
class StatsSnapshot:
    """Thread-safe immutable snapshot for GUI rendering."""

    global_stats: GlobalStats
    smtp_stats: tuple[SMTPStats, ...] = field(default_factory=tuple)
    proxy_stats: tuple[ProxyStats, ...] = field(default_factory=tuple)


class StatsManager:
    """Thread-safe campaign stats store."""

    def __init__(self, logs_dir: str | Path = "logs") -> None:
        self.logs_dir = Path(logs_dir)
        self._lock = threading.RLock()
        self._state: CampaignState = "stopped"
        self._started_at: datetime | None = None
        self._total_recipients = 0
        self._queued = 0
        self._sent_total = 0
        self._errors = 0
        self._smtp_stats: dict[str, SMTPStats] = {}
        self._proxy_stats: dict[str, ProxyStats] = {}

    def start_campaign(self, total_recipients: int) -> None:
        """Initialize stats for a campaign."""
        with self._lock:
            self._state = "running"
            self._started_at = datetime.now(timezone.utc)
            self._total_recipients = max(0, total_recipients)
            self._queued = max(0, total_recipients)
            self._sent_total = 0
            self._errors = 0
            self._smtp_stats.clear()
            self._proxy_stats.clear()

    def stop_campaign(self) -> None:
        """Mark campaign as stopped."""
        with self._lock:
            self._state = "stopped"

    def pause_campaign(self) -> None:
        """Mark campaign as paused."""
        with self._lock:
            self._state = "paused"

    def complete_campaign(self) -> None:
        """Mark campaign as completed."""
        with self._lock:
            self._state = "completed"
            self._queued = 0

    def set_queue_size(self, queued: int, total_recipients: int | None = None) -> None:
        """Update queue size from sender/queue manager."""
        with self._lock:
            self._queued = max(0, queued)
            if total_recipients is not None:
                self._total_recipients = max(0, total_recipients)

    def register_smtp(self, email: str, status: str = "unknown") -> None:
        """Ensure SMTP account appears in per-account stats."""
        if not email:
            return
        with self._lock:
            item = self._smtp_stats.setdefault(email, SMTPStats(email=email))
            item.status = status

    def register_proxy(self, address: str, status: str = "unknown") -> None:
        """Ensure proxy appears in per-proxy stats."""
        if not address:
            return
        with self._lock:
            item = self._proxy_stats.setdefault(address, ProxyStats(address=address))
            item.status = status

    def set_smtp_status(self, email: str, status: str) -> None:
        """Update SMTP status."""
        if not email:
            return
        with self._lock:
            item = self._smtp_stats.setdefault(email, SMTPStats(email=email))
            item.status = status
            item.last_activity = _utc_now_string()

    def set_proxy_status(self, address: str, status: str) -> None:
        """Update proxy status."""
        if not address:
            return
        with self._lock:
            item = self._proxy_stats.setdefault(address, ProxyStats(address=address))
            item.status = status

    def record_delivery(
        self,
        recipient: str,
        smtp_used: str,
        proxy_used: str,
        subject: str,
        status: DeliveryStatus,
        error_text: str = "",
        control: bool = False,
        had_cc: bool = False,
        had_bcc: bool = False,
    ) -> LogEntry:
        """Record one send attempt and append it to the daily JSON log."""
        entry = LogEntry(
            timestamp=_utc_now_string(),
            recipient=recipient,
            smtp_used=smtp_used,
            proxy_used=proxy_used,
            subject=subject,
            status=status,
            error_text=error_text,
            control=control,
            had_cc=had_cc,
            had_bcc=had_bcc,
        )

        with self._lock:
            if self._started_at is None:
                self._started_at = datetime.now(timezone.utc)
            if self._state == "stopped":
                self._state = "running"

            if status == "sent":
                self._sent_total += 1
            else:
                self._errors += 1

            if self._queued > 0:
                self._queued -= 1

            if smtp_used:
                smtp_item = self._smtp_stats.setdefault(smtp_used, SMTPStats(email=smtp_used))
                smtp_item.last_activity = entry.timestamp
                if status == "sent":
                    smtp_item.sent += 1
                else:
                    smtp_item.errors += 1

            if proxy_used:
                proxy_item = self._proxy_stats.setdefault(proxy_used, ProxyStats(address=proxy_used))
                if status == "sent":
                    proxy_item.used += 1
                else:
                    proxy_item.errors += 1

            if self._queued == 0 and self._total_recipients > 0:
                self._state = "completed"

        append_log_entry(self.logs_dir, entry)
        return entry

    def snapshot(self) -> StatsSnapshot:
        """Return an immutable snapshot suitable for GUI updates."""
        now = datetime.now(timezone.utc)
        with self._lock:
            started_at = self._started_at
            elapsed_seconds = (now - started_at).total_seconds() if started_at else 0.0
            processed = self._sent_total + self._errors
            speed = (self._sent_total / elapsed_seconds * 60.0) if elapsed_seconds > 0 else 0.0
            progress_ratio = processed / self._total_recipients if self._total_recipients else 0.0
            progress_ratio = min(max(progress_ratio, 0.0), 1.0)

            eta = "-"
            if self._state == "running" and speed > 0 and self._queued > 0:
                minutes_left = self._queued / speed
                eta_seconds = int(minutes_left * 60)
                eta_dt = now.timestamp() + eta_seconds
                eta = datetime.fromtimestamp(eta_dt, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            global_stats = GlobalStats(
                sent_total=self._sent_total,
                queued=self._queued,
                errors=self._errors,
                speed_per_minute=speed,
                started_at=_format_dt(started_at),
                current_time=_format_dt(now),
                eta=eta,
                total_recipients=self._total_recipients,
                processed=processed,
                progress_ratio=progress_ratio,
                state=self._state,
            )
            smtp_items = tuple(SMTPStats(**vars(item)) for item in self._smtp_stats.values())
            proxy_items = tuple(ProxyStats(**vars(item)) for item in self._proxy_stats.values())

        return StatsSnapshot(global_stats=global_stats, smtp_stats=smtp_items, proxy_stats=proxy_items)


def get_stats_manager() -> StatsManager:
    """Return the process-wide stats manager used by GUI and sender."""
    return _GLOBAL_STATS_MANAGER


def append_log_entry(logs_dir: str | Path, entry: LogEntry) -> Path:
    """Append one entry to logs/YYYY-MM-DD.json as a valid JSON array."""
    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)
    log_path = logs_path / f"{_today_utc()}.json"
    record = entry.as_dict()

    with _LOG_FILE_LOCK:
        records = _read_log_records(log_path)
        records.append(record)
        _write_log_records(log_path, records)

    return log_path


def read_log_records(logs_dir: str | Path = "logs", date_value: str | None = None) -> list[dict[str, object]]:
    """Read daily log records."""
    log_path = Path(logs_dir) / f"{date_value or _today_utc()}.json"
    with _LOG_FILE_LOCK:
        return _read_log_records(log_path)


def export_log(
    destination: str | Path,
    export_format: Literal["json", "csv"],
    logs_dir: str | Path = "logs",
    date_value: str | None = None,
) -> Path:
    """Export a daily log to JSON or CSV."""
    records = read_log_records(logs_dir, date_value)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    if export_format == "json":
        destination_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return destination_path

    if export_format == "csv":
        with destination_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=LOG_FIELDS)
            writer.writeheader()
            for record in records:
                row = {field_name: record.get(field_name, "") for field_name in LOG_FIELDS}
                writer.writerow(row)
        return destination_path

    raise StatsError(f"Неподдерживаемый формат экспорта: {export_format}")


def _read_log_records(log_path: Path) -> list[dict[str, object]]:
    if not log_path.exists() or log_path.stat().st_size == 0:
        return []

    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StatsError(f"Не удалось прочитать JSON-лог {log_path}: {exc}") from exc

    if not isinstance(data, list):
        raise StatsError(f"JSON-лог должен быть массивом: {log_path}")
    return [record for record in data if isinstance(record, dict)]


def _write_log_records(log_path: Path, records: list[dict[str, object]]) -> None:
    temp_path = log_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(log_path)


def _utc_now_string() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


_LOG_FILE_LOCK = threading.Lock()
_GLOBAL_STATS_MANAGER = StatsManager()

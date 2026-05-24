"""Campaign preset save/load helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlsplit

from core.app_state import AppState
from core.content import ContentError
from core.proxy_manager import ProxySourceError
from core.smtp_manager import SMTPSourceError
from core.storage import StorageError, read_recipients_csv


PRESETS_DIR = Path("data") / "presets"
PRESET_VERSION = 1


class PresetError(RuntimeError):
    """Raised when a preset cannot be saved or loaded."""


@dataclass(frozen=True)
class PresetResult:
    """Preset operation result with non-fatal warnings."""

    path: str
    warnings: tuple[str, ...] = ()


def save_preset(app_state: AppState, destination: str | Path) -> PresetResult:
    """Save current campaign settings and loaded file paths to JSON."""
    destination_path = _normalize_preset_path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    payload = build_preset_payload(app_state)
    try:
        destination_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise PresetError(f"Не удалось сохранить пресет: {exc}") from exc

    return PresetResult(path=str(destination_path))


def load_preset(app_state: AppState, source: str | Path) -> PresetResult:
    """Load a preset and apply every available setting."""
    source_path = Path(source).resolve()
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PresetError(f"Не удалось прочитать пресет: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PresetError(f"Пресет повреждён: {exc}") from exc

    if not isinstance(payload, dict):
        raise PresetError("Пресет должен быть JSON-объектом")

    warnings: list[str] = []
    _clear_runtime_for_preset(app_state)
    _load_proxy_sources(app_state, payload, warnings)
    _load_file_list(
        "SMTP",
        _get_list(payload, "smtp_files"),
        lambda path: app_state.smtp_manager.load_from_file(path),
        warnings,
    )
    _load_optional_file("темы", _get_string(payload, "subjects_file"), app_state.subject_manager.load_from_file, warnings)
    _load_optional_file("тела", _get_string(payload, "bodies_file"), app_state.body_manager.load_from_file, warnings)
    _load_file_list(
        "ссылки",
        _get_list(payload, "link_files"),
        lambda path: app_state.link_manager.load_from_file(path),
        warnings,
    )
    _load_optional_file(
        "имена отправителей",
        _get_string(payload, "senders_file"),
        app_state.load_sender_names_from_file,
        warnings,
    )
    _load_recipients(app_state, _get_string(payload, "recipients_file"), warnings)

    app_state.unique_links_per_message = bool(payload.get("unique_links_per_message", False))
    app_state.from_email_only = bool(payload.get("from_email_only", False))
    _apply_control_settings(app_state, payload.get("control"))
    _apply_cc_bcc_settings(app_state, payload.get("additional_recipients"))
    _apply_send_settings(app_state, payload.get("send_settings"))

    return PresetResult(path=str(source_path), warnings=tuple(warnings))


def _clear_runtime_for_preset(app_state: AppState) -> None:
    app_state.proxy_manager.clear()
    app_state.smtp_manager.clear()
    app_state.subject_manager.clear()
    app_state.body_manager.clear()
    app_state.link_manager.clear()
    app_state.sender_name_manager.clear()
    app_state.clear_recipients()
    app_state.control_recipients = []
    app_state.control_every = 0
    app_state.set_cc_bcc_settings([], [], 0.0, 0.0)


def build_preset_payload(app_state: AppState) -> dict[str, object]:
    """Build a serializable preset payload from current runtime state."""
    proxy_sources = _unique(record.source for record in app_state.proxy_manager.get_all())
    proxy_files = [source for source in proxy_sources if not _is_http_url(source)]
    proxy_urls = [source for source in proxy_sources if _is_http_url(source)]
    smtp_files = _unique(account.source for account in app_state.smtp_manager.get_all())

    return {
        "version": PRESET_VERSION,
        "proxy_files": proxy_files,
        "proxy_urls": proxy_urls,
        "smtp_files": smtp_files,
        "subjects_file": app_state.subject_manager.source,
        "bodies_file": app_state.body_manager.source,
        "link_files": app_state.link_manager.get_sources(),
        "senders_file": app_state.sender_name_manager.source,
        "recipients_file": app_state.recipients_source,
        "unique_links_per_message": app_state.unique_links_per_message,
        "from_email_only": app_state.from_email_only,
        "control": {
            "every": app_state.control_every,
            "addresses": [str(item.get("email", "")) for item in app_state.control_recipients],
        },
        "additional_recipients": {
            "cc_addresses": app_state.cc_addresses,
            "bcc_addresses": app_state.bcc_addresses,
            "cc_percent": app_state.cc_percent,
            "bcc_percent": app_state.bcc_percent,
        },
        "send_settings": {
            "delay_seconds": app_state.delay_seconds,
            "emails_per_minute": app_state.emails_per_minute,
            "jitter_seconds": app_state.jitter_seconds,
        },
    }


def _load_proxy_sources(app_state: AppState, payload: dict[str, object], warnings: list[str]) -> None:
    _load_file_list(
        "прокси",
        _get_list(payload, "proxy_files"),
        lambda path: app_state.proxy_manager.load_from_file(path),
        warnings,
    )
    for url in _get_list(payload, "proxy_urls"):
        if not _is_http_url(url):
            warnings.append(f"Некорректный URL прокси в пресете: {url}")
            continue
        try:
            app_state.proxy_manager.load_from_url(url)
        except (ProxySourceError, OSError) as exc:
            warnings.append(f"Не удалось загрузить прокси URL {url}: {exc}")


def _load_recipients(app_state: AppState, path_value: str, warnings: list[str]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if not path.exists():
        warnings.append(f"Файл базы не найден: {path}")
        return
    try:
        recipients = read_recipients_csv(path)
    except StorageError as exc:
        warnings.append(f"Не удалось загрузить базу {path}: {exc}")
        return
    app_state.set_recipients(recipients, source=path)


def _load_optional_file(label: str, path_value: str, loader: object, warnings: list[str]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if not path.exists():
        warnings.append(f"Файл {label} не найден: {path}")
        return
    try:
        loader(path)  # type: ignore[misc]
    except (ContentError, ProxySourceError, SMTPSourceError, StorageError, OSError) as exc:
        warnings.append(f"Не удалось загрузить {label} {path}: {exc}")


def _load_file_list(label: str, paths: list[str], loader: object, warnings: list[str]) -> None:
    for path_value in paths:
        _load_optional_file(label, path_value, loader, warnings)


def _apply_control_settings(app_state: AppState, raw: object) -> None:
    data = raw if isinstance(raw, dict) else {}
    every = _safe_int(data.get("every"), 0)
    addresses = [email for email in _string_list(data.get("addresses")) if email]
    app_state.control_every = max(0, every)
    app_state.control_recipients = [{"email": email.lower(), "name": "CONTROL"} for email in addresses]


def _apply_cc_bcc_settings(app_state: AppState, raw: object) -> None:
    data = raw if isinstance(raw, dict) else {}
    app_state.set_cc_bcc_settings(
        cc_addresses=_string_list(data.get("cc_addresses")),
        bcc_addresses=_string_list(data.get("bcc_addresses")),
        cc_percent=_safe_float(data.get("cc_percent"), 0.0),
        bcc_percent=_safe_float(data.get("bcc_percent"), 0.0),
    )


def _apply_send_settings(app_state: AppState, raw: object) -> None:
    data = raw if isinstance(raw, dict) else {}
    app_state.set_send_settings(
        delay_seconds=_safe_float(data.get("delay_seconds"), 0.0),
        emails_per_minute=_safe_float(data.get("emails_per_minute"), 0.0),
        jitter_seconds=_safe_float(data.get("jitter_seconds"), 0.0),
    )


def _normalize_preset_path(destination: str | Path) -> Path:
    path = Path(destination)
    if not path.suffix:
        path = path.with_suffix(".json")
    if not path.is_absolute():
        path = PRESETS_DIR / path
    return path.resolve()


def _get_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key, "")
    return value if isinstance(value, str) else ""


def _get_list(payload: dict[str, object], key: str) -> list[str]:
    return _string_list(payload.get(key))


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_int(raw: object, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _safe_float(raw: object, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _is_http_url(value: str) -> bool:
    return urlsplit(value).scheme.lower() in {"http", "https"}


def _unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

"""Proxy loading, parsing, validation, and session rotation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from urllib.parse import quote, unquote, urlsplit

import requests

from core.storage import StorageError, parse_text_lines, read_text_lines


DEFAULT_PROXY_TEST_URL = "http://httpbin.org/ip"
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_RETRIES = 2
DEFAULT_MAX_WORKERS = 12

_LOG_LOCK = threading.Lock()


class ProxyStatus:
    """Proxy status values used by core and GUI."""

    UNCHECKED = "unchecked"
    CHECKING = "checking"
    ALIVE = "alive"
    DEAD = "dead"


class ProxyParseError(ValueError):
    """Raised when a proxy line has an unsupported format."""


class ProxySourceError(RuntimeError):
    """Raised when proxies cannot be loaded from a source."""


@dataclass
class ProxyRecord:
    """One normalized proxy entry for the current session."""

    raw: str
    source: str
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    status: str = ProxyStatus.UNCHECKED
    last_error: str = ""
    last_checked_at: str = ""
    external_ip: str = ""

    @property
    def proxy_url(self) -> str:
        """Return a requests-compatible proxy URL."""
        auth = ""
        if self.username:
            auth_user = quote(self.username, safe="")
            auth_pass = quote(self.password or "", safe="")
            auth = f"{auth_user}:{auth_pass}@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def display_name(self) -> str:
        """Return a safe proxy label for GUI and logs."""
        if self.username:
            return f"{self.scheme}://{self.username}:***@{self.host}:{self.port}"
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def key(self) -> str:
        """Return a stable duplicate key for the current session."""
        return self.proxy_url

    def as_dict(self) -> dict[str, str | int | None]:
        """Return a serializable safe snapshot."""
        return {
            "source": self.source,
            "scheme": self.scheme,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "status": self.status,
            "last_error": self.last_error,
            "last_checked_at": self.last_checked_at,
            "external_ip": self.external_ip,
            "display_name": self.display_name,
        }


@dataclass(frozen=True)
class ProxyLoadResult:
    """Summary of one proxy load operation."""

    source: str
    total_lines: int
    loaded: int
    invalid: int
    duplicates: int
    replaced: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ProxyCheckResult:
    """Summary of proxy validation."""

    checked: int
    alive: int
    dead: int


def parse_proxy_line(raw_line: str, source: str = "manual") -> ProxyRecord:
    """Parse one proxy line into a normalized proxy record."""
    line = raw_line.strip()
    if not line:
        raise ProxyParseError("пустая строка")

    if "://" in line:
        return _parse_url_proxy(line, source)

    return _parse_colon_proxy(line, source)


class ProxyManager:
    """Session proxy store with loading, validation, and live rotation."""

    def __init__(
        self,
        test_url: str = DEFAULT_PROXY_TEST_URL,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        max_workers: int = DEFAULT_MAX_WORKERS,
        logs_dir: str | Path = "logs",
    ) -> None:
        self.test_url = test_url
        self.timeout = timeout
        self.retries = max(1, retries)
        self.max_workers = max(1, max_workers)
        self.logs_dir = Path(logs_dir)
        self._proxies: list[ProxyRecord] = []
        self._lock = threading.RLock()
        self._rotation_index = 0

    def load_from_file(self, path: str | Path) -> ProxyLoadResult:
        """Load and replace proxies from one local file source."""
        file_path = Path(path).resolve()
        try:
            lines = read_text_lines(file_path)
        except StorageError as exc:
            _write_json_log(self.logs_dir, "proxy_load_file_failed", "error", error=str(exc))
            raise ProxySourceError(str(exc)) from exc

        result = self._replace_source(str(file_path), lines)
        _write_json_log(
            self.logs_dir,
            "proxy_load_file",
            "info",
            source=str(file_path),
            loaded=result.loaded,
            invalid=result.invalid,
            duplicates=result.duplicates,
            replaced=result.replaced,
        )
        return result

    def load_from_url(self, url: str) -> ProxyLoadResult:
        """Load and replace proxies from one HTTP proxy-list URL."""
        clean_url = url.strip()
        if not clean_url:
            raise ProxySourceError("URL прокси-листа пустой")

        scheme = urlsplit(clean_url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ProxySourceError("URL должен начинаться с http:// или https://")

        text = self._get_text_with_retries(clean_url)
        lines = parse_text_lines(text)
        result = self._replace_source(clean_url, lines)
        _write_json_log(
            self.logs_dir,
            "proxy_load_url",
            "info",
            source=clean_url,
            loaded=result.loaded,
            invalid=result.invalid,
            duplicates=result.duplicates,
            replaced=result.replaced,
        )
        return result

    def check_all(self) -> ProxyCheckResult:
        """Check every loaded proxy and mark dead ones for this session."""
        with self._lock:
            proxies = list(self._proxies)

        if not proxies:
            return ProxyCheckResult(checked=0, alive=0, dead=0)

        for proxy in proxies:
            self._mark_proxy(proxy, ProxyStatus.CHECKING)

        alive = 0
        dead = 0
        workers = min(self.max_workers, len(proxies))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(self.check_proxy, proxy): proxy for proxy in proxies}
            for future in as_completed(future_map):
                proxy = future_map[future]
                try:
                    checked_proxy = future.result()
                except Exception as exc:
                    self._mark_proxy(proxy, ProxyStatus.DEAD, error=str(exc))
                    dead += 1
                    continue

                if checked_proxy.status == ProxyStatus.ALIVE:
                    alive += 1
                else:
                    dead += 1

        _write_json_log(
            self.logs_dir,
            "proxy_check_all",
            "info",
            checked=len(proxies),
            alive=alive,
            dead=dead,
        )
        return ProxyCheckResult(checked=len(proxies), alive=alive, dead=dead)

    def check_proxy(self, proxy: ProxyRecord) -> ProxyRecord:
        """Check one proxy with a test HTTP GET request."""
        request_proxies = {"http": proxy.proxy_url, "https": proxy.proxy_url}
        last_error = ""

        for attempt in range(1, self.retries + 1):
            try:
                response = requests.get(
                    self.test_url,
                    proxies=request_proxies,
                    timeout=self.timeout,
                    headers={"User-Agent": "CHARLY-MAILER/1.0"},
                )
                response.raise_for_status()
                external_ip = _extract_external_ip(response)
                self._mark_proxy(proxy, ProxyStatus.ALIVE, external_ip=external_ip)
                _write_json_log(
                    self.logs_dir,
                    "proxy_check_ok",
                    "info",
                    proxy=proxy.display_name,
                    external_ip=external_ip,
                )
                return proxy
            except requests.RequestException as exc:
                last_error = _short_error(exc)
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 5))

        self._mark_proxy(proxy, ProxyStatus.DEAD, error=last_error)
        _write_json_log(
            self.logs_dir,
            "proxy_check_failed",
            "warning",
            proxy=proxy.display_name,
            error=last_error,
        )
        return proxy

    def prepare_live_rotation(self) -> list[ProxyRecord]:
        """Re-check proxies before a campaign and return only live entries."""
        self.check_all()
        return self.get_live_proxies()

    def get_all(self) -> list[ProxyRecord]:
        """Return a snapshot of all loaded proxies."""
        with self._lock:
            return list(self._proxies)

    def get_live_proxies(self) -> list[ProxyRecord]:
        """Return proxies that are alive in the current session."""
        with self._lock:
            return [proxy for proxy in self._proxies if proxy.status == ProxyStatus.ALIVE]

    def get_live_proxy_urls(self) -> list[str]:
        """Return requests-compatible URLs for live proxies only."""
        return [proxy.proxy_url for proxy in self.get_live_proxies()]

    def get_next_live_proxy(self) -> ProxyRecord | None:
        """Return the next live proxy for round-robin rotation."""
        live = self.get_live_proxies()
        if not live:
            return None

        with self._lock:
            proxy = live[self._rotation_index % len(live)]
            self._rotation_index += 1
            return proxy

    def clear(self) -> None:
        """Clear all loaded proxies from the current session."""
        with self._lock:
            self._proxies.clear()
            self._rotation_index = 0

    def _replace_source(self, source: str, lines: list[str]) -> ProxyLoadResult:
        records: list[ProxyRecord] = []
        errors: list[str] = []
        invalid = 0

        for line in lines:
            try:
                records.append(parse_proxy_line(line, source=source))
            except ProxyParseError as exc:
                invalid += 1
                errors.append(f"{line}: {exc}")

        with self._lock:
            replaced = sum(1 for proxy in self._proxies if proxy.source == source)
            kept = [proxy for proxy in self._proxies if proxy.source != source]
            existing_keys = {proxy.key for proxy in kept}
            source_keys: set[str] = set()
            loaded = 0
            duplicates = 0

            for proxy in records:
                if proxy.key in existing_keys or proxy.key in source_keys:
                    duplicates += 1
                    continue
                kept.append(proxy)
                source_keys.add(proxy.key)
                loaded += 1

            self._proxies = kept
            self._rotation_index = 0

        return ProxyLoadResult(
            source=source,
            total_lines=len(lines),
            loaded=loaded,
            invalid=invalid,
            duplicates=duplicates,
            replaced=replaced,
            errors=tuple(errors[:20]),
        )

    def _get_text_with_retries(self, url: str) -> str:
        last_error = ""
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.get(
                    url,
                    timeout=self.timeout,
                    headers={"User-Agent": "CHARLY-MAILER/1.0"},
                )
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_error = _short_error(exc)
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 5))

        _write_json_log(self.logs_dir, "proxy_load_url_failed", "error", source=url, error=last_error)
        raise ProxySourceError(f"Не удалось загрузить прокси по URL: {last_error}")

    def _mark_proxy(
        self,
        proxy: ProxyRecord,
        status: str,
        error: str = "",
        external_ip: str = "",
    ) -> None:
        with self._lock:
            proxy.status = status
            proxy.last_error = error
            proxy.external_ip = external_ip
            proxy.last_checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_url_proxy(line: str, source: str) -> ProxyRecord:
    parsed = urlsplit(line)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ProxyParseError("поддерживаются только http:// и https://")
    if not parsed.hostname:
        raise ProxyParseError("не найден host")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ProxyParseError("порт должен быть числом") from exc

    if port is None:
        raise ProxyParseError("не найден port")
    _validate_host_port(parsed.hostname, port)

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None

    return ProxyRecord(
        raw=line,
        source=source,
        scheme=scheme,
        host=parsed.hostname,
        port=port,
        username=username,
        password=password,
    )


def _parse_colon_proxy(line: str, source: str) -> ProxyRecord:
    parts = line.split(":")
    if len(parts) == 2:
        host, port_raw = parts
        username = None
        password = None
    elif len(parts) >= 4:
        host = parts[0]
        port_raw = parts[1]
        username = parts[2]
        password = ":".join(parts[3:])
    else:
        raise ProxyParseError("формат должен быть host:port или host:port:user:pass")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ProxyParseError("порт должен быть числом") from exc

    host = host.strip()
    username = username.strip() if username else None
    password = password.strip() if password else None
    _validate_host_port(host, port)

    return ProxyRecord(
        raw=line,
        source=source,
        scheme="http",
        host=host,
        port=port,
        username=username,
        password=password,
    )


def _validate_host_port(host: str, port: int) -> None:
    if not host or any(char.isspace() for char in host):
        raise ProxyParseError("host пустой или содержит пробелы")
    if port < 1 or port > 65535:
        raise ProxyParseError("порт вне диапазона 1-65535")


def _extract_external_ip(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:120]

    origin = data.get("origin")
    if isinstance(origin, str):
        return origin.split(",")[0].strip()
    return ""


def _short_error(exc: BaseException) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:300] if message else exc.__class__.__name__


def _write_json_log(
    logs_dir: Path,
    event: str,
    level: str,
    **payload: object,
) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    record = {
        "ts": now.isoformat(),
        "level": level,
        "event": event,
        **payload,
    }
    log_path = logs_dir / f"{now.date().isoformat()}.jsonl"
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))

    with _LOG_LOCK:
        with log_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

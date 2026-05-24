"""SMTP account loading, login validation, and live account rotation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
import base64
import json
from pathlib import Path
import socket
import smtplib
import ssl
import threading
from urllib.parse import unquote, urlsplit

from core.storage import StorageError, read_text_lines


DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MAX_WORKERS = 8

_LOG_LOCK = threading.Lock()


class SMTPStatus:
    """SMTP account statuses used by core and GUI."""

    UNKNOWN = "unknown"
    CHECKING = "checking"
    ALIVE = "alive"
    DEAD = "dead"


class SMTPEncryption:
    """Resolved SMTP encryption modes."""

    SSL = "ssl"
    STARTTLS = "starttls"
    OPPORTUNISTIC_STARTTLS = "opportunistic_starttls"
    NONE = "none"


class SMTPParseError(ValueError):
    """Raised when a SMTP account line has an unsupported format."""


class SMTPSourceError(RuntimeError):
    """Raised when SMTP accounts cannot be loaded from a source."""


class SMTPProxyError(OSError):
    """Raised when a SMTP proxy tunnel cannot be established."""


@dataclass
class SMTPAccount:
    """One SMTP account for the current session."""

    raw: str
    source: str
    host: str
    port: int
    email: str
    password: str
    status: str = SMTPStatus.UNKNOWN
    sent_count: int = 0
    last_error: str = ""
    last_checked_at: str = ""
    bound_proxy_url: str | None = None
    use_global_proxy_pool: bool = True

    @property
    def key(self) -> str:
        """Return a stable duplicate key for the current session."""
        return f"{self.host}:{self.port}:{self.email}".lower()

    @property
    def endpoint(self) -> str:
        """Return host:port label."""
        return f"{self.host}:{self.port}"

    @property
    def encryption(self) -> str:
        """Return encryption mode inferred from port."""
        return detect_encryption(self.port)

    @property
    def proxy_mode_label(self) -> str:
        """Return a safe proxy mode label for GUI."""
        if self.bound_proxy_url:
            return "привязанный прокси"
        if self.use_global_proxy_pool:
            return "общий пул прокси"
        return "без прокси"

    def as_dict(self) -> dict[str, str | int | bool | None]:
        """Return a serializable safe snapshot without password."""
        return {
            "source": self.source,
            "host": self.host,
            "port": self.port,
            "email": self.email,
            "status": self.status,
            "sent_count": self.sent_count,
            "last_error": self.last_error,
            "last_checked_at": self.last_checked_at,
            "bound_proxy": bool(self.bound_proxy_url),
            "use_global_proxy_pool": self.use_global_proxy_pool,
            "encryption": self.encryption,
        }


@dataclass(frozen=True)
class SMTPLoadResult:
    """Summary of one SMTP load operation."""

    source: str
    total_lines: int
    loaded: int
    invalid: int
    duplicates: int
    replaced: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class SMTPLoginResult:
    """Result of checking one SMTP account."""

    account_key: str
    ok: bool
    status: str
    message: str
    smtp_code: int | None = None
    temporary: bool = False


@dataclass(frozen=True)
class SMTPCheckSummary:
    """Summary of SMTP account validation."""

    checked: int
    alive: int
    dead: int
    unknown: int


def detect_encryption(port: int) -> str:
    """Infer SMTP encryption mode from port."""
    if port == 465:
        return SMTPEncryption.SSL
    if port == 587:
        return SMTPEncryption.STARTTLS
    if port == 25:
        return SMTPEncryption.OPPORTUNISTIC_STARTTLS
    return SMTPEncryption.NONE


def parse_smtp_line(raw_line: str, source: str = "manual") -> SMTPAccount:
    """Parse host:port:email:password into an account."""
    line = raw_line.strip()
    if not line:
        raise SMTPParseError("пустая строка")

    parts = line.split(":", 3)
    if len(parts) != 4:
        raise SMTPParseError("формат должен быть host:port:email:password")

    host, port_raw, email, password = (part.strip() for part in parts)
    if not host or any(char.isspace() for char in host):
        raise SMTPParseError("host пустой или содержит пробелы")
    if not email or "@" not in email:
        raise SMTPParseError("email некорректный")
    if not password:
        raise SMTPParseError("password пустой")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise SMTPParseError("порт должен быть числом") from exc

    if port < 1 or port > 65535:
        raise SMTPParseError("порт вне диапазона 1-65535")

    return SMTPAccount(
        raw=line,
        source=source,
        host=host,
        port=port,
        email=email,
        password=password,
    )


class SMTPManager:
    """Session SMTP account store with validation and live rotation."""

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_workers: int = DEFAULT_MAX_WORKERS,
        logs_dir: str | Path = "logs",
    ) -> None:
        self.timeout = timeout
        self.max_workers = max(1, max_workers)
        self.logs_dir = Path(logs_dir)
        self._accounts: list[SMTPAccount] = []
        self._lock = threading.RLock()
        self._rotation_index = 0

    def load_from_file(self, path: str | Path) -> SMTPLoadResult:
        """Load and replace SMTP accounts from one local file source."""
        file_path = Path(path).resolve()
        try:
            lines = read_text_lines(file_path)
        except StorageError as exc:
            _write_json_log(self.logs_dir, "smtp_load_file_failed", "error", error=str(exc))
            raise SMTPSourceError(str(exc)) from exc

        result = self._replace_source(str(file_path), lines)
        _write_json_log(
            self.logs_dir,
            "smtp_load_file",
            "info",
            source=str(file_path),
            loaded=result.loaded,
            invalid=result.invalid,
            duplicates=result.duplicates,
            replaced=result.replaced,
        )
        return result

    def check_all(self) -> SMTPCheckSummary:
        """Check every loaded SMTP account."""
        with self._lock:
            accounts = list(self._accounts)

        if not accounts:
            return SMTPCheckSummary(checked=0, alive=0, dead=0, unknown=0)

        for account in accounts:
            self._mark_account(account, SMTPStatus.CHECKING)

        workers = min(self.max_workers, len(accounts))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(self.check_account, account): account for account in accounts}
            for future in as_completed(future_map):
                account = future_map[future]
                try:
                    future.result()
                except Exception as exc:
                    self._mark_account(account, SMTPStatus.DEAD, error=_short_error(exc))

        summary = self._summary(checked=len(accounts))
        _write_json_log(
            self.logs_dir,
            "smtp_check_all",
            "info",
            checked=summary.checked,
            alive=summary.alive,
            dead=summary.dead,
            unknown=summary.unknown,
        )
        return summary

    def check_account_by_key(self, account_key: str) -> SMTPLoginResult:
        """Check one SMTP account by key."""
        account = self.get_by_key(account_key)
        if account is None:
            raise SMTPSourceError("SMTP-аккаунт не найден")
        self._mark_account(account, SMTPStatus.CHECKING)
        return self.check_account(account)

    def check_account(self, account: SMTPAccount, proxy_url: str | None = None) -> SMTPLoginResult:
        """Connect and login to one SMTP account."""
        chosen_proxy = account.bound_proxy_url or proxy_url

        try:
            with self._open_connection(account, chosen_proxy) as server:
                server.login(account.email, account.password)
            self._mark_account(account, SMTPStatus.ALIVE, error="")
            result = SMTPLoginResult(account.key, True, SMTPStatus.ALIVE, "Логин успешен")
            _write_json_log(self.logs_dir, "smtp_check_ok", "info", email=account.email, host=account.endpoint)
            return result
        except smtplib.SMTPAuthenticationError as exc:
            return self._handle_smtp_auth_error(account, exc)
        except smtplib.SMTPResponseException as exc:
            return self._handle_smtp_response_error(account, exc)
        except (socket.timeout, TimeoutError) as exc:
            message = f"Таймаут подключения или логина: {_short_error(exc)}"
            return self._fail_account(account, SMTPStatus.DEAD, message)
        except (socket.gaierror, ConnectionRefusedError, ConnectionResetError, SMTPProxyError) as exc:
            message = f"Сервер недоступен: {_short_error(exc)}"
            return self._fail_account(account, SMTPStatus.DEAD, message)
        except smtplib.SMTPException as exc:
            message = f"SMTP ошибка: {_short_error(exc)}"
            return self._fail_account(account, SMTPStatus.DEAD, message)
        except OSError as exc:
            message = f"Ошибка сети: {_short_error(exc)}"
            return self._fail_account(account, SMTPStatus.DEAD, message)

    def send_message(
        self,
        account: SMTPAccount,
        message: EmailMessage,
        proxy_url: str | None = None,
    ) -> None:
        """Login and send one MIME message through an SMTP account."""
        chosen_proxy = account.bound_proxy_url or proxy_url
        with self._open_connection(account, chosen_proxy) as server:
            server.login(account.email, account.password)
            server.send_message(message)

    def prepare_live_rotation(self) -> list[SMTPAccount]:
        """Re-check accounts before a campaign and return live entries."""
        self.check_all()
        return self.get_live_accounts()

    def get_all(self) -> list[SMTPAccount]:
        """Return a snapshot of all loaded SMTP accounts."""
        with self._lock:
            return list(self._accounts)

    def get_by_key(self, account_key: str) -> SMTPAccount | None:
        """Return account by stable key."""
        with self._lock:
            for account in self._accounts:
                if account.key == account_key:
                    return account
        return None

    def get_live_accounts(self) -> list[SMTPAccount]:
        """Return accounts that are alive in the current session."""
        with self._lock:
            return [account for account in self._accounts if account.status == SMTPStatus.ALIVE]

    def get_next_live_account(self) -> SMTPAccount | None:
        """Return the next live account for round-robin rotation."""
        live = self.get_live_accounts()
        if not live:
            return None

        with self._lock:
            account = live[self._rotation_index % len(live)]
            self._rotation_index += 1
            return account

    def record_send_success(self, account: SMTPAccount) -> None:
        """Increment the per-session sent counter for one account."""
        with self._lock:
            account.sent_count += 1
            account.last_error = ""

    def record_auth_failure(self, account: SMTPAccount, smtp_code: int | None, message: str) -> None:
        """Handle auth failure during future sending."""
        if smtp_code is not None and 500 <= smtp_code <= 599:
            self._mark_account(account, SMTPStatus.DEAD, error=message)
            return
        if smtp_code is not None and 400 <= smtp_code <= 499:
            self._mark_account(account, account.status, error=message)
            return
        self._mark_account(account, SMTPStatus.DEAD, error=message)

    def assign_proxy(self, account_key: str, proxy_url: str | None) -> None:
        """Bind a specific proxy URL to one SMTP account."""
        account = self.get_by_key(account_key)
        if account is None:
            raise SMTPSourceError("SMTP-аккаунт не найден")
        with self._lock:
            account.bound_proxy_url = proxy_url
            account.use_global_proxy_pool = proxy_url is None

    def clear(self) -> None:
        """Clear all loaded SMTP accounts from the current session."""
        with self._lock:
            self._accounts.clear()
            self._rotation_index = 0

    def _replace_source(self, source: str, lines: list[str]) -> SMTPLoadResult:
        accounts: list[SMTPAccount] = []
        errors: list[str] = []
        invalid = 0

        for line in lines:
            try:
                accounts.append(parse_smtp_line(line, source=source))
            except SMTPParseError as exc:
                invalid += 1
                errors.append(f"{line}: {exc}")

        with self._lock:
            replaced = sum(1 for account in self._accounts if account.source == source)
            kept = [account for account in self._accounts if account.source != source]
            existing_keys = {account.key for account in kept}
            source_keys: set[str] = set()
            loaded = 0
            duplicates = 0

            for account in accounts:
                if account.key in existing_keys or account.key in source_keys:
                    duplicates += 1
                    continue
                kept.append(account)
                source_keys.add(account.key)
                loaded += 1

            self._accounts = kept
            self._rotation_index = 0

        return SMTPLoadResult(
            source=source,
            total_lines=len(lines),
            loaded=loaded,
            invalid=invalid,
            duplicates=duplicates,
            replaced=replaced,
            errors=tuple(errors[:20]),
        )

    def _open_connection(
        self,
        account: SMTPAccount,
        proxy_url: str | None = None,
    ) -> smtplib.SMTP:
        context = ssl.create_default_context()
        encryption = account.encryption

        if encryption == SMTPEncryption.SSL:
            return _ProxySMTPSSL(
                account.host,
                account.port,
                timeout=self.timeout,
                context=context,
                proxy_url=proxy_url,
            )

        server = _ProxySMTP(account.host, account.port, timeout=self.timeout, proxy_url=proxy_url)
        try:
            server.ehlo()
            if encryption == SMTPEncryption.STARTTLS:
                server.starttls(context=context)
                server.ehlo()
            elif encryption == SMTPEncryption.OPPORTUNISTIC_STARTTLS and server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
            return server
        except Exception:
            server.close()
            raise

    def _handle_smtp_auth_error(
        self,
        account: SMTPAccount,
        exc: smtplib.SMTPAuthenticationError,
    ) -> SMTPLoginResult:
        code = _smtp_code(exc)
        response = _smtp_response(exc)
        message = f"Ошибка авторизации {code or ''}: {response}".strip()
        if code is not None and 400 <= code <= 499:
            self._mark_account(account, SMTPStatus.UNKNOWN, error=message)
            temporary = True
        else:
            self._mark_account(account, SMTPStatus.DEAD, error=message)
            temporary = False

        _write_json_log(
            self.logs_dir,
            "smtp_auth_failed",
            "warning",
            email=account.email,
            host=account.endpoint,
            smtp_code=code,
            temporary=temporary,
        )
        return SMTPLoginResult(account.key, False, account.status, message, smtp_code=code, temporary=temporary)

    def _handle_smtp_response_error(
        self,
        account: SMTPAccount,
        exc: smtplib.SMTPResponseException,
    ) -> SMTPLoginResult:
        code = _smtp_code(exc)
        response = _smtp_response(exc)
        message = f"SMTP ответ {code or ''}: {response}".strip()
        if code is not None and 400 <= code <= 499:
            self._mark_account(account, SMTPStatus.UNKNOWN, error=message)
            temporary = True
        else:
            self._mark_account(account, SMTPStatus.DEAD, error=message)
            temporary = False
        _write_json_log(
            self.logs_dir,
            "smtp_response_failed",
            "warning",
            email=account.email,
            host=account.endpoint,
            smtp_code=code,
            temporary=temporary,
        )
        return SMTPLoginResult(account.key, False, account.status, message, smtp_code=code, temporary=temporary)

    def _fail_account(self, account: SMTPAccount, status: str, message: str) -> SMTPLoginResult:
        self._mark_account(account, status, error=message)
        _write_json_log(
            self.logs_dir,
            "smtp_check_failed",
            "warning",
            email=account.email,
            host=account.endpoint,
            status=status,
            error=message,
        )
        return SMTPLoginResult(account.key, False, status, message)

    def _mark_account(self, account: SMTPAccount, status: str, error: str = "") -> None:
        with self._lock:
            account.status = status
            account.last_error = error
            account.last_checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _summary(self, checked: int) -> SMTPCheckSummary:
        accounts = self.get_all()
        alive = sum(1 for account in accounts if account.status == SMTPStatus.ALIVE)
        dead = sum(1 for account in accounts if account.status == SMTPStatus.DEAD)
        unknown = sum(1 for account in accounts if account.status == SMTPStatus.UNKNOWN)
        return SMTPCheckSummary(checked=checked, alive=alive, dead=dead, unknown=unknown)


class _ProxySMTP(smtplib.SMTP):
    """SMTP client with optional HTTP CONNECT proxy support."""

    def __init__(self, *args: object, proxy_url: str | None = None, **kwargs: object) -> None:
        self._proxy_url = proxy_url
        super().__init__(*args, **kwargs)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        if self._proxy_url:
            return _open_http_proxy_tunnel(self._proxy_url, host, port, timeout)
        return super()._get_socket(host, port, timeout)


class _ProxySMTPSSL(smtplib.SMTP_SSL):
    """SMTP SSL client with optional HTTP CONNECT proxy support."""

    def __init__(self, *args: object, proxy_url: str | None = None, **kwargs: object) -> None:
        self._proxy_url = proxy_url
        super().__init__(*args, **kwargs)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        if not self._proxy_url:
            return super()._get_socket(host, port, timeout)

        raw_socket = _open_http_proxy_tunnel(self._proxy_url, host, port, timeout)
        try:
            return self.context.wrap_socket(raw_socket, server_hostname=host)
        except Exception:
            raw_socket.close()
            raise


def _open_http_proxy_tunnel(
    proxy_url: str,
    target_host: str,
    target_port: int,
    timeout: float,
) -> socket.socket:
    parsed = urlsplit(proxy_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SMTPProxyError("SMTP поддерживает только HTTP/HTTPS proxy tunnel")
    if not parsed.hostname:
        raise SMTPProxyError("В proxy URL не найден host")

    proxy_port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    sock = socket.create_connection((parsed.hostname, proxy_port), timeout=timeout)
    sock.settimeout(timeout)

    if parsed.scheme.lower() == "https":
        context = ssl.create_default_context()
        sock = context.wrap_socket(sock, server_hostname=parsed.hostname)

    auth_header = ""
    if parsed.username:
        user = unquote(parsed.username)
        password = unquote(parsed.password or "")
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        auth_header = f"Proxy-Authorization: Basic {token}\r\n"

    connect_request = (
        f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
        f"Host: {target_host}:{target_port}\r\n"
        "Proxy-Connection: Keep-Alive\r\n"
        "User-Agent: CHARLY-MAILER/1.0\r\n"
        f"{auth_header}"
        "\r\n"
    )

    try:
        sock.sendall(connect_request.encode("ascii"))
        response = _read_proxy_response(sock)
        status_line = response.splitlines()[0] if response else ""
        if " 200 " not in f" {status_line} ":
            raise SMTPProxyError(f"Proxy CONNECT failed: {status_line}")
        return sock
    except Exception:
        sock.close()
        raise


def _read_proxy_response(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        data = b"".join(chunks)
        if b"\r\n\r\n" in data:
            break
        if len(data) > 65536:
            raise SMTPProxyError("Proxy response is too large")
    return b"".join(chunks).decode("iso-8859-1", errors="replace")


def _smtp_code(exc: smtplib.SMTPResponseException) -> int | None:
    code = getattr(exc, "smtp_code", None)
    return code if isinstance(code, int) else None


def _smtp_response(exc: smtplib.SMTPResponseException) -> str:
    response = getattr(exc, "smtp_error", b"")
    if isinstance(response, bytes):
        return response.decode("utf-8", errors="replace").strip()
    return str(response).strip()


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

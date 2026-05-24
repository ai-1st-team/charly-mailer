"""Email composition, test send, and campaign sending orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
import json
from pathlib import Path
import random
import smtplib
import socket
import threading
import time
from typing import Literal

from core.app_state import AppState
from core.content import BodyRenderResult, ContentError, RecipientContext
from core.proxy_manager import ProxyRecord
from core.queue_manager import QueueError, QueueItem
from core.smtp_manager import SMTPAccount, SMTPStatus
from core.stats import get_stats_manager


TEST_LOG_PATH = Path("logs") / "test-log.json"


class SenderError(RuntimeError):
    """Raised when a message cannot be composed or sent."""


@dataclass(frozen=True)
class RenderedEmail:
    """Fully rendered email content."""

    recipient: str
    recipient_name: str
    sender_email: str
    sender_name: str
    subject: str
    body: str
    body_format: str
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    had_cc: bool = False
    had_bcc: bool = False
    control: bool = False


@dataclass(frozen=True)
class SendResult:
    """Result of sending one email."""

    ok: bool
    message: str
    smtp_used: str = ""
    proxy_used: str = ""
    duration_seconds: float = 0.0
    error_text: str = ""


@dataclass(frozen=True)
class CampaignSettings:
    """Runtime campaign send settings."""

    delay_seconds: float = 0.0
    emails_per_minute: float = 0.0
    jitter_seconds: float = 0.0

    def delay_for_next_email(self, rng: random.Random) -> float:
        """Return delay with speed limit and jitter."""
        delay = max(0.0, self.delay_seconds)
        if self.emails_per_minute > 0:
            delay = max(delay, 60.0 / self.emails_per_minute)
        if self.jitter_seconds > 0:
            delay += rng.uniform(-self.jitter_seconds, self.jitter_seconds)
        return max(0.0, delay)

    def as_dict(self) -> dict[str, float]:
        """Return JSON-ready settings."""
        return {
            "delay_seconds": self.delay_seconds,
            "emails_per_minute": self.emails_per_minute,
            "jitter_seconds": self.jitter_seconds,
        }


class EmailComposer:
    """Build rendered email content from current app state."""

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state

    def compose(self, recipient: QueueItem | dict[str, str] | str, smtp_account: SMTPAccount) -> RenderedEmail:
        """Compose one complete email without sending it."""
        recipient_context = _recipient_context(recipient)
        sender_name = self.app_state.choose_sender_name(smtp_account.email)
        cc_addresses, bcc_addresses = self.app_state.choose_cc_bcc()
        link_context = self.app_state.link_manager.create_context(self.app_state.unique_links_per_message)

        try:
            subject = self.app_state.subject_manager.render_random(
                recipient_context,
                sender_name,
                link_manager=self.app_state.link_manager,
                link_context=link_context,
            )
            body_result = self.app_state.body_manager.render_random(
                recipient_context,
                sender_name,
                link_manager=self.app_state.link_manager,
                link_context=link_context,
            )
        except ContentError as exc:
            raise SenderError(str(exc)) from exc

        return RenderedEmail(
            recipient=recipient_context.email,
            recipient_name=recipient_context.name,
            sender_email=smtp_account.email,
            sender_name=sender_name,
            subject=subject,
            body=body_result.body,
            body_format=body_result.body_format,
            cc=tuple(cc_addresses),
            bcc=tuple(bcc_addresses),
            had_cc=bool(cc_addresses),
            had_bcc=bool(bcc_addresses),
            control=_recipient_is_control(recipient),
        )

    def to_mime(self, rendered: RenderedEmail) -> EmailMessage:
        """Convert rendered email to a UTF-8 MIME message."""
        message = EmailMessage()
        if rendered.sender_name:
            message["From"] = formataddr((rendered.sender_name, rendered.sender_email))
        else:
            message["From"] = rendered.sender_email
        message["To"] = rendered.recipient
        if rendered.cc:
            message["Cc"] = ", ".join(rendered.cc)
        if rendered.bcc:
            message["Bcc"] = ", ".join(rendered.bcc)
        message["Subject"] = rendered.subject

        if rendered.body_format == "html":
            message.set_content(_html_to_plain_fallback(rendered.body))
            message.add_alternative(rendered.body, subtype="html")
        else:
            message.set_content(rendered.body)

        return message


class EmailDeliveryService:
    """Send test and campaign emails through app SMTP/proxy managers."""

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state
        self.composer = EmailComposer(app_state)
        self._random = random.SystemRandom()

    def preview_email(self, recipient_email: str = "preview@example.com") -> RenderedEmail:
        """Build one preview email using the first available SMTP account."""
        smtp_account = self._first_available_smtp()
        return self.composer.compose({"email": recipient_email, "name": "Preview"}, smtp_account)

    def send_test(self, recipient_email: str) -> SendResult:
        """Send one test email and write only test-log.json."""
        recipient_email = recipient_email.strip()
        if not recipient_email:
            raise SenderError("Укажи тестовый адрес")

        start = time.monotonic()
        smtp_account = self._first_live_smtp_with_check()
        proxy = self._random_live_proxy_with_check()

        try:
            rendered = self.composer.compose({"email": recipient_email}, smtp_account)
            mime_message = self.composer.to_mime(rendered)
            self.app_state.smtp_manager.send_message(
                smtp_account,
                mime_message,
                proxy_url=proxy.proxy_url if proxy else None,
            )
            self.app_state.smtp_manager.record_send_success(smtp_account)
        except Exception as exc:
            duration = time.monotonic() - start
            error_text = _error_text(exc)
            self._handle_smtp_exception(smtp_account, exc)
            result = SendResult(
                ok=False,
                message=f"ошибка: {error_text}",
                smtp_used=smtp_account.email,
                proxy_used=proxy.display_name if proxy else "",
                duration_seconds=duration,
                error_text=error_text,
            )
            append_test_log(result, recipient_email, "", control=False, had_cc=False, had_bcc=False)
            return result

        duration = time.monotonic() - start
        result = SendResult(
            ok=True,
            message=f"отправлено за {duration:.1f} сек через {smtp_account.email}",
            smtp_used=smtp_account.email,
            proxy_used=proxy.display_name if proxy else "",
            duration_seconds=duration,
        )
        append_test_log(
            result,
            recipient_email,
            rendered.subject,
            control=False,
            had_cc=rendered.had_cc,
            had_bcc=rendered.had_bcc,
        )
        return result

    def send_campaign_item(self, item: QueueItem) -> SendResult:
        """Compose and send one campaign queue item."""
        start = time.monotonic()
        smtp_account = self._next_live_smtp()
        proxy = self.app_state.proxy_manager.get_next_live_proxy()
        rendered: RenderedEmail | None = None

        try:
            rendered = self.composer.compose(item, smtp_account)
            mime_message = self.composer.to_mime(rendered)
            self.app_state.smtp_manager.send_message(
                smtp_account,
                mime_message,
                proxy_url=proxy.proxy_url if proxy else None,
            )
            self.app_state.smtp_manager.record_send_success(smtp_account)
            self.app_state.stats_manager.record_delivery(
                recipient=rendered.recipient,
                smtp_used=smtp_account.email,
                proxy_used=proxy.display_name if proxy else "",
                subject=rendered.subject,
                status="sent",
                control=rendered.control,
                had_cc=rendered.had_cc,
                had_bcc=rendered.had_bcc,
            )
            duration = time.monotonic() - start
            prefix = "[CONTROL] " if item.control else ""
            return SendResult(
                ok=True,
                message=f"{prefix}sent: {rendered.recipient}",
                smtp_used=smtp_account.email,
                proxy_used=proxy.display_name if proxy else "",
                duration_seconds=duration,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            error_text = _error_text(exc)
            self._handle_smtp_exception(smtp_account, exc)
            recipient = rendered.recipient if rendered else item.email
            subject = rendered.subject if rendered else ""
            self.app_state.stats_manager.record_delivery(
                recipient=recipient,
                smtp_used=smtp_account.email,
                proxy_used=proxy.display_name if proxy else "",
                subject=subject,
                status="error",
                error_text=error_text,
                control=item.control,
                had_cc=rendered.had_cc if rendered else False,
                had_bcc=rendered.had_bcc if rendered else False,
            )
            return SendResult(
                ok=False,
                message=f"{'[CONTROL] ' if item.control else ''}error: {recipient}: {error_text}",
                smtp_used=smtp_account.email,
                proxy_used=proxy.display_name if proxy else "",
                duration_seconds=duration,
                error_text=error_text,
            )

    def prepare_campaign_transports(self) -> None:
        """Check SMTP/proxy lists before campaign start."""
        if not self.app_state.smtp_manager.get_all():
            raise SenderError("Загрузите SMTP на вкладке Setup")
        live_smtp = self.app_state.smtp_manager.prepare_live_rotation()
        if not live_smtp:
            raise SenderError("Нет живых SMTP-аккаунтов")

        for account in self.app_state.smtp_manager.get_all():
            self.app_state.stats_manager.register_smtp(account.email, account.status)

        if self.app_state.proxy_manager.get_all():
            self.app_state.proxy_manager.prepare_live_rotation()
            for proxy in self.app_state.proxy_manager.get_all():
                self.app_state.stats_manager.register_proxy(proxy.display_name, proxy.status)

    def _first_available_smtp(self) -> SMTPAccount:
        accounts = self.app_state.smtp_manager.get_all()
        if not accounts:
            raise SenderError("Загрузите SMTP на вкладке Setup")
        return accounts[0]

    def _first_live_smtp_with_check(self) -> SMTPAccount:
        if not self.app_state.smtp_manager.get_all():
            raise SenderError("Загрузите SMTP на вкладке Setup")
        live = self.app_state.smtp_manager.get_live_accounts()
        if not live:
            self.app_state.smtp_manager.check_all()
            live = self.app_state.smtp_manager.get_live_accounts()
        if not live:
            raise SenderError("Нет живых SMTP-аккаунтов. Проверьте SMTP на вкладке Setup")
        return live[0]

    def _next_live_smtp(self) -> SMTPAccount:
        account = self.app_state.smtp_manager.get_next_live_account()
        if account is None:
            raise SenderError("Нет живых SMTP-аккаунтов")
        return account

    def _random_live_proxy_with_check(self) -> ProxyRecord | None:
        if not self.app_state.proxy_manager.get_all():
            return None
        live = self.app_state.proxy_manager.get_live_proxies()
        if not live:
            self.app_state.proxy_manager.check_all()
            live = self.app_state.proxy_manager.get_live_proxies()
        if not live:
            return None
        return self._random.choice(live)

    def _handle_smtp_exception(self, account: SMTPAccount, exc: Exception) -> None:
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            self.app_state.smtp_manager.record_auth_failure(account, _smtp_code(exc), _error_text(exc))
        elif isinstance(exc, smtplib.SMTPResponseException):
            self.app_state.smtp_manager.record_auth_failure(account, _smtp_code(exc), _error_text(exc))


class CampaignController:
    """Background campaign runner with pause and cooperative stop."""

    def __init__(self, app_state: AppState) -> None:
        self.app_state = app_state
        self.delivery = EmailDeliveryService(app_state)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.RLock()
        self._last_result = ""
        self._state: Literal["idle", "running", "paused", "completed", "stopped", "error"] = "idle"
        self._random = random.SystemRandom()

    @property
    def state(self) -> str:
        """Return current controller state."""
        with self._lock:
            return self._state

    @property
    def last_result(self) -> str:
        """Return last user-facing result."""
        with self._lock:
            return self._last_result

    def start_new(self, settings: CampaignSettings) -> None:
        """Build a fresh queue from app recipients and start sending."""
        recipients = self.app_state.get_recipients()
        if not recipients:
            raise SenderError("Загрузите базу на вкладке Campaign")

        snapshot = self.app_state.queue_manager.build_from_recipients(
            recipients,
            control_recipients=self.app_state.control_recipients,
            control_every=self.app_state.control_every,
            metadata={"settings": settings.as_dict(), "started_at": _utc_now()},
        )
        self.app_state.stats_manager.start_campaign(snapshot.total)
        self._start_thread(settings)

    def resume(self, settings: CampaignSettings) -> None:
        """Resume queue from data/queue-state.json."""
        snapshot = self.app_state.queue_manager.load_state()
        if snapshot.remaining <= 0:
            raise SenderError("Сохранённая очередь уже завершена")
        self.app_state.stats_manager.start_campaign(snapshot.total)
        self.app_state.stats_manager.set_queue_size(snapshot.remaining, snapshot.total)
        self._start_thread(settings)

    def stop(self) -> None:
        """Request graceful stop after the current email."""
        self._stop_event.set()
        with self._lock:
            self._state = "stopped"
            self._last_result = "Остановка запрошена. Текущее письмо будет дослано."
        self.app_state.stats_manager.stop_campaign()

    def toggle_pause(self) -> str:
        """Pause or continue campaign."""
        if self._pause_event.is_set():
            self._pause_event.clear()
            with self._lock:
                self._state = "running"
                self._last_result = "Рассылка продолжена."
            return "running"

        self._pause_event.set()
        with self._lock:
            self._state = "paused"
            self._last_result = "Пауза включена."
        self.app_state.stats_manager.pause_campaign()
        return "paused"

    def is_running(self) -> bool:
        """Return True while campaign thread is active."""
        return self._thread is not None and self._thread.is_alive()

    def _start_thread(self, settings: CampaignSettings) -> None:
        if self.is_running():
            raise SenderError("Рассылка уже запущена")
        self._stop_event.clear()
        self._pause_event.clear()
        with self._lock:
            self._state = "running"
            self._last_result = "Рассылка запускается..."
        self._thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self._thread.start()

    def _run(self, settings: CampaignSettings) -> None:
        try:
            self.delivery.prepare_campaign_transports()
            while not self._stop_event.is_set():
                self._wait_if_paused()
                if self._stop_event.is_set():
                    break

                item = self.app_state.queue_manager.next_item()
                if item is None:
                    self.app_state.stats_manager.complete_campaign()
                    self.app_state.queue_manager.clear_state()
                    with self._lock:
                        self._state = "completed"
                        self._last_result = "Рассылка завершена."
                    return

                result = self.delivery.send_campaign_item(item)
                self.app_state.queue_manager.mark_current_processed()
                snapshot = self.app_state.queue_manager.snapshot()
                self.app_state.stats_manager.set_queue_size(snapshot.remaining, snapshot.total)
                with self._lock:
                    self._last_result = result.message

                delay = settings.delay_for_next_email(self._random)
                if not self._sleep_interruptible(delay):
                    break

            self.app_state.queue_manager.save_state()
            with self._lock:
                if self._state != "error":
                    self._state = "stopped"
                    self._last_result = "Рассылка остановлена. Прогресс сохранён."
            self.app_state.stats_manager.stop_campaign()
        except Exception as exc:
            self.app_state.queue_manager.save_state()
            with self._lock:
                self._state = "error"
                self._last_result = f"Ошибка рассылки: {_error_text(exc)}"
            self.app_state.stats_manager.stop_campaign()

    def _wait_if_paused(self) -> None:
        while self._pause_event.is_set() and not self._stop_event.is_set():
            time.sleep(0.2)

    def _sleep_interruptible(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            self._wait_if_paused()
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        return True


def append_test_log(
    result: SendResult,
    recipient: str,
    subject: str,
    control: bool,
    had_cc: bool = False,
    had_bcc: bool = False,
) -> None:
    """Append one test send result to logs/test-log.json."""
    TEST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": _utc_now(),
        "recipient": recipient,
        "smtp_used": result.smtp_used,
        "proxy_used": result.proxy_used,
        "subject": subject,
        "status": "sent" if result.ok else "error",
        "duration_seconds": round(result.duration_seconds, 3),
        "control": control,
        "had_cc": had_cc,
        "had_bcc": had_bcc,
    }
    if not result.ok:
        record["error_text"] = result.error_text

    with _TEST_LOG_LOCK:
        records: list[dict[str, object]]
        if TEST_LOG_PATH.exists() and TEST_LOG_PATH.stat().st_size > 0:
            try:
                data = json.loads(TEST_LOG_PATH.read_text(encoding="utf-8"))
                records = data if isinstance(data, list) else []
            except json.JSONDecodeError:
                records = []
        else:
            records = []
        records.append(record)
        TEST_LOG_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _recipient_context(recipient: QueueItem | dict[str, str] | str) -> RecipientContext:
    if isinstance(recipient, QueueItem):
        return RecipientContext(email=recipient.email, name=recipient.name)
    if isinstance(recipient, str):
        return RecipientContext(email=recipient.strip(), name="")
    return RecipientContext(
        email=str(recipient.get("email", "")).strip(),
        name=str(recipient.get("name", "")).strip(),
    )


def _recipient_is_control(recipient: QueueItem | dict[str, str] | str) -> bool:
    return isinstance(recipient, QueueItem) and recipient.control


def _html_to_plain_fallback(html: str) -> str:
    return "HTML version is available. If you see this text, your email client did not render HTML."


def _smtp_code(exc: smtplib.SMTPResponseException) -> int | None:
    code = getattr(exc, "smtp_code", None)
    return code if isinstance(code, int) else None


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPResponseException):
        code = _smtp_code(exc)
        smtp_error = getattr(exc, "smtp_error", b"")
        if isinstance(smtp_error, bytes):
            message = smtp_error.decode("utf-8", errors="replace").strip()
        else:
            message = str(smtp_error).strip()
        return f"SMTP {code}: {message}" if code else message
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "таймаут подключения или отправки"
    message = str(exc).replace("\n", " ").strip()
    return message[:500] if message else exc.__class__.__name__


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_TEST_LOG_LOCK = threading.Lock()

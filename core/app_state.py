"""Shared in-process application state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import random
import threading
from typing import Any

from core.content import BodyManager, LinkManager, SenderNameLoadResult, SenderNameManager, SubjectManager
from core.proxy_manager import ProxyManager
from core.queue_manager import QueueManager
from core.smtp_manager import SMTPManager
from core.stats import StatsManager, get_stats_manager


RecipientRow = dict[str, Any]


@dataclass
class AppState:
    """Shared managers and campaign data used by GUI tabs."""

    proxy_manager: ProxyManager = field(default_factory=ProxyManager)
    smtp_manager: SMTPManager = field(default_factory=SMTPManager)
    subject_manager: SubjectManager = field(default_factory=SubjectManager)
    body_manager: BodyManager = field(default_factory=BodyManager)
    link_manager: LinkManager = field(default_factory=LinkManager)
    sender_name_manager: SenderNameManager = field(default_factory=SenderNameManager)
    queue_manager: QueueManager = field(default_factory=QueueManager)
    stats_manager: StatsManager = field(default_factory=get_stats_manager)
    recipients: list[RecipientRow] = field(default_factory=list)
    recipients_source: str = ""
    control_recipients: list[RecipientRow] = field(default_factory=list)
    control_every: int = 0
    cc_addresses: list[str] = field(default_factory=list)
    bcc_addresses: list[str] = field(default_factory=list)
    cc_percent: float = 0.0
    bcc_percent: float = 0.0
    unique_links_per_message: bool = False
    from_email_only: bool = False
    delay_seconds: float = 0.0
    emails_per_minute: float = 0.0
    jitter_seconds: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._random = random.SystemRandom()

    def set_recipients(self, recipients: list[RecipientRow], source: str | Path = "") -> None:
        """Replace campaign recipients."""
        with self._lock:
            self.recipients = list(recipients)
            if source:
                self.recipients_source = str(Path(source).resolve())

    def clear_recipients(self) -> None:
        """Clear loaded campaign recipients."""
        with self._lock:
            self.recipients = []
            self.recipients_source = ""

    def get_recipients(self) -> list[RecipientRow]:
        """Return a recipients snapshot."""
        with self._lock:
            return list(self.recipients)

    def set_sender_names(self, names: list[str]) -> None:
        """Replace sender display names."""
        with self._lock:
            self.sender_name_manager.set_names(names)

    def load_sender_names_from_file(self, path: str | Path) -> SenderNameLoadResult:
        """Load sender display names from senders.txt."""
        with self._lock:
            return self.sender_name_manager.load_from_file(path)

    def choose_sender_name(self, fallback_email: str = "") -> str:
        """Return a random sender name or empty string for email-only From."""
        with self._lock:
            if self.from_email_only:
                return ""
            return self.sender_name_manager.choose_random(default="")

    def set_cc_bcc_settings(
        self,
        cc_addresses: list[str],
        bcc_addresses: list[str],
        cc_percent: float,
        bcc_percent: float,
    ) -> None:
        """Replace campaign CC/BCC settings."""
        with self._lock:
            self.cc_addresses = list(cc_addresses)
            self.bcc_addresses = list(bcc_addresses)
            self.cc_percent = _clamp_percent(cc_percent)
            self.bcc_percent = _clamp_percent(bcc_percent)

    def choose_cc_bcc(self) -> tuple[list[str], list[str]]:
        """Return CC/BCC addresses for one message according to configured percentages."""
        with self._lock:
            cc_addresses = list(self.cc_addresses)
            bcc_addresses = list(self.bcc_addresses)
            cc_percent = self.cc_percent
            bcc_percent = self.bcc_percent

            include_cc = bool(cc_addresses) and self._random.random() < cc_percent / 100.0
            include_bcc = bool(bcc_addresses) and self._random.random() < bcc_percent / 100.0

        return (cc_addresses if include_cc else [], bcc_addresses if include_bcc else [])

    def set_send_settings(self, delay_seconds: float, emails_per_minute: float, jitter_seconds: float) -> None:
        """Store send speed controls for presets."""
        with self._lock:
            self.delay_seconds = max(0.0, delay_seconds)
            self.emails_per_minute = max(0.0, emails_per_minute)
            self.jitter_seconds = max(0.0, jitter_seconds)


def _clamp_percent(value: float) -> float:
    return min(100.0, max(0.0, float(value)))


def get_app_state() -> AppState:
    """Return the process-wide app state."""
    return _APP_STATE


_APP_STATE = AppState()

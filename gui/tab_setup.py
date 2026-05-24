"""Setup tab: proxy and SMTP account configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import queue
import threading
from tkinter import filedialog

import customtkinter as ctk

from core.app_state import get_app_state
from core.proxy_manager import ProxyCheckResult, ProxyLoadResult, ProxyManager, ProxyStatus
from core.smtp_manager import SMTPAccount, SMTPCheckSummary, SMTPLoginResult, SMTPManager, SMTPLoadResult, SMTPStatus


STATUS_LABELS = {
    ProxyStatus.UNCHECKED: "не проверен",
    ProxyStatus.CHECKING: "проверка",
    ProxyStatus.ALIVE: "живой",
    ProxyStatus.DEAD: "мёртвый",
}

SMTP_STATUS_LABELS = {
    SMTPStatus.UNKNOWN: "неизвестный",
    SMTPStatus.CHECKING: "проверка",
    SMTPStatus.ALIVE: "живой",
    SMTPStatus.DEAD: "мёртвый",
}


def build_setup_tab(parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
    """Build the Setup tab."""
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    content = ctk.CTkFrame(parent, fg_color="transparent")
    content.grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=16,
        pady=16,
    )
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=1)
    content.grid_columnconfigure(1, weight=1)

    ProxySetupPanel(content, colors).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    SMTPSetupPanel(content, colors).grid(row=0, column=1, sticky="nsew", padx=(8, 0))


class ProxySetupPanel(ctk.CTkFrame):
    """Proxy controls for loading and validation."""

    def __init__(self, parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
        super().__init__(parent, fg_color=colors["background"])
        self.colors = colors
        self.app_state = get_app_state()
        self.proxy_manager = self.app_state.proxy_manager
        self.stats_manager = self.app_state.stats_manager
        self._queue: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self._busy = False
        self._last_url = ""
        self._auto_refresh_after_id: str | None = None

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_file_controls()
        self._build_url_controls()
        self._build_proxy_list()
        self._build_footer()
        self._refresh_proxy_list()
        self.winfo_toplevel().bind("<<PresetLoaded>>", self._on_preset_loaded, add="+")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Прокси",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.summary_label = ctk.CTkLabel(
            header,
            text="Загружено: 0 | Живых: 0 | Мёртвых: 0",
            text_color=self.colors["muted"],
        )
        self.summary_label.grid(row=0, column=1, sticky="e")

    def _build_file_controls(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        row.grid_columnconfigure(1, weight=1)

        self.load_file_button = ctk.CTkButton(
            row,
            text="Загрузить из файла",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_proxy_file,
        )
        self.load_file_button.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            row,
            text="Форматы: URL или host:port:user:pass",
            text_color=self.colors["muted"],
            wraplength=260,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

    def _build_url_controls(self) -> None:
        wrapper = ctk.CTkFrame(self, fg_color="transparent")
        wrapper.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        wrapper.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            wrapper,
            placeholder_text="URL прокси-листа",
            fg_color=self.colors["surface"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.load_url_button = ctk.CTkButton(
            wrapper,
            text="Загрузить по URL",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._load_from_url,
        )
        self.load_url_button.grid(row=0, column=1, sticky="e")

        self.auto_refresh_switch = ctk.CTkSwitch(
            wrapper,
            text="Автообновление",
            text_color=self.colors["text"],
            progress_color=self.colors["accent"],
            command=self._on_auto_refresh_changed,
        )
        self.auto_refresh_switch.grid(row=1, column=0, sticky="w", pady=(8, 0))

        interval_frame = ctk.CTkFrame(wrapper, fg_color="transparent")
        interval_frame.grid(row=1, column=1, sticky="e", pady=(8, 0))

        ctk.CTkLabel(interval_frame, text="мин:", text_color=self.colors["muted"]).grid(
            row=0,
            column=0,
            padx=(0, 6),
        )
        self.refresh_interval_entry = ctk.CTkEntry(
            interval_frame,
            width=70,
            fg_color=self.colors["surface"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.refresh_interval_entry.grid(row=0, column=1)
        self.refresh_interval_entry.insert(0, "10")

    def _build_proxy_list(self) -> None:
        list_frame = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        list_frame.grid(row=3, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(list_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        header.grid_columnconfigure(0, weight=4)
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=2)
        header.grid_columnconfigure(3, weight=3)

        self._header_label(header, "Прокси", 0)
        self._header_label(header, "Статус", 1)
        self._header_label(header, "IP", 2)
        self._header_label(header, "Комментарий", 3)

        self.proxy_rows = ctk.CTkScrollableFrame(list_frame, fg_color="transparent")
        self.proxy_rows.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.proxy_rows.grid_columnconfigure(0, weight=4)
        self.proxy_rows.grid_columnconfigure(1, weight=1)
        self.proxy_rows.grid_columnconfigure(2, weight=2)
        self.proxy_rows.grid_columnconfigure(3, weight=3)

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            footer,
            text="Готово.",
            text_color=self.colors["muted"],
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self.check_all_button = ctk.CTkButton(
            footer,
            text="Проверить все",
            fg_color=self.colors["warning"],
            hover_color="#f59e0b",
            text_color="#050505",
            command=self._check_all,
        )
        self.check_all_button.grid(row=0, column=1, sticky="e")

    def _header_label(self, parent: ctk.CTkFrame, text: str, column: int) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=self.colors["muted"],
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=column, sticky="ew", padx=(0, 8))

    def _choose_proxy_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Выберите proxies.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not file_path:
            return

        self._run_async(
            "file_load",
            lambda: self.proxy_manager.load_from_file(Path(file_path)),
            self._on_load_success,
        )

    def _load_from_url(self, periodic: bool = False) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("Укажи URL прокси-листа.", self.colors["warning"])
            return

        self._last_url = url
        action = "url_auto_load" if periodic else "url_load"
        self._run_async(action, lambda: self.proxy_manager.load_from_url(url), self._on_load_success)

    def _check_all(self) -> None:
        if not self.proxy_manager.get_all():
            self._set_status("Список прокси пуст.", self.colors["warning"])
            return

        self._refresh_proxy_list(checking=True)
        self._run_async("check_all", self.proxy_manager.check_all, self._on_check_success)

    def _run_async(
        self,
        action: str,
        task: Callable[[], object],
        on_success: Callable[[str, object], None],
    ) -> None:
        if self._busy:
            self._set_status("Дождись завершения текущей операции.", self.colors["warning"])
            return

        self._set_busy(True)
        self._set_status("Выполняю...", self.colors["muted"])

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                self._queue.put(("error", action, exc))
            else:
                self._queue.put(("success", action, (on_success, result)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            status, action, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return

        self._set_busy(False)
        if status == "error":
            self._set_status(str(payload), self.colors["error"])
            self._refresh_proxy_list()
        else:
            on_success, result = payload
            on_success(action, result)

        if action in {"url_load", "url_auto_load"}:
            self._schedule_auto_refresh(show_status=True)

    def _on_load_success(self, action: str, result: ProxyLoadResult) -> None:
        self._sync_proxy_stats()
        self._refresh_proxy_list()
        message = (
            f"Загружено: {result.loaded}. "
            f"Заменено старых: {result.replaced}. "
            f"Дубликаты: {result.duplicates}. "
            f"Ошибки: {result.invalid}."
        )
        color = self.colors["warning"] if result.invalid else self.colors["accent"]
        if result.errors:
            message += f" Первая ошибка: {result.errors[0]}"
        if action == "url_auto_load":
            message = f"Автообновление: {message}"
        self._set_status(message, color)

    def _on_check_success(self, _action: str, result: ProxyCheckResult) -> None:
        self._sync_proxy_stats()
        self._refresh_proxy_list()
        if result.checked == 0:
            self._set_status("Прокси для проверки не найдены.", self.colors["warning"])
            return

        color = self.colors["accent"] if result.alive else self.colors["error"]
        self._set_status(
            f"Проверено: {result.checked}. Живых: {result.alive}. Мёртвых: {result.dead}.",
            color,
        )

    def _refresh_proxy_list(self, checking: bool = False) -> None:
        for child in self.proxy_rows.winfo_children():
            child.destroy()

        proxies = self.proxy_manager.get_all()
        if not proxies:
            ctk.CTkLabel(
                self.proxy_rows,
                text="// TODO: список прокси пуст",
                text_color=self.colors["muted"],
            ).grid(row=0, column=0, columnspan=4, sticky="nsew", pady=40)
        else:
            for row_index, proxy in enumerate(proxies):
                status = ProxyStatus.CHECKING if checking else proxy.status
                self._proxy_row(row_index, proxy.display_name, status, proxy.external_ip, proxy.last_error)

        total = len(proxies)
        alive = sum(1 for proxy in proxies if proxy.status == ProxyStatus.ALIVE)
        dead = sum(1 for proxy in proxies if proxy.status == ProxyStatus.DEAD)
        self.summary_label.configure(text=f"Загружено: {total} | Живых: {alive} | Мёртвых: {dead}")

    def _proxy_row(
        self,
        row: int,
        display_name: str,
        status: str,
        external_ip: str,
        last_error: str,
    ) -> None:
        status_color = self._status_color(status)
        values = (
            (display_name, self.colors["text"]),
            (STATUS_LABELS.get(status, status), status_color),
            (external_ip or "-", self.colors["muted"]),
            (last_error or "-", self.colors["muted"]),
        )

        for column, (text, color) in enumerate(values):
            ctk.CTkLabel(
                self.proxy_rows,
                text=text,
                text_color=color,
                anchor="w",
                justify="left",
                wraplength=280 if column in {0, 3} else 120,
            ).grid(row=row, column=column, sticky="ew", padx=(0, 8), pady=3)

    def _status_color(self, status: str) -> str:
        if status == ProxyStatus.ALIVE:
            return self.colors["accent"]
        if status == ProxyStatus.DEAD:
            return self.colors["error"]
        if status == ProxyStatus.CHECKING:
            return self.colors["warning"]
        return self.colors["muted"]

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, text_color=color)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.load_file_button.configure(state=state)
        self.load_url_button.configure(state=state)
        self.check_all_button.configure(state=state)

    def _on_auto_refresh_changed(self) -> None:
        if self.auto_refresh_switch.get():
            if not self.url_entry.get().strip() and not self._last_url:
                self.auto_refresh_switch.deselect()
                self._set_status("Сначала укажи и загрузи URL прокси-листа.", self.colors["warning"])
                return
            self._schedule_auto_refresh()
        else:
            self._cancel_auto_refresh()
            self._set_status("Автообновление отключено.", self.colors["muted"])

    def _schedule_auto_refresh(self, show_status: bool = False) -> None:
        self._cancel_auto_refresh()
        if not self.auto_refresh_switch.get():
            return

        interval = self._get_refresh_interval_minutes()
        if interval is None:
            self.auto_refresh_switch.deselect()
            self._set_status("Интервал автообновления должен быть от 1 до 1440 минут.", self.colors["error"])
            return

        self._auto_refresh_after_id = self.after(interval * 60 * 1000, self._auto_refresh_tick)
        if show_status:
            self._set_status(f"Автообновление включено: раз в {interval} мин.", self.colors["muted"])

    def _cancel_auto_refresh(self) -> None:
        if self._auto_refresh_after_id is not None:
            self.after_cancel(self._auto_refresh_after_id)
            self._auto_refresh_after_id = None

    def _auto_refresh_tick(self) -> None:
        self._auto_refresh_after_id = None
        if not self.auto_refresh_switch.get():
            return
        if self._busy:
            self._schedule_auto_refresh()
            return

        if self._last_url:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, self._last_url)
        self._load_from_url(periodic=True)

    def _get_refresh_interval_minutes(self) -> int | None:
        raw_value = self.refresh_interval_entry.get().strip()
        try:
            interval = int(raw_value)
        except ValueError:
            return None

        if interval < 1 or interval > 1440:
            return None
        return interval

    def _sync_proxy_stats(self) -> None:
        for proxy in self.proxy_manager.get_all():
            self.stats_manager.register_proxy(proxy.display_name, proxy.status)

    def _on_preset_loaded(self, _event: object | None = None) -> None:
        self._sync_proxy_stats()
        self._refresh_proxy_list()
        self._set_status("Пресет загружен. Список прокси обновлён.", self.colors["accent"])


class SMTPSetupPanel(ctk.CTkFrame):
    """SMTP controls for loading, validation, and session status."""

    def __init__(self, parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
        super().__init__(parent, fg_color=colors["background"])
        self.colors = colors
        self.app_state = get_app_state()
        self.smtp_manager = self.app_state.smtp_manager
        self.stats_manager = self.app_state.stats_manager
        self._queue: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self._busy = False
        self._checking_key: str | None = None

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_controls()
        self._build_account_list()
        self._build_footer()
        self._refresh_accounts()
        self.winfo_toplevel().bind("<<PresetLoaded>>", self._on_preset_loaded, add="+")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="SMTP",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.summary_label = ctk.CTkLabel(
            header,
            text="Аккаунтов: 0 | Живых: 0 | Мёртвых: 0",
            text_color=self.colors["muted"],
        )
        self.summary_label.grid(row=0, column=1, sticky="e")

    def _build_controls(self) -> None:
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        controls.grid_columnconfigure(0, weight=1)

        self.load_button = ctk.CTkButton(
            controls,
            text="Загрузить smtps.txt",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_smtp_file,
        )
        self.load_button.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.check_all_button = ctk.CTkButton(
            controls,
            text="Проверить все",
            fg_color=self.colors["warning"],
            hover_color="#f59e0b",
            text_color="#050505",
            command=self._check_all,
        )
        self.check_all_button.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            controls,
            text="Формат: host:port:email:password",
            text_color=self.colors["muted"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_account_list(self) -> None:
        self.account_list = ctk.CTkScrollableFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        self.account_list.grid(row=2, column=0, sticky="nsew")
        self.account_list.grid_columnconfigure(0, weight=1)

    def _build_footer(self) -> None:
        self.status_label = ctk.CTkLabel(
            self,
            text="Готово.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
            wraplength=390,
        )
        self.status_label.grid(row=3, column=0, sticky="ew", pady=(12, 0))

    def _choose_smtp_file(self) -> None:
        initial_dir = Path("data") if Path("data").exists() else Path(".")
        file_path = filedialog.askopenfilename(
            title="Выберите smtps.txt",
            initialdir=str(initial_dir),
            initialfile="smtps.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not file_path:
            return

        self._run_async(
            "smtp_load",
            lambda: self.smtp_manager.load_from_file(Path(file_path)),
            self._on_load_success,
        )

    def _check_all(self) -> None:
        if not self.smtp_manager.get_all():
            self._set_status("Список SMTP пуст.", self.colors["warning"])
            return

        self._checking_key = None
        self._run_async("smtp_check_all", self.smtp_manager.check_all, self._on_check_all_success)
        self._refresh_accounts(checking_all=True)

    def _check_one(self, account_key: str) -> None:
        self._checking_key = account_key
        self._run_async(
            "smtp_check_one",
            lambda: self.smtp_manager.check_account_by_key(account_key),
            self._on_check_one_success,
        )
        self._refresh_accounts(checking_key=account_key)

    def _run_async(
        self,
        action: str,
        task: Callable[[], object],
        on_success: Callable[[str, object], None],
    ) -> None:
        if self._busy:
            self._set_status("Дождись завершения текущей операции.", self.colors["warning"])
            return

        self._set_busy(True)
        self._set_status("Выполняю...", self.colors["muted"])

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                self._queue.put(("error", action, exc))
            else:
                self._queue.put(("success", action, (on_success, result)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            status, action, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return

        self._checking_key = None
        self._set_busy(False)
        if status == "error":
            self._set_status(str(payload), self.colors["error"])
            self._refresh_accounts()
            return

        on_success, result = payload
        on_success(action, result)

    def _on_load_success(self, _action: str, result: object) -> None:
        load_result = _require_type(result, SMTPLoadResult)
        self._sync_smtp_stats()
        self._refresh_accounts()
        message = (
            f"Загружено: {load_result.loaded}. "
            f"Заменено старых: {load_result.replaced}. "
            f"Дубликаты: {load_result.duplicates}. "
            f"Ошибки: {load_result.invalid}."
        )
        color = self.colors["warning"] if load_result.invalid else self.colors["accent"]
        if load_result.errors:
            message += f" Первая ошибка: {load_result.errors[0]}"
        self._set_status(message, color)

    def _on_check_all_success(self, _action: str, result: object) -> None:
        summary = _require_type(result, SMTPCheckSummary)
        self._sync_smtp_stats()
        self._refresh_accounts()
        if summary.checked == 0:
            self._set_status("SMTP-аккаунты для проверки не найдены.", self.colors["warning"])
            return

        color = self.colors["accent"] if summary.alive else self.colors["error"]
        self._set_status(
            (
                f"Проверено: {summary.checked}. "
                f"Живых: {summary.alive}. "
                f"Мёртвых: {summary.dead}. "
                f"Неизвестных: {summary.unknown}."
            ),
            color,
        )

    def _on_check_one_success(self, _action: str, result: object) -> None:
        login_result = _require_type(result, SMTPLoginResult)
        self._sync_smtp_stats()
        self._refresh_accounts()
        color = self._status_color(login_result.status)
        self._set_status(login_result.message, color)

    def _refresh_accounts(
        self,
        checking_key: str | None = None,
        checking_all: bool = False,
    ) -> None:
        for child in self.account_list.winfo_children():
            child.destroy()

        accounts = self.smtp_manager.get_all()
        if not accounts:
            ctk.CTkLabel(
                self.account_list,
                text="// TODO: список SMTP пуст",
                text_color=self.colors["muted"],
            ).grid(row=0, column=0, sticky="nsew", pady=40)
        else:
            for row_index, account in enumerate(accounts):
                status = account.status
                if checking_all or account.key == checking_key:
                    status = SMTPStatus.CHECKING
                self._account_card(row_index, account, status)

        total = len(accounts)
        alive = sum(1 for account in accounts if account.status == SMTPStatus.ALIVE)
        dead = sum(1 for account in accounts if account.status == SMTPStatus.DEAD)
        self.summary_label.configure(text=f"Аккаунтов: {total} | Живых: {alive} | Мёртвых: {dead}")

    def _account_card(self, row: int, account: SMTPAccount, status: str) -> None:
        card = ctk.CTkFrame(
            self.account_list,
            fg_color=self.colors["background"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        card.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 0))
        card.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text=account.email,
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(
            top,
            text="Проверить",
            width=100,
            fg_color=self.colors["surface_hover"],
            hover_color=self.colors["accent_hover"],
            text_color=self.colors["text"],
            state="disabled" if self._busy else "normal",
            command=lambda key=account.key: self._check_one(key),
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        meta = ctk.CTkFrame(card, fg_color="transparent")
        meta.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        meta.grid_columnconfigure(0, weight=1)
        meta.grid_columnconfigure(1, weight=1)

        self._card_label(meta, f"Host: {account.endpoint}", 0, 0, self.colors["muted"])
        self._card_label(meta, f"Статус: {SMTP_STATUS_LABELS.get(status, status)}", 0, 1, self._status_color(status))
        self._card_label(meta, f"Отправлено: {account.sent_count}", 1, 0, self.colors["muted"])
        self._card_label(meta, f"Шифрование: {account.encryption}", 1, 1, self.colors["muted"])
        self._card_label(meta, f"Прокси: {account.proxy_mode_label}", 2, 0, self.colors["muted"])

        if account.last_error:
            self._card_label(meta, account.last_error, 3, 0, self.colors["error"], columnspan=2)

    def _card_label(
        self,
        parent: ctk.CTkFrame,
        text: str,
        row: int,
        column: int,
        color: str,
        columnspan: int = 1,
    ) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=color,
            anchor="w",
            justify="left",
            wraplength=180 if columnspan == 1 else 360,
        ).grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=(0, 8), pady=2)

    def _status_color(self, status: str) -> str:
        if status == SMTPStatus.ALIVE:
            return self.colors["accent"]
        if status == SMTPStatus.DEAD:
            return self.colors["error"]
        if status == SMTPStatus.CHECKING:
            return self.colors["warning"]
        return self.colors["muted"]

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, text_color=color)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.load_button.configure(state=state)
        self.check_all_button.configure(state=state)

    def _sync_smtp_stats(self) -> None:
        for account in self.smtp_manager.get_all():
            self.stats_manager.register_smtp(account.email, account.status)

    def _on_preset_loaded(self, _event: object | None = None) -> None:
        self._sync_smtp_stats()
        self._refresh_accounts()
        self._set_status("Пресет загружен. Список SMTP обновлён.", self.colors["accent"])


def _require_type(value: object, expected_type: type[object]) -> object:
    if not isinstance(value, expected_type):
        raise TypeError(f"Unexpected result type: {type(value).__name__}")
    return value

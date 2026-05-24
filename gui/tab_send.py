"""Send tab: test email and bulk campaign controls."""

from __future__ import annotations

from collections.abc import Mapping
import queue
import threading

import customtkinter as ctk

from core.app_state import get_app_state
from core.sender import CampaignController, CampaignSettings, EmailDeliveryService, RenderedEmail, SendResult, SenderError


def build_send_tab(parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
    """Build the Send tab."""
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    SendPanel(parent, colors).grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=20,
        pady=20,
    )


class SendPanel(ctk.CTkFrame):
    """Test send and campaign control panel."""

    def __init__(self, parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
        super().__init__(parent, fg_color=colors["background"])
        self.colors = colors
        self.app_state = get_app_state()
        self.delivery = EmailDeliveryService(self.app_state)
        self.controller = CampaignController(self.app_state)
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._test_running = False

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_test_block()
        self._build_campaign_controls()
        self._build_preview_area()
        self._build_resume_block()
        self._refresh_buttons()
        self.after(300, self._poll_queue)
        self.after(1000, self._refresh_runtime_state)
        self.winfo_toplevel().bind("<<PresetLoaded>>", self._on_preset_loaded, add="+")

    def _build_test_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        block.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            block,
            text="Тестовая отправка",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=14, pady=(12, 8))

        ctk.CTkLabel(
            block,
            text="Тестовый адрес",
            text_color=self.colors["muted"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=(0, 14))

        self.test_email_entry = ctk.CTkEntry(
            block,
            placeholder_text="test@example.com",
            fg_color=self.colors["background"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.test_email_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 14))

        self.test_button = ctk.CTkButton(
            block,
            text="ТЕСТ",
            height=42,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._run_test_send,
        )
        self.test_button.grid(row=1, column=2, sticky="e", padx=(0, 14), pady=(0, 14))

        self.test_result_label = ctk.CTkLabel(
            block,
            text="Тестовое письмо пишется в logs/test-log.json",
            text_color=self.colors["muted"],
            anchor="w",
        )
        self.test_result_label.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 12))

    def _build_campaign_controls(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        block.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(block, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 10))
        top.grid_columnconfigure(4, weight=1)

        self.preview_button = ctk.CTkButton(
            top,
            text="👁 Превью письма",
            fg_color=self.colors["surface_hover"],
            hover_color=self.colors["accent_hover"],
            text_color=self.colors["text"],
            command=self._show_preview,
        )
        self.preview_button.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.start_button = ctk.CTkButton(
            top,
            text="▶ СТАРТ РАССЫЛКИ",
            height=44,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_campaign,
        )
        self.start_button.grid(row=0, column=1, sticky="w", padx=(0, 8))

        self.stop_button = ctk.CTkButton(
            top,
            text="■ СТОП",
            height=44,
            fg_color=self.colors["error"],
            hover_color="#dc2626",
            text_color="#ffffff",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._stop_campaign,
        )
        self.stop_button.grid(row=0, column=2, sticky="w", padx=(0, 8))

        self.pause_button = ctk.CTkButton(
            top,
            text="⏸ ПАУЗА / ▶ ПРОДОЛЖИТЬ",
            height=44,
            fg_color=self.colors["warning"],
            hover_color="#f59e0b",
            text_color="#050505",
            command=self._toggle_pause,
        )
        self.pause_button.grid(row=0, column=3, sticky="w", padx=(0, 8))

        fields = ctk.CTkFrame(block, fg_color="transparent")
        fields.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        for column in range(6):
            fields.grid_columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        self.delay_entry = self._labeled_entry(fields, "Задержка между письмами (сек)", _format_number(self.app_state.delay_seconds), 0)
        self.rate_entry = self._labeled_entry(fields, "Писем в минуту", _format_number(self.app_state.emails_per_minute), 2)
        self.jitter_entry = self._labeled_entry(fields, "Случайный разброс задержки ±сек", _format_number(self.app_state.jitter_seconds), 4)

        self.campaign_status_label = ctk.CTkLabel(
            block,
            text="СТАРТ станет доступен после загрузки базы на вкладке Campaign и SMTP/контента.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
        )
        self.campaign_status_label.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))

    def _labeled_entry(self, parent: ctk.CTkFrame, label: str, default: str, column: int) -> ctk.CTkEntry:
        ctk.CTkLabel(
            parent,
            text=label,
            text_color=self.colors["muted"],
            anchor="w",
        ).grid(row=0, column=column, sticky="w", padx=(0, 6))
        entry = ctk.CTkEntry(
            parent,
            width=90,
            fg_color=self.colors["background"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        entry.grid(row=0, column=column + 1, sticky="ew", padx=(0, 14))
        entry.insert(0, default)
        entry.bind("<KeyRelease>", self._sync_send_settings_to_state)
        return entry

    def _build_preview_area(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=2, column=0, sticky="nsew")
        block.grid_rowconfigure(1, weight=1)
        block.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            block,
            text="Последнее превью / результат",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))

        self.preview_textbox = ctk.CTkTextbox(
            block,
            fg_color=self.colors["background"],
            border_width=1,
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
            wrap="word",
        )
        self.preview_textbox.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self._set_preview_text("// TODO: нажмите «Превью письма» после загрузки контента.")

    def _build_resume_block(self) -> None:
        self.resume_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.resume_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.resume_frame.grid_columnconfigure(0, weight=1)

        self.resume_label = ctk.CTkLabel(
            self.resume_frame,
            text="",
            text_color=self.colors["warning"],
            anchor="w",
        )
        self.resume_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.resume_button = ctk.CTkButton(
            self.resume_frame,
            text="Продолжить",
            width=120,
            fg_color=self.colors["warning"],
            hover_color="#f59e0b",
            text_color="#050505",
            command=self._resume_campaign,
        )
        self.resume_button.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self.reset_queue_button = ctk.CTkButton(
            self.resume_frame,
            text="Начать заново",
            width=130,
            fg_color=self.colors["surface_hover"],
            hover_color=self.colors["accent_hover"],
            text_color=self.colors["text"],
            command=self._clear_resume_state,
        )
        self.reset_queue_button.grid(row=0, column=2, sticky="e")
        self._refresh_resume_block()

    def _run_test_send(self) -> None:
        if self._test_running:
            return
        self._test_running = True
        self.test_button.configure(state="disabled")
        self.test_result_label.configure(text="Отправляю тест...", text_color=self.colors["muted"])
        recipient = self.test_email_entry.get().strip()

        def worker() -> None:
            try:
                result = self.delivery.send_test(recipient)
            except Exception as exc:
                self._queue.put(("test_error", exc))
            else:
                self._queue.put(("test_result", result))

        threading.Thread(target=worker, daemon=True).start()

    def _show_preview(self) -> None:
        try:
            rendered = self.delivery.preview_email(self.test_email_entry.get().strip() or "preview@example.com")
        except Exception as exc:
            self._set_campaign_status(str(exc), self.colors["error"])
            return

        text = _rendered_email_preview(rendered)
        self._set_preview_text(text)
        self._open_preview_window(text)
        self._set_campaign_status("Превью собрано. Проверьте From, Subject, ссылки и тело.", self.colors["accent"])

    def _start_campaign(self) -> None:
        try:
            settings = self._read_settings()
            self.controller.start_new(settings)
        except Exception as exc:
            self._set_campaign_status(str(exc), self.colors["error"])
            return
        self._set_campaign_status("Рассылка запущена.", self.colors["accent"])
        self._refresh_buttons()

    def _resume_campaign(self) -> None:
        try:
            settings = self._read_settings()
            self.controller.resume(settings)
        except Exception as exc:
            self._set_campaign_status(str(exc), self.colors["error"])
            return
        self._set_campaign_status("Продолжаю прерванную рассылку.", self.colors["accent"])
        self._refresh_buttons()

    def _stop_campaign(self) -> None:
        self.controller.stop()
        self._set_campaign_status(self.controller.last_result, self.colors["warning"])
        self._refresh_buttons()

    def _toggle_pause(self) -> None:
        state = self.controller.toggle_pause()
        color = self.colors["warning"] if state == "paused" else self.colors["accent"]
        self._set_campaign_status(self.controller.last_result, color)
        self._refresh_buttons()

    def _clear_resume_state(self) -> None:
        self.app_state.queue_manager.clear_state()
        self._refresh_resume_block()
        self._set_campaign_status("Сохранённая очередь очищена.", self.colors["muted"])

    def _poll_queue(self) -> None:
        while True:
            try:
                event, payload = self._queue.get_nowait()
            except queue.Empty:
                break

            if event == "test_result":
                self._test_running = False
                result = _require_type(payload, SendResult)
                color = self.colors["accent"] if result.ok else self.colors["error"]
                prefix = "✓" if result.ok else "✗"
                self.test_result_label.configure(text=f"{prefix} {result.message}", text_color=color)
            elif event == "test_error":
                self._test_running = False
                self.test_result_label.configure(text=f"✗ ошибка: {payload}", text_color=self.colors["error"])

        self._refresh_buttons()
        self.after(300, self._poll_queue)

    def _refresh_runtime_state(self) -> None:
        if self.controller.is_running():
            self._set_campaign_status(self.controller.last_result or "Рассылка работает...", self.colors["accent"])
        elif self.controller.state in {"completed", "stopped", "error"} and self.controller.last_result:
            color = self.colors["accent"] if self.controller.state == "completed" else self.colors["warning"]
            if self.controller.state == "error":
                color = self.colors["error"]
            self._set_campaign_status(self.controller.last_result, color)
        self._refresh_resume_block()
        self._refresh_buttons()
        self.after(1000, self._refresh_runtime_state)

    def _refresh_buttons(self) -> None:
        running = self.controller.is_running()
        can_start, reason = self._can_start_campaign()
        self.start_button.configure(state="normal" if can_start and not running else "disabled")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.pause_button.configure(state="normal" if running else "disabled")
        self.test_button.configure(state="disabled" if self._test_running else "normal")
        if not running and not can_start:
            current = str(self.campaign_status_label.cget("text"))
            if current.startswith("СТАРТ") or current.startswith("Рассылка") or current.startswith("Сохранённая"):
                self._set_campaign_status(reason, self.colors["muted"])

    def _refresh_resume_block(self) -> None:
        if self.controller.is_running():
            self.resume_label.configure(text="Рассылка активна. Прогресс сохраняется автоматически.")
            self.resume_button.configure(state="disabled")
            self.reset_queue_button.configure(state="disabled")
            return

        if self.app_state.queue_manager.has_unfinished_state():
            try:
                snapshot = self.app_state.queue_manager.load_state()
                text = f"Найдена прерванная рассылка: отправлено {snapshot.processed} из {snapshot.total}."
            except Exception:
                text = "Найдена прерванная рассылка."
            self.resume_label.configure(text=text)
            self.resume_button.configure(state="normal")
            self.reset_queue_button.configure(state="normal")
        else:
            self.resume_label.configure(text="Прерванных рассылок нет.")
            self.resume_button.configure(state="disabled")
            self.reset_queue_button.configure(state="disabled")

    def _can_start_campaign(self) -> tuple[bool, str]:
        if not self.app_state.get_recipients():
            return False, "СТАРТ недоступен: загрузите базу на вкладке Campaign."
        if not self.app_state.smtp_manager.get_all():
            return False, "СТАРТ недоступен: загрузите SMTP на вкладке Setup."
        if self.app_state.subject_manager.count() == 0:
            return False, "СТАРТ недоступен: загрузите темы на вкладке Content."
        if self.app_state.body_manager.count() == 0:
            return False, "СТАРТ недоступен: загрузите тела на вкладке Content."
        return True, "Готово к запуску."

    def _read_settings(self) -> CampaignSettings:
        settings = CampaignSettings(
            delay_seconds=_parse_non_negative_float(self.delay_entry.get(), "Задержка"),
            emails_per_minute=_parse_non_negative_float(self.rate_entry.get(), "Писем в минуту"),
            jitter_seconds=_parse_non_negative_float(self.jitter_entry.get(), "Разброс задержки"),
        )
        self.app_state.set_send_settings(
            settings.delay_seconds,
            settings.emails_per_minute,
            settings.jitter_seconds,
        )
        return settings

    def _sync_send_settings_to_state(self, _event: object | None = None) -> None:
        try:
            self._read_settings()
        except SenderError:
            return

    def _on_preset_loaded(self, _event: object | None = None) -> None:
        self._replace_entry_text(self.delay_entry, _format_number(self.app_state.delay_seconds))
        self._replace_entry_text(self.rate_entry, _format_number(self.app_state.emails_per_minute))
        self._replace_entry_text(self.jitter_entry, _format_number(self.app_state.jitter_seconds))
        self._refresh_buttons()
        self._set_campaign_status("Пресет загружен. Настройки скорости восстановлены.", self.colors["accent"])

    def _replace_entry_text(self, entry: ctk.CTkEntry, text: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, text)

    def _set_campaign_status(self, text: str, color: str) -> None:
        self.campaign_status_label.configure(text=text, text_color=color)

    def _set_preview_text(self, text: str) -> None:
        self.preview_textbox.configure(state="normal")
        self.preview_textbox.delete("1.0", "end")
        self.preview_textbox.insert("1.0", text)
        self.preview_textbox.configure(state="disabled")

    def _open_preview_window(self, text: str) -> None:
        window = ctk.CTkToplevel(self)
        window.title("Превью письма")
        window.geometry("760x560")
        window.configure(fg_color=self.colors["background"])
        window.grid_rowconfigure(0, weight=1)
        window.grid_columnconfigure(0, weight=1)

        textbox = ctk.CTkTextbox(
            window,
            fg_color=self.colors["surface"],
            text_color=self.colors["text"],
            wrap="word",
        )
        textbox.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")


def _rendered_email_preview(rendered: RenderedEmail) -> str:
    from_header = (
        f'"{rendered.sender_name}" <{rendered.sender_email}>'
        if rendered.sender_name
        else rendered.sender_email
    )
    cc_header = f"Cc: {', '.join(rendered.cc)}\n" if rendered.cc else ""
    bcc_header = f"Bcc: {', '.join(rendered.bcc)}\n" if rendered.bcc else ""
    return (
        f"From: {from_header}\n"
        f"To: {rendered.recipient}\n"
        f"{cc_header}"
        f"{bcc_header}"
        f"Subject: {rendered.subject}\n"
        f"Format: {rendered.body_format}\n"
        "\n"
        f"{rendered.body}"
    )


def _parse_non_negative_float(value: str, label: str) -> float:
    raw = value.strip().replace(",", ".")
    if not raw:
        return 0.0
    try:
        number = float(raw)
    except ValueError as exc:
        raise SenderError(f"{label}: введите число") from exc
    if number < 0:
        raise SenderError(f"{label}: значение не может быть отрицательным")
    return number


def _format_number(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _require_type(value: object, expected_type: type[object]) -> object:
    if not isinstance(value, expected_type):
        raise TypeError(f"Unexpected result type: {type(value).__name__}")
    return value

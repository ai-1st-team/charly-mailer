"""Campaign tab: recipients, control inject, CC, and BCC settings."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from tkinter import filedialog

import customtkinter as ctk

from core.app_state import get_app_state
from core.presets import PRESETS_DIR, PresetError, load_preset, save_preset
from core.storage import StorageError, read_recipients_csv


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def build_campaign_tab(parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
    """Build the Campaign tab."""
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    CampaignPanel(parent, colors).grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=20,
        pady=20,
    )


class CampaignPanel(ctk.CTkFrame):
    """Recipient base and control email injection settings."""

    def __init__(self, parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
        super().__init__(parent, fg_color=colors["background"])
        self.colors = colors
        self.app_state = get_app_state()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.content_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=self.colors["background"],
            scrollbar_button_color=self.colors["surface_hover"],
            scrollbar_button_hover_color=self.colors["accent_hover"],
        )
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)

        self._build_recipients_block()
        self._build_control_block()
        self._build_additional_recipients_block()
        self._build_presets_block()
        self._refresh_preview()
        self._sync_control_settings()
        self._sync_additional_settings()

    def _build_recipients_block(self) -> None:
        block = ctk.CTkFrame(
            self.content_frame,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        block.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="База получателей",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        self.recipient_count_label = ctk.CTkLabel(
            header,
            text="загружено 0 получателей",
            text_color=self.colors["muted"],
        )
        self.recipient_count_label.grid(row=0, column=1, sticky="e")

        controls = ctk.CTkFrame(block, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        controls.grid_columnconfigure(1, weight=1)

        self.load_base_button = ctk.CTkButton(
            controls,
            text="Загрузить базу",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_recipients_file,
        )
        self.load_base_button.grid(row=0, column=0, sticky="w", padx=(0, 12))

        self.base_status_label = ctk.CTkLabel(
            controls,
            text="CSV: обязательная колонка email, name опциональна.",
            text_color=self.colors["muted"],
            anchor="w",
        )
        self.base_status_label.grid(row=0, column=1, sticky="ew")

    def _build_control_block(self) -> None:
        block = ctk.CTkFrame(
            self.content_frame,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=1, column=0, sticky="nsew")
        block.grid_rowconfigure(2, weight=1)
        block.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Control-инжект",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        fields = ctk.CTkFrame(block, fg_color="transparent")
        fields.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        fields.grid_columnconfigure(1, weight=0)
        fields.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            fields,
            text="Контрольная почта каждые N писем",
            text_color=self.colors["muted"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.control_every_entry = ctk.CTkEntry(
            fields,
            width=90,
            fg_color=self.colors["background"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.control_every_entry.grid(row=0, column=1, sticky="w", padx=(0, 18))
        self.control_every_entry.insert(0, str(self.app_state.control_every or 100))
        self.control_every_entry.bind("<KeyRelease>", self._on_control_changed)

        ctk.CTkLabel(
            fields,
            text="Контрольные адреса",
            text_color=self.colors["muted"],
            anchor="w",
        ).grid(row=0, column=2, sticky="w", padx=(0, 8))

        self.control_emails_entry = ctk.CTkEntry(
            fields,
            placeholder_text="mybox1@gmail.com, mybox2@protonmail.com",
            fg_color=self.colors["background"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.control_emails_entry.grid(row=0, column=3, sticky="ew")
        self.control_emails_entry.bind("<KeyRelease>", self._on_control_changed)

        if self.app_state.control_recipients:
            self.control_emails_entry.insert(
                0,
                ", ".join(str(item.get("email", "")) for item in self.app_state.control_recipients),
            )

        preview_wrapper = ctk.CTkFrame(block, fg_color=self.colors["background"])
        preview_wrapper.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        preview_wrapper.grid_rowconfigure(1, weight=1)
        preview_wrapper.grid_columnconfigure(0, weight=1)

        table_header = ctk.CTkFrame(preview_wrapper, fg_color="transparent")
        table_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        table_header.grid_columnconfigure(0, weight=2)
        table_header.grid_columnconfigure(1, weight=1)

        self._header_label(table_header, "email", 0)
        self._header_label(table_header, "name", 1)

        self.preview_rows = ctk.CTkFrame(preview_wrapper, fg_color="transparent")
        self.preview_rows.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.preview_rows.grid_columnconfigure(0, weight=2)
        self.preview_rows.grid_columnconfigure(1, weight=1)

        self.control_status_label = ctk.CTkLabel(
            block,
            text="N=100 по умолчанию. Поставьте 0, чтобы отключить control-инжект.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
        )
        self.control_status_label.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

    def _build_additional_recipients_block(self) -> None:
        block = ctk.CTkFrame(
            self.content_frame,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        block.grid_columnconfigure(1, weight=1)
        block.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            block,
            text="Дополнительные получатели",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=4, sticky="ew", padx=16, pady=(14, 10))

        ctk.CTkLabel(block, text="CC адреса", text_color=self.colors["muted"], anchor="w").grid(
            row=1, column=0, sticky="nw", padx=(16, 8), pady=(0, 8)
        )
        self.cc_textbox = ctk.CTkTextbox(
            block,
            height=52,
            fg_color=self.colors["background"],
            border_width=1,
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
            wrap="word",
        )
        self.cc_textbox.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=(0, 8))
        self.cc_textbox.insert("1.0", ", ".join(self.app_state.cc_addresses))
        self.cc_textbox.bind("<KeyRelease>", self._on_additional_changed)

        ctk.CTkLabel(block, text="Процент писем с CC", text_color=self.colors["muted"], anchor="w").grid(
            row=1, column=2, sticky="w", padx=(0, 8), pady=(0, 8)
        )
        self.cc_percent_entry = self._percent_entry(block, self.app_state.cc_percent, 1, 3)

        ctk.CTkLabel(block, text="BCC адреса", text_color=self.colors["muted"], anchor="w").grid(
            row=2, column=0, sticky="nw", padx=(16, 8), pady=(0, 8)
        )
        self.bcc_textbox = ctk.CTkTextbox(
            block,
            height=52,
            fg_color=self.colors["background"],
            border_width=1,
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
            wrap="word",
        )
        self.bcc_textbox.grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=(0, 8))
        self.bcc_textbox.insert("1.0", ", ".join(self.app_state.bcc_addresses))
        self.bcc_textbox.bind("<KeyRelease>", self._on_additional_changed)

        ctk.CTkLabel(block, text="Процент писем с BCC", text_color=self.colors["muted"], anchor="w").grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=(0, 8)
        )
        self.bcc_percent_entry = self._percent_entry(block, self.app_state.bcc_percent, 2, 3)

        self.additional_status_label = ctk.CTkLabel(
            block,
            text="CC/BCC добавляются случайно по проценту для каждого письма.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
        )
        self.additional_status_label.grid(row=3, column=0, columnspan=4, sticky="ew", padx=16, pady=(0, 14))

    def _build_presets_block(self) -> None:
        block = ctk.CTkFrame(
            self.content_frame,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        block.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            block,
            text="Пресеты кампании",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(14, 10))

        self.save_preset_button = ctk.CTkButton(
            block,
            text="💾 Сохранить пресет",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._save_preset,
        )
        self.save_preset_button.grid(row=1, column=0, sticky="w", padx=(16, 10), pady=(0, 14))

        self.load_preset_button = ctk.CTkButton(
            block,
            text="📂 Загрузить пресет",
            fg_color=self.colors["surface_hover"],
            hover_color=self.colors["accent_hover"],
            text_color=self.colors["text"],
            command=self._load_preset,
        )
        self.load_preset_button.grid(row=1, column=1, sticky="w", padx=(0, 10), pady=(0, 14))

        self.preset_status_label = ctk.CTkLabel(
            block,
            text="Пресет хранит пути к файлам, control, CC/BCC и скорость отправки.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
        )
        self.preset_status_label.grid(row=1, column=2, sticky="ew", padx=(0, 16), pady=(0, 14))

    def _percent_entry(self, parent: ctk.CTkFrame, value: float, row: int, column: int) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(
            parent,
            width=80,
            fg_color=self.colors["background"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        entry.grid(row=row, column=column, sticky="ew", padx=(0, 16), pady=(0, 8))
        entry.insert(0, _format_percent(value))
        entry.bind("<KeyRelease>", self._on_additional_changed)
        return entry

    def _header_label(self, parent: ctk.CTkFrame, text: str, column: int) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=self.colors["muted"],
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=column, sticky="ew", padx=(0, 8))

    def _choose_recipients_file(self) -> None:
        initial_dir = Path("data") if Path("data").exists() else Path(".")
        file_path = filedialog.askopenfilename(
            title="Выберите CSV базу получателей",
            initialdir=str(initial_dir),
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            recipients = read_recipients_csv(Path(file_path))
        except StorageError as exc:
            self._set_base_status(str(exc), self.colors["error"])
            return

        self.app_state.set_recipients(recipients, source=Path(file_path))
        self._refresh_preview()
        self._set_base_status(f"Загружено из {Path(file_path).resolve()}", self.colors["accent"])

    def _refresh_preview(self) -> None:
        for child in self.preview_rows.winfo_children():
            child.destroy()

        recipients = self.app_state.get_recipients()
        self.recipient_count_label.configure(text=f"загружено {len(recipients)} получателей")

        if not recipients:
            ctk.CTkLabel(
                self.preview_rows,
                text="// TODO: база не загружена",
                text_color=self.colors["muted"],
                anchor="center",
            ).grid(row=0, column=0, columnspan=2, sticky="nsew", pady=42)
            return

        for row_index, recipient in enumerate(recipients[:5]):
            email = str(recipient.get("email", ""))
            name = str(recipient.get("name", ""))
            ctk.CTkLabel(
                self.preview_rows,
                text=email,
                text_color=self.colors["text"],
                anchor="w",
                wraplength=420,
            ).grid(row=row_index, column=0, sticky="ew", padx=(0, 8), pady=4)
            ctk.CTkLabel(
                self.preview_rows,
                text=name or "-",
                text_color=self.colors["muted"] if not name else self.colors["text"],
                anchor="w",
                wraplength=240,
            ).grid(row=row_index, column=1, sticky="ew", padx=(0, 8), pady=4)

    def _on_control_changed(self, _event: object | None = None) -> None:
        self._sync_control_settings()

    def _on_additional_changed(self, _event: object | None = None) -> None:
        self._sync_additional_settings()

    def _sync_control_settings(self) -> bool:
        try:
            control_every = self._parse_control_every()
            control_recipients = self._parse_control_recipients()
        except ValueError as exc:
            self.control_status_label.configure(text=str(exc), text_color=self.colors["error"])
            return False

        self.app_state.control_every = control_every
        self.app_state.control_recipients = control_recipients

        if control_every == 0:
            self.control_status_label.configure(
                text="Control-инжект отключён: N=0.",
                text_color=self.colors["muted"],
            )
        elif control_recipients:
            self.control_status_label.configure(
                text=f"Control включён: каждые {control_every} писем, адресов: {len(control_recipients)}.",
                text_color=self.colors["accent"],
            )
        else:
            self.control_status_label.configure(
                text="Control включится после ввода контрольных адресов.",
                text_color=self.colors["warning"],
            )
        return True

    def _parse_control_every(self) -> int:
        raw_value = self.control_every_entry.get().strip()
        if not raw_value:
            return 100
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError("N для control-инжекта должен быть целым числом") from exc
        if value < 0:
            raise ValueError("N для control-инжекта не может быть отрицательным")
        return value

    def _parse_control_recipients(self) -> list[dict[str, str]]:
        raw_value = self.control_emails_entry.get().strip()
        if not raw_value:
            return []

        recipients: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_email in raw_value.split(","):
            email = raw_email.strip().lower()
            if not email:
                continue
            if not EMAIL_RE.match(email):
                raise ValueError(f"Некорректная контрольная почта: {raw_email.strip()}")
            if email in seen:
                continue
            seen.add(email)
            recipients.append({"email": email, "name": "CONTROL"})
        return recipients

    def _sync_additional_settings(self) -> bool:
        try:
            cc_addresses = self._parse_email_list(self.cc_textbox.get("1.0", "end"))
            bcc_addresses = self._parse_email_list(self.bcc_textbox.get("1.0", "end"))
            cc_percent = self._parse_percent(self.cc_percent_entry.get(), "Процент CC")
            bcc_percent = self._parse_percent(self.bcc_percent_entry.get(), "Процент BCC")
        except ValueError as exc:
            self.additional_status_label.configure(text=str(exc), text_color=self.colors["error"])
            return False

        self.app_state.set_cc_bcc_settings(
            cc_addresses=cc_addresses,
            bcc_addresses=bcc_addresses,
            cc_percent=cc_percent,
            bcc_percent=bcc_percent,
        )
        self.additional_status_label.configure(
            text=(
                f"CC: {len(cc_addresses)} адресов, {cc_percent:g}% писем. "
                f"BCC: {len(bcc_addresses)} адресов, {bcc_percent:g}% писем."
            ),
            text_color=self.colors["accent"] if cc_addresses or bcc_addresses else self.colors["muted"],
        )
        return True

    def _parse_email_list(self, raw_value: str) -> list[str]:
        cleaned = raw_value.replace("\n", ",")
        addresses: list[str] = []
        seen: set[str] = set()
        for raw_email in cleaned.split(","):
            email = raw_email.strip().lower()
            if not email:
                continue
            if not EMAIL_RE.match(email):
                raise ValueError(f"Некорректный email в CC/BCC: {raw_email.strip()}")
            if email in seen:
                continue
            seen.add(email)
            addresses.append(email)
        return addresses

    def _parse_percent(self, raw_value: str, label: str) -> float:
        raw = raw_value.strip().replace(",", ".")
        if not raw:
            return 0.0
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{label}: введите число от 0 до 100") from exc
        if value < 0 or value > 100:
            raise ValueError(f"{label}: значение должно быть от 0 до 100")
        return value

    def _save_preset(self) -> None:
        if not self._sync_control_settings() or not self._sync_additional_settings():
            self._set_preset_status("Исправьте ошибки в настройках Campaign перед сохранением пресета.", self.colors["error"])
            return
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = filedialog.asksaveasfilename(
            title="Сохранить пресет кампании",
            initialdir=str(PRESETS_DIR),
            defaultextension=".json",
            filetypes=(("JSON presets", "*.json"), ("All files", "*.*")),
        )
        if not file_path:
            return
        try:
            result = save_preset(self.app_state, Path(file_path))
        except PresetError as exc:
            self._set_preset_status(str(exc), self.colors["error"])
            return
        self._set_preset_status(f"Пресет сохранён: {result.path}", self.colors["accent"])

    def _load_preset(self) -> None:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = filedialog.askopenfilename(
            title="Загрузить пресет кампании",
            initialdir=str(PRESETS_DIR),
            filetypes=(("JSON presets", "*.json"), ("All files", "*.*")),
        )
        if not file_path:
            return
        try:
            result = load_preset(self.app_state, Path(file_path))
        except PresetError as exc:
            self._set_preset_status(str(exc), self.colors["error"])
            return

        self._refresh_from_state()
        self.winfo_toplevel().event_generate("<<PresetLoaded>>", when="tail")
        if result.warnings:
            warning_text = "; ".join(result.warnings[:4])
            more = f" Ещё предупреждений: {len(result.warnings) - 4}." if len(result.warnings) > 4 else ""
            self._set_preset_status(f"Пресет загружен с предупреждениями: {warning_text}.{more}", self.colors["warning"])
        else:
            self._set_preset_status(f"Пресет загружен: {result.path}", self.colors["accent"])

    def _refresh_from_state(self) -> None:
        self._replace_entry_text(self.control_every_entry, str(self.app_state.control_every or 0))
        self._replace_entry_text(
            self.control_emails_entry,
            ", ".join(str(item.get("email", "")) for item in self.app_state.control_recipients),
        )
        self._replace_textbox_text(self.cc_textbox, ", ".join(self.app_state.cc_addresses))
        self._replace_textbox_text(self.bcc_textbox, ", ".join(self.app_state.bcc_addresses))
        self._replace_entry_text(self.cc_percent_entry, _format_percent(self.app_state.cc_percent))
        self._replace_entry_text(self.bcc_percent_entry, _format_percent(self.app_state.bcc_percent))
        self._refresh_preview()
        self._sync_control_settings()
        self._sync_additional_settings()

    def _replace_entry_text(self, entry: ctk.CTkEntry, text: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, text)

    def _replace_textbox_text(self, textbox: ctk.CTkTextbox, text: str) -> None:
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)

    def _set_base_status(self, text: str, color: str) -> None:
        self.base_status_label.configure(text=text, text_color=color)

    def _set_preset_status(self, text: str, color: str) -> None:
        self.preset_status_label.configure(text=text, text_color=color)


def _format_percent(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")

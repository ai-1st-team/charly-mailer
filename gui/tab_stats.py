"""Stats tab: campaign progress and delivery statistics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog

from core.stats import ProxyStats, SMTPStats, StatsError, StatsManager, export_log, get_stats_manager


def build_stats_tab(parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
    """Build the Stats tab."""
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    StatsPanel(parent, colors, get_stats_manager()).grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=16,
        pady=16,
    )


class StatsPanel(ctk.CTkFrame):
    """Real-time campaign stats view."""

    def __init__(self, parent: ctk.CTkFrame, colors: Mapping[str, str], manager: StatsManager) -> None:
        super().__init__(parent, fg_color=colors["background"])
        self.colors = colors
        self.manager = manager
        self._after_id: str | None = None

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_progress_block()
        self._build_global_block()
        self._build_tables_block()
        self._build_export_block()
        self._refresh()

    def destroy(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        super().destroy()

    def _build_progress_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        block.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            block,
            text="Остановлено",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))

        self.progress_bar = ctk.CTkProgressBar(
            block,
            fg_color=self.colors["background"],
            progress_color=self.colors["accent"],
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.progress_bar.set(0)

    def _build_global_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for column in range(5):
            block.grid_columnconfigure(column, weight=1)

        ctk.CTkLabel(
            block,
            text="Глобальные метрики",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=5, sticky="ew", padx=14, pady=(12, 8))

        self.metric_labels: dict[str, ctk.CTkLabel] = {}
        metrics = (
            ("sent_total", "Отправлено всего"),
            ("queued", "В очереди"),
            ("errors", "Ошибок"),
            ("speed", "Писем/мин"),
            ("started_at", "Старт"),
            ("current_time", "Текущее время"),
            ("eta", "Оценка завершения"),
        )

        for index, (key, title) in enumerate(metrics):
            row = 1 + index // 5
            column = index % 5
            cell = ctk.CTkFrame(block, fg_color=self.colors["background"])
            cell.grid(row=row, column=column, sticky="ew", padx=8, pady=(0, 10))
            cell.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                cell,
                text=title,
                text_color=self.colors["muted"],
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))

            label = ctk.CTkLabel(
                cell,
                text="0",
                text_color=self.colors["text"],
                anchor="w",
                wraplength=170,
            )
            label.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
            self.metric_labels[key] = label

    def _build_tables_block(self) -> None:
        block = ctk.CTkFrame(self, fg_color="transparent")
        block.grid(row=2, column=0, sticky="nsew")
        block.grid_rowconfigure(0, weight=1)
        block.grid_columnconfigure(0, weight=1)
        block.grid_columnconfigure(1, weight=1)

        self.smtp_table = self._build_table(
            block,
            title="SMTP-аккаунты",
            columns=("email", "использовано", "ошибок", "статус", "последняя активность"),
            column=0,
        )
        self.proxy_table = self._build_table(
            block,
            title="Прокси",
            columns=("адрес", "использовано", "ошибок", "статус"),
            column=1,
        )

    def _build_table(
        self,
        parent: ctk.CTkFrame,
        title: str,
        columns: tuple[str, ...],
        column: int,
    ) -> ctk.CTkScrollableFrame:
        wrapper = ctk.CTkFrame(
            parent,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        wrapper.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
        wrapper.grid_rowconfigure(2, weight=1)
        wrapper.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wrapper,
            text=title,
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))

        header = ctk.CTkFrame(wrapper, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        for index, name in enumerate(columns):
            header.grid_columnconfigure(index, weight=2 if index == 0 else 1)
            ctk.CTkLabel(
                header,
                text=name,
                text_color=self.colors["muted"],
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w",
            ).grid(row=0, column=index, sticky="ew", padx=(0, 6))

        rows = ctk.CTkScrollableFrame(wrapper, fg_color=self.colors["background"])
        rows.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        for index in range(len(columns)):
            rows.grid_columnconfigure(index, weight=2 if index == 0 else 1)
        return rows

    def _build_export_block(self) -> None:
        block = ctk.CTkFrame(self, fg_color="transparent")
        block.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        block.grid_columnconfigure(0, weight=1)

        self.export_status_label = ctk.CTkLabel(
            block,
            text="Лог текущего дня: logs/YYYY-MM-DD.json",
            text_color=self.colors["muted"],
            anchor="w",
        )
        self.export_status_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self.export_format_menu = ctk.CTkOptionMenu(
            block,
            values=("JSON", "CSV"),
            fg_color=self.colors["surface"],
            button_color=self.colors["surface_hover"],
            button_hover_color=self.colors["accent_hover"],
            text_color=self.colors["text"],
        )
        self.export_format_menu.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.export_format_menu.set("JSON")

        self.export_button = ctk.CTkButton(
            block,
            text="Экспорт лога",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._export_log,
        )
        self.export_button.grid(row=0, column=2, sticky="e")

    def _refresh(self) -> None:
        snapshot = self.manager.snapshot()
        global_stats = snapshot.global_stats
        sent = global_stats.sent_total
        errors = global_stats.errors
        total = global_stats.total_recipients
        processed = global_stats.processed
        percent = global_stats.progress_ratio * 100

        self.progress_bar.set(global_stats.progress_ratio)
        self.status_label.configure(
            text=self._status_text(global_stats.state, processed, total, percent),
            text_color=self._state_color(global_stats.state),
        )

        self.metric_labels["sent_total"].configure(text=str(sent))
        self.metric_labels["queued"].configure(text=str(global_stats.queued))
        self.metric_labels["errors"].configure(text=str(errors))
        self.metric_labels["speed"].configure(text=f"{global_stats.speed_per_minute:.1f}")
        self.metric_labels["started_at"].configure(text=global_stats.started_at)
        self.metric_labels["current_time"].configure(text=global_stats.current_time)
        self.metric_labels["eta"].configure(text=global_stats.eta)

        self._render_smtp_rows(snapshot.smtp_stats)
        self._render_proxy_rows(snapshot.proxy_stats)

        self._after_id = self.after(1000, self._refresh)

    def _render_smtp_rows(self, rows: tuple[SMTPStats, ...]) -> None:
        self._clear_rows(self.smtp_table)
        if not rows:
            self._empty_row(self.smtp_table, 5, "// TODO: SMTP-статистика появится после загрузки/рассылки")
            return

        for row_index, item in enumerate(rows):
            values = (item.email, str(item.sent), str(item.errors), item.status, item.last_activity or "-")
            self._table_row(self.smtp_table, row_index, values, status_column=3)

    def _render_proxy_rows(self, rows: tuple[ProxyStats, ...]) -> None:
        self._clear_rows(self.proxy_table)
        if not rows:
            self._empty_row(self.proxy_table, 4, "// TODO: прокси-статистика появится после загрузки/рассылки")
            return

        for row_index, item in enumerate(rows):
            values = (item.address, str(item.used), str(item.errors), item.status)
            self._table_row(self.proxy_table, row_index, values, status_column=3)

    def _clear_rows(self, frame: ctk.CTkScrollableFrame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _empty_row(self, frame: ctk.CTkScrollableFrame, columns: int, text: str) -> None:
        ctk.CTkLabel(
            frame,
            text=text,
            text_color=self.colors["muted"],
            anchor="center",
        ).grid(row=0, column=0, columnspan=columns, sticky="nsew", pady=34)

    def _table_row(
        self,
        frame: ctk.CTkScrollableFrame,
        row: int,
        values: tuple[str, ...],
        status_column: int,
    ) -> None:
        for column, value in enumerate(values):
            color = self._status_color(value) if column == status_column else self.colors["text"]
            ctk.CTkLabel(
                frame,
                text=value,
                text_color=color,
                anchor="w",
                justify="left",
                wraplength=190 if column == 0 else 120,
            ).grid(row=row, column=column, sticky="ew", padx=(0, 6), pady=3)

    def _export_log(self) -> None:
        export_format = self.export_format_menu.get().lower()
        suffix = ".csv" if export_format == "csv" else ".json"
        default_name = f"charly-log-{datetime.now().date().isoformat()}{suffix}"
        file_path = filedialog.asksaveasfilename(
            title="Экспорт лога",
            defaultextension=suffix,
            initialfile=default_name,
            filetypes=(("JSON", "*.json"), ("CSV", "*.csv"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            exported_path = export_log(file_path, export_format)  # type: ignore[arg-type]
        except StatsError as exc:
            self.export_status_label.configure(text=str(exc), text_color=self.colors["error"])
            return

        self.export_status_label.configure(text=f"Экспортировано: {exported_path}", text_color=self.colors["accent"])

    def _status_text(self, state: str, processed: int, total: int, percent: float) -> str:
        if state == "running":
            return f"Идёт рассылка: {processed} / {total} ({percent:.1f}%)"
        if state == "paused":
            return f"Пауза: {processed} / {total} ({percent:.1f}%)"
        if state == "completed":
            return f"Завершено: {processed} / {total} ({percent:.1f}%)"
        return "Остановлено"

    def _state_color(self, state: str) -> str:
        if state == "running":
            return self.colors["accent"]
        if state == "paused":
            return self.colors["warning"]
        if state == "completed":
            return self.colors["accent"]
        return self.colors["muted"]

    def _status_color(self, value: str) -> str:
        normalized = value.lower()
        if normalized in {"alive", "живой", "sent"}:
            return self.colors["accent"]
        if normalized in {"dead", "мёртвый", "error"}:
            return self.colors["error"]
        if normalized in {"checking", "paused", "проверка"}:
            return self.colors["warning"]
        return self.colors["muted"]

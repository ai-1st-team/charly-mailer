"""Content tab: subjects, email bodies, links, and sender names."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from core.app_state import get_app_state
from core.content import (
    BodyLoadResult,
    BodyManager,
    BodyRenderResult,
    ContentError,
    LinkLoadResult,
    LinkManager,
    RecipientContext,
    SenderNameLoadResult,
    SubjectLoadResult,
    SubjectManager,
    link_macro_name,
)


def build_content_tab(parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
    """Build the Content tab."""
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)

    ContentPanel(parent, colors).grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=20,
        pady=20,
    )


class ContentPanel(ctk.CTkFrame):
    """Content controls for subjects and future message assets."""

    def __init__(self, parent: ctk.CTkFrame, colors: Mapping[str, str]) -> None:
        super().__init__(parent, fg_color=colors["background"])
        self.colors = colors
        self.app_state = get_app_state()
        self.subject_manager = self.app_state.subject_manager
        self.body_manager = self.app_state.body_manager
        self.link_manager = self.app_state.link_manager
        self.sender_name_manager = self.app_state.sender_name_manager

        self.grid_rowconfigure(0, weight=2)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_subjects_block()
        self._build_sender_names_block()
        self._build_links_block()
        self._build_bodies_block()
        self.winfo_toplevel().bind("<<PresetLoaded>>", self._on_preset_loaded, add="+")

    def _build_subjects_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        block.grid_rowconfigure(2, weight=1)
        block.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Темы писем",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.subject_count_label = ctk.CTkLabel(
            header,
            text="загружено 0 тем",
            text_color=self.colors["muted"],
        )
        self.subject_count_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        controls = ctk.CTkFrame(block, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        controls.grid_columnconfigure(1, weight=1)

        self.load_subjects_button = ctk.CTkButton(
            controls,
            text="Загрузить темы",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_subjects_file,
        )
        self.load_subjects_button.grid(row=0, column=0, sticky="w", padx=(0, 12))

        self.status_label = ctk.CTkLabel(
            controls,
            text="Файл: subjects.txt, одна строка — одна тема.",
            text_color=self.colors["muted"],
            anchor="w",
        )
        self.status_label.grid(row=0, column=1, sticky="ew")

        content = ctk.CTkFrame(block, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        self._build_preview(content)
        self._build_try_panel(content)

    def _build_preview(self, parent: ctk.CTkFrame) -> None:
        preview = ctk.CTkFrame(parent, fg_color=self.colors["background"])
        preview.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        preview.grid_rowconfigure(1, weight=1)
        preview.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            preview,
            text="Превью первых 5 строк",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        self.preview_frame = ctk.CTkFrame(preview, fg_color="transparent")
        self.preview_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.preview_frame.grid_columnconfigure(0, weight=1)

        self._refresh_preview([])

    def _build_try_panel(self, parent: ctk.CTkFrame) -> None:
        try_panel = ctk.CTkFrame(parent, fg_color=self.colors["background"])
        try_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        try_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            try_panel,
            text="Попробовать на email",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        self.test_email_entry = ctk.CTkEntry(
            try_panel,
            placeholder_text="recipient@example.com",
            fg_color=self.colors["surface"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.test_email_entry.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.test_email_entry.bind("<KeyRelease>", self._update_render_preview)

        self.test_name_entry = ctk.CTkEntry(
            try_panel,
            placeholder_text="name из CSV",
            fg_color=self.colors["surface"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.test_name_entry.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.test_name_entry.bind("<KeyRelease>", self._update_render_preview)

        self.sender_name_entry = ctk.CTkEntry(
            try_panel,
            placeholder_text="senderName из senders.txt",
            fg_color=self.colors["surface"],
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
        )
        self.sender_name_entry.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.sender_name_entry.bind("<KeyRelease>", self._update_render_preview)

        self.render_button = ctk.CTkButton(
            try_panel,
            text="Сгенерировать пример",
            fg_color=self.colors["warning"],
            hover_color="#f59e0b",
            text_color="#050505",
            command=self._update_render_preview,
        )
        self.render_button.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.rendered_subject_label = ctk.CTkLabel(
            try_panel,
            text="// TODO: загрузите темы",
            text_color=self.colors["muted"],
            anchor="nw",
            justify="left",
            wraplength=360,
        )
        self.rendered_subject_label.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))

    def _build_sender_names_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=8)
        block.grid_rowconfigure(2, weight=1)
        block.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Имена отправителей",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.sender_names_count_label = ctk.CTkLabel(
            header,
            text="загружено 0 имён",
            text_color=self.colors["muted"],
        )
        self.sender_names_count_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        controls = ctk.CTkFrame(block, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        controls.grid_columnconfigure(1, weight=1)

        self.load_sender_names_button = ctk.CTkButton(
            controls,
            text="Загрузить имена отправителей",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_sender_names_file,
        )
        self.load_sender_names_button.grid(row=0, column=0, sticky="w", padx=(0, 12))

        self.email_only_checkbox = ctk.CTkCheckBox(
            controls,
            text="использовать только email без имени",
            text_color=self.colors["text"],
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            border_color=self.colors["muted"],
            command=self._on_email_only_changed,
        )
        self.email_only_checkbox.grid(row=0, column=1, sticky="w")
        if self.app_state.from_email_only:
            self.email_only_checkbox.select()

        self.sender_names_preview_frame = ctk.CTkFrame(block, fg_color=self.colors["background"])
        self.sender_names_preview_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.sender_names_preview_frame.grid_columnconfigure(0, weight=1)

        self.sender_names_status_label = ctk.CTkLabel(
            block,
            text="Файл: senders.txt, одна строка — одно имя отправителя.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
        )
        self.sender_names_status_label.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._update_sender_names_count()
        self._refresh_sender_names_preview(self.sender_name_manager.preview(5))

    def _build_links_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        block.grid_rowconfigure(2, weight=1)
        block.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Ссылки",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.links_count_label = ctk.CTkLabel(
            header,
            text="загружено 0 списков",
            text_color=self.colors["muted"],
        )
        self.links_count_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        controls = ctk.CTkFrame(block, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        controls.grid_columnconfigure(1, weight=1)

        self.load_links_button = ctk.CTkButton(
            controls,
            text="Загрузить ссылки",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_links_files,
        )
        self.load_links_button.grid(row=0, column=0, sticky="w", padx=(0, 12))

        self.unique_links_checkbox = ctk.CTkCheckBox(
            controls,
            text="уникальные ссылки в письме",
            text_color=self.colors["text"],
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            border_color=self.colors["muted"],
            command=self._on_unique_links_changed,
        )
        self.unique_links_checkbox.grid(row=0, column=1, sticky="w")
        if self.app_state.unique_links_per_message:
            self.unique_links_checkbox.select()

        self.links_list_frame = ctk.CTkScrollableFrame(
            block,
            fg_color=self.colors["background"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        self.links_list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.links_list_frame.grid_columnconfigure(0, weight=1)

        self.links_status_label = ctk.CTkLabel(
            block,
            text="Макросы: [[LINK]], [[LINK1]], [[LINK2]]...",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
        )
        self.links_status_label.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._refresh_links_list()

    def _build_bodies_block(self) -> None:
        block = ctk.CTkFrame(
            self,
            fg_color=self.colors["surface"],
            border_width=1,
            border_color=self.colors["surface_hover"],
        )
        block.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(8, 0))
        block.grid_rowconfigure(2, weight=1)
        block.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(block, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Тела писем",
            text_color=self.colors["text"],
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.body_count_label = ctk.CTkLabel(
            header,
            text="загружено 0 тел",
            text_color=self.colors["muted"],
        )
        self.body_count_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        controls = ctk.CTkFrame(block, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        controls.grid_columnconfigure(3, weight=1)

        self.load_bodies_button = ctk.CTkButton(
            controls,
            text="Загрузить тела",
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#050505",
            command=self._choose_bodies_file,
        )
        self.load_bodies_button.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.preview_body_button = ctk.CTkButton(
            controls,
            text="Превью",
            fg_color=self.colors["warning"],
            hover_color="#f59e0b",
            text_color="#050505",
            command=self._update_body_preview,
        )
        self.preview_body_button.grid(row=0, column=1, sticky="w", padx=(0, 8))

        self.refresh_body_button = ctk.CTkButton(
            controls,
            text="Обновить превью",
            fg_color=self.colors["surface_hover"],
            hover_color=self.colors["accent_hover"],
            text_color=self.colors["text"],
            command=self._update_body_preview,
        )
        self.refresh_body_button.grid(row=0, column=2, sticky="w", padx=(0, 8))

        self.body_format_label = ctk.CTkLabel(
            controls,
            text="формат: -",
            text_color=self.colors["muted"],
            anchor="e",
        )
        self.body_format_label.grid(row=0, column=3, sticky="e")

        self.body_preview_textbox = ctk.CTkTextbox(
            block,
            fg_color=self.colors["background"],
            border_width=1,
            border_color=self.colors["surface_hover"],
            text_color=self.colors["text"],
            wrap="word",
        )
        self.body_preview_textbox.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self._set_body_preview_text("// TODO: загрузите bodies.txt")

        self.body_status_label = ctk.CTkLabel(
            block,
            text="Разделитель тел: ===END=== на отдельной строке.",
            text_color=self.colors["muted"],
            anchor="w",
            justify="left",
            wraplength=420,
        )
        self.body_status_label.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

    def _choose_subjects_file(self) -> None:
        initial_dir = Path("data") if Path("data").exists() else Path(".")
        file_path = filedialog.askopenfilename(
            title="Выберите subjects.txt",
            initialdir=str(initial_dir),
            initialfile="subjects.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            result = self.subject_manager.load_from_file(Path(file_path))
        except ContentError as exc:
            self._set_status(str(exc), self.colors["error"])
            self._refresh_preview([])
            self._update_count()
            self._update_render_preview()
            return

        self._on_subjects_loaded(result)

    def _choose_bodies_file(self) -> None:
        initial_dir = Path("data") if Path("data").exists() else Path(".")
        file_path = filedialog.askopenfilename(
            title="Выберите bodies.txt",
            initialdir=str(initial_dir),
            initialfile="bodies.txt",
            filetypes=(("Text files", "*.txt"), ("HTML files", "*.html"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            result = self.body_manager.load_from_file(Path(file_path))
        except ContentError as exc:
            self._set_body_status(str(exc), self.colors["error"])
            self._update_body_count()
            self._set_body_preview_text("// TODO: тела не загружены")
            self.body_format_label.configure(text="формат: -", text_color=self.colors["muted"])
            return

        self._on_bodies_loaded(result)

    def _choose_links_files(self) -> None:
        initial_dir = Path("data") if Path("data").exists() else Path(".")
        file_paths = filedialog.askopenfilenames(
            title="Выберите links.txt, links1.txt, links2.txt...",
            initialdir=str(initial_dir),
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not file_paths:
            return

        try:
            results = self.link_manager.load_from_files(tuple(Path(path) for path in file_paths))
        except ContentError as exc:
            self._set_link_status(str(exc), self.colors["error"])
            self._refresh_links_list()
            return

        self._on_links_loaded(results)

    def _choose_sender_names_file(self) -> None:
        initial_dir = Path("data") if Path("data").exists() else Path(".")
        file_path = filedialog.askopenfilename(
            title="Выберите senders.txt",
            initialdir=str(initial_dir),
            initialfile="senders.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            result = self.app_state.load_sender_names_from_file(Path(file_path))
        except ContentError as exc:
            self._set_sender_names_status(str(exc), self.colors["error"])
            self._refresh_sender_names_preview([])
            self._update_sender_names_count()
            self._update_render_preview()
            if self.body_manager.count() > 0:
                self._update_body_preview()
            return

        self._on_sender_names_loaded(result)

    def _on_subjects_loaded(self, result: SubjectLoadResult) -> None:
        self._set_status(f"Загружено из {result.source}", self.colors["accent"])
        self._update_count()
        self._refresh_preview(result.preview)
        self._update_render_preview()

    def _on_bodies_loaded(self, result: BodyLoadResult) -> None:
        self._set_body_status(f"Загружено из {result.source}", self.colors["accent"])
        self._update_body_count()
        self._update_body_preview()

    def _on_links_loaded(self, results: list[LinkLoadResult]) -> None:
        self._refresh_links_list()
        loaded_names = ", ".join(result.filename for result in results)
        self._set_link_status(f"Загружено: {loaded_names}", self.colors["accent"])
        self._update_render_preview()
        if self.body_manager.count() > 0:
            self._update_body_preview()

    def _on_sender_names_loaded(self, result: SenderNameLoadResult) -> None:
        self._set_sender_names_status(f"Загружено из {result.source}", self.colors["accent"])
        self._update_sender_names_count()
        self._refresh_sender_names_preview(result.preview)
        self._update_render_preview()
        if self.body_manager.count() > 0:
            self._update_body_preview()

    def _refresh_preview(self, subjects: list[str] | tuple[str, ...]) -> None:
        for child in self.preview_frame.winfo_children():
            child.destroy()

        if not subjects:
            ctk.CTkLabel(
                self.preview_frame,
                text="// TODO: темы не загружены",
                text_color=self.colors["muted"],
                anchor="center",
            ).grid(row=0, column=0, sticky="nsew", pady=40)
            return

        for index, subject in enumerate(subjects, start=1):
            ctk.CTkLabel(
                self.preview_frame,
                text=f"{index}. {subject}",
                text_color=self.colors["text"],
                anchor="w",
                justify="left",
                wraplength=360,
            ).grid(row=index - 1, column=0, sticky="ew", pady=4)

    def _update_render_preview(self, _event: object | None = None) -> None:
        if self.subject_manager.count() == 0:
            self.rendered_subject_label.configure(
                text="// TODO: загрузите темы",
                text_color=self.colors["muted"],
            )
            return

        recipient = RecipientContext(
            email=self.test_email_entry.get().strip() or "recipient@example.com",
            name=self.test_name_entry.get().strip(),
        )
        sender_name = self._current_sender_name()
        link_context = self.link_manager.create_context(self._unique_links_enabled())

        try:
            rendered = self.subject_manager.render_random(
                recipient,
                sender_name,
                link_manager=self.link_manager,
                link_context=link_context,
            )
        except ContentError as exc:
            self.rendered_subject_label.configure(text=str(exc), text_color=self.colors["error"])
            return

        self.rendered_subject_label.configure(text=rendered, text_color=self.colors["accent"])

    def _update_body_preview(self) -> None:
        if self.body_manager.count() == 0:
            self._set_body_status("Сначала загрузите bodies.txt.", self.colors["warning"])
            self._set_body_preview_text("// TODO: тела не загружены")
            self.body_format_label.configure(text="формат: -", text_color=self.colors["muted"])
            return

        recipient = self._current_recipient()
        sender_name = self._current_sender_name()
        link_context = self.link_manager.create_context(self._unique_links_enabled())

        if self.subject_manager.count() > 0:
            try:
                subject = self.subject_manager.render_random(
                    recipient,
                    sender_name,
                    link_manager=self.link_manager,
                    link_context=link_context,
                )
            except ContentError as exc:
                subject = f"[ошибка темы: {exc}]"
        else:
            subject = "[темы не загружены]"

        try:
            body_result = self.body_manager.render_random(
                recipient,
                sender_name,
                link_manager=self.link_manager,
                link_context=link_context,
            )
        except ContentError as exc:
            self._set_body_status(str(exc), self.colors["error"])
            self._set_body_preview_text(f"Ошибка генерации тела:\n{exc}")
            self.body_format_label.configure(text="формат: -", text_color=self.colors["error"])
            return

        self._show_body_preview(subject, body_result)

    def _update_count(self) -> None:
        count = self.subject_manager.count()
        self.subject_count_label.configure(text=f"загружено {count} тем")

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, text_color=color)

    def _update_sender_names_count(self) -> None:
        count = self.sender_name_manager.count()
        self.sender_names_count_label.configure(text=f"загружено {count} имён")

    def _refresh_sender_names_preview(self, names: list[str] | tuple[str, ...]) -> None:
        for child in self.sender_names_preview_frame.winfo_children():
            child.destroy()

        if not names:
            ctk.CTkLabel(
                self.sender_names_preview_frame,
                text="// TODO: имена отправителей не загружены",
                text_color=self.colors["muted"],
                anchor="center",
            ).grid(row=0, column=0, sticky="nsew", pady=12)
            return

        for index, name in enumerate(names, start=1):
            ctk.CTkLabel(
                self.sender_names_preview_frame,
                text=f"{index}. {name}",
                text_color=self.colors["text"],
                anchor="w",
                justify="left",
                wraplength=360,
            ).grid(row=index - 1, column=0, sticky="ew", padx=10, pady=2)

    def _update_body_count(self) -> None:
        count = self.body_manager.count()
        self.body_count_label.configure(text=f"загружено {count} тел")

    def _refresh_links_list(self) -> None:
        for child in self.links_list_frame.winfo_children():
            child.destroy()

        rows = self.link_manager.get_counts()
        if not rows:
            ctk.CTkLabel(
                self.links_list_frame,
                text="// TODO: списки ссылок не загружены",
                text_color=self.colors["muted"],
                anchor="center",
            ).grid(row=0, column=0, sticky="nsew", pady=20)
        else:
            for row_index, (key, filename, count) in enumerate(rows):
                macro = link_macro_name(key)
                ctk.CTkLabel(
                    self.links_list_frame,
                    text=f"{count} ссылок в {filename}  →  {macro}",
                    text_color=self.colors["text"],
                    anchor="w",
                    justify="left",
                    wraplength=360,
                ).grid(row=row_index, column=0, sticky="ew", padx=8, pady=4)

        self.links_count_label.configure(text=f"загружено {len(rows)} списков")

    def _show_body_preview(self, subject: str, body_result: BodyRenderResult) -> None:
        preview_text = (
            f"Subject: {subject}\n"
            f"Format: {body_result.body_format}\n"
            "\n"
            f"{body_result.body}"
        )
        self._set_body_preview_text(preview_text)
        self.body_format_label.configure(
            text=f"формат: {body_result.body_format}",
            text_color=self.colors["accent"],
        )
        self._set_body_status("Превью сгенерировано.", self.colors["accent"])

    def _set_body_preview_text(self, text: str) -> None:
        self.body_preview_textbox.configure(state="normal")
        self.body_preview_textbox.delete("1.0", "end")
        self.body_preview_textbox.insert("1.0", text)
        self.body_preview_textbox.configure(state="disabled")

    def _current_recipient(self) -> RecipientContext:
        return RecipientContext(
            email=self.test_email_entry.get().strip() or "recipient@example.com",
            name=self.test_name_entry.get().strip(),
        )

    def _current_sender_name(self) -> str:
        if self.app_state.from_email_only:
            return ""
        manual_name = self.sender_name_entry.get().strip()
        if manual_name:
            return manual_name
        return self.app_state.choose_sender_name()

    def _set_body_status(self, text: str, color: str) -> None:
        self.body_status_label.configure(text=text, text_color=color)

    def _set_link_status(self, text: str, color: str) -> None:
        self.links_status_label.configure(text=text, text_color=color)

    def _set_sender_names_status(self, text: str, color: str) -> None:
        self.sender_names_status_label.configure(text=text, text_color=color)

    def _unique_links_enabled(self) -> bool:
        return bool(self.unique_links_checkbox.get())

    def _email_only_enabled(self) -> bool:
        return bool(self.email_only_checkbox.get())

    def _on_unique_links_changed(self) -> None:
        self.app_state.unique_links_per_message = self._unique_links_enabled()
        state = "включены" if self._unique_links_enabled() else "выключены"
        self._set_link_status(f"Уникальные ссылки в письме: {state}.", self.colors["muted"])
        self._update_render_preview()
        if self.body_manager.count() > 0:
            self._update_body_preview()

    def _on_email_only_changed(self) -> None:
        self.app_state.from_email_only = self._email_only_enabled()
        if self.app_state.from_email_only:
            self._set_sender_names_status("From будет содержать только email SMTP-аккаунта.", self.colors["warning"])
        else:
            self._set_sender_names_status("Имена отправителей включены.", self.colors["muted"])
        self._update_render_preview()
        if self.body_manager.count() > 0:
            self._update_body_preview()

    def _on_preset_loaded(self, _event: object | None = None) -> None:
        self._update_count()
        self._refresh_preview(self.subject_manager.preview(5))
        self._refresh_links_list()
        self._update_body_count()
        self._update_sender_names_count()
        self._refresh_sender_names_preview(self.sender_name_manager.preview(5))
        _set_checkbox(self.unique_links_checkbox, self.app_state.unique_links_per_message)
        _set_checkbox(self.email_only_checkbox, self.app_state.from_email_only)
        self._set_status("Пресет загружен. Темы обновлены.", self.colors["accent"])
        self._set_link_status("Пресет загружен. Ссылки обновлены.", self.colors["accent"])
        self._set_sender_names_status("Пресет загружен. Имена отправителей обновлены.", self.colors["accent"])
        self._update_render_preview()
        if self.body_manager.count() > 0:
            self._update_body_preview()
        else:
            self._set_body_preview_text("// TODO: тела не загружены")
            self.body_format_label.configure(text="формат: -", text_color=self.colors["muted"])


def _set_checkbox(checkbox: ctk.CTkCheckBox, enabled: bool) -> None:
    if enabled:
        checkbox.select()
    else:
        checkbox.deselect()

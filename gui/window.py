"""Main application window and tab initialization."""

from __future__ import annotations

import customtkinter as ctk

from gui.tab_campaign import build_campaign_tab
from gui.tab_content import build_content_tab
from gui.tab_send import build_send_tab
from gui.tab_setup import build_setup_tab
from gui.tab_stats import build_stats_tab


COLORS = {
    "background": "#0a0a0a",
    "surface": "#151515",
    "surface_hover": "#202020",
    "text": "#f5f5f5",
    "muted": "#737373",
    "accent": "#4ade80",
    "accent_hover": "#22c55e",
    "error": "#ef4444",
    "warning": "#fbbf24",
}


class MainWindow(ctk.CTk):
    """Root window for CHARLY MAILER."""

    TAB_SETUP = "Setup"
    TAB_CONTENT = "Content"
    TAB_CAMPAIGN = "Campaign"
    TAB_SEND = "Send"
    TAB_STATS = "Stats"

    def __init__(self) -> None:
        super().__init__()

        self.title("CHARLY MAILER")
        self.geometry("900x600")
        self.minsize(900, 600)
        self.configure(fg_color=COLORS["background"])

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tab_view = ctk.CTkTabview(
            self,
            fg_color=COLORS["background"],
            segmented_button_fg_color=COLORS["surface"],
            segmented_button_selected_color=COLORS["accent"],
            segmented_button_selected_hover_color=COLORS["accent_hover"],
            segmented_button_unselected_color=COLORS["surface"],
            segmented_button_unselected_hover_color=COLORS["surface_hover"],
            text_color=COLORS["text"],
        )
        self.tab_view.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

        setup_tab = self.tab_view.add(self.TAB_SETUP)
        content_tab = self.tab_view.add(self.TAB_CONTENT)
        campaign_tab = self.tab_view.add(self.TAB_CAMPAIGN)
        send_tab = self.tab_view.add(self.TAB_SEND)
        stats_tab = self.tab_view.add(self.TAB_STATS)

        build_setup_tab(setup_tab, COLORS)
        build_content_tab(content_tab, COLORS)
        build_campaign_tab(campaign_tab, COLORS)
        build_send_tab(send_tab, COLORS)
        build_stats_tab(stats_tab, COLORS)

        self.tab_view.set(self.TAB_SETUP)

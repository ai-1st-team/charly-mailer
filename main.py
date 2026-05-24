"""Application entry point for CHARLY MAILER."""

from pathlib import Path

import customtkinter as ctk

from gui.window import MainWindow


def main() -> None:
    """Configure CustomTkinter and start the GUI application."""
    _ensure_runtime_dirs()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("green")

    app = MainWindow()
    app.mainloop()


def _ensure_runtime_dirs() -> None:
    for folder in (Path("data"), Path("data") / "presets", Path("logs")):
        folder.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()

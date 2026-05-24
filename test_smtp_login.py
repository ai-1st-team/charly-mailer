"""Standalone SMTP login checker.

Usage:
    python test_smtp_login.py
    python test_smtp_login.py path/to/smtps.txt
"""

from __future__ import annotations

from pathlib import Path
import sys

from core.smtp_manager import SMTPManager, SMTPStatus


def main() -> int:
    file_path = _resolve_input_path()
    manager = SMTPManager()

    try:
        load_result = manager.load_from_file(file_path)
    except Exception as exc:
        print(f"LOAD ERROR: {exc}")
        return 1

    print(
        "Loaded: "
        f"{load_result.loaded}, invalid: {load_result.invalid}, "
        f"duplicates: {load_result.duplicates}, replaced: {load_result.replaced}"
    )
    for error in load_result.errors:
        print(f"PARSE ERROR: {error}")

    if not manager.get_all():
        print("No SMTP accounts to check.")
        return 1

    summary = manager.check_all()
    print(
        "Checked: "
        f"{summary.checked}, alive: {summary.alive}, "
        f"dead: {summary.dead}, unknown: {summary.unknown}"
    )

    for account in manager.get_all():
        status = account.status.upper()
        marker = "OK" if account.status == SMTPStatus.ALIVE else "FAIL"
        message = account.last_error or "Логин успешен"
        print(f"{marker} | {status} | {account.email} | {account.endpoint} | {message}")

    return 0 if summary.alive else 2


def _resolve_input_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])

    data_file = Path("data") / "smtps.txt"
    if data_file.exists():
        return data_file
    return Path("smtps.txt")


if __name__ == "__main__":
    raise SystemExit(main())

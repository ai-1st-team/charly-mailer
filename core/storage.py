"""Shared helpers for reading TXT and CSV files."""

from __future__ import annotations

import csv
import re
from pathlib import Path


TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StorageError(RuntimeError):
    """Raised when a local data file cannot be read safely."""


def read_text_lines(path: str | Path, ignore_comments: bool = True) -> list[str]:
    """Read useful lines from a text file."""
    file_path = Path(path)
    if not file_path.exists():
        raise StorageError(f"Файл не найден: {file_path}")
    if not file_path.is_file():
        raise StorageError(f"Это не файл: {file_path}")

    last_error: Exception | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            text = file_path.read_text(encoding=encoding)
            return parse_text_lines(text, ignore_comments=ignore_comments)
        except UnicodeDecodeError as exc:
            last_error = exc
        except OSError as exc:
            raise StorageError(f"Не удалось прочитать файл {file_path}: {exc}") from exc

    raise StorageError(f"Не удалось определить кодировку файла {file_path}") from last_error


def read_text_file(path: str | Path) -> str:
    """Read a whole text file preserving line breaks."""
    file_path = Path(path)
    if not file_path.exists():
        raise StorageError(f"Файл не найден: {file_path}")
    if not file_path.is_file():
        raise StorageError(f"Это не файл: {file_path}")

    last_error: Exception | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
        except OSError as exc:
            raise StorageError(f"Не удалось прочитать файл {file_path}: {exc}") from exc

    raise StorageError(f"Не удалось определить кодировку файла {file_path}") from last_error


def read_recipients_csv(path: str | Path) -> list[dict[str, str]]:
    """Read recipients CSV with required email and optional name columns."""
    file_path = Path(path)
    text = read_text_file(file_path)

    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    rows: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise StorageError("CSV пустой или не содержит заголовков")

    field_map = {field.strip().lower(): field for field in reader.fieldnames if field}
    email_field = field_map.get("email")
    name_field = field_map.get("name")
    if not email_field:
        raise StorageError("В CSV обязательна колонка email")

    for row_number, row in enumerate(reader, start=2):
        raw_email = str(row.get(email_field, "") or "").strip()
        if not raw_email or raw_email.startswith("#"):
            continue
        email = raw_email.lower()
        if not EMAIL_RE.match(email):
            raise StorageError(f"Некорректный email в строке {row_number}: {raw_email}")
        if email in seen_emails:
            continue
        seen_emails.add(email)
        name = str(row.get(name_field, "") or "").strip() if name_field else ""
        rows.append({"email": email, "name": name})

    if not rows:
        raise StorageError("В CSV не найдено получателей с email")
    return rows


def parse_text_lines(text: str, ignore_comments: bool = True) -> list[str]:
    """Return useful lines, optionally ignoring lines starting with #."""
    result: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ignore_comments and line.startswith("#"):
            continue
        result.append(line)
    return result

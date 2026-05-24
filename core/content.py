"""Email content loading and placeholder rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import re

from core.storage import StorageError, read_text_file, read_text_lines


PLACEHOLDER_RE = re.compile(r"\{\{\s*(name|email|senderName)\s*\}\}", re.IGNORECASE)
LINK_MACRO_RE = re.compile(r"\[\[LINK(\d*)\]\]", re.IGNORECASE)
LINKS_FILENAME_RE = re.compile(r"^links(\d*)\.txt$", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9:-]*(?:\s[^<>]*)?>")
BODY_SEPARATOR = "===END==="


class ContentError(RuntimeError):
    """Raised when content cannot be loaded or rendered."""


@dataclass(frozen=True)
class RecipientContext:
    """Recipient data available for placeholder rendering."""

    email: str
    name: str = ""


@dataclass(frozen=True)
class SubjectLoadResult:
    """Summary of loading subject lines."""

    source: str
    loaded: int
    preview: tuple[str, ...]


@dataclass(frozen=True)
class BodyLoadResult:
    """Summary of loading email bodies."""

    source: str
    loaded: int


@dataclass(frozen=True)
class BodyRenderResult:
    """Rendered body with detected format."""

    body: str
    body_format: str


@dataclass(frozen=True)
class LinkLoadResult:
    """Summary of loading one links file."""

    key: str
    filename: str
    source: str
    loaded: int


@dataclass(frozen=True)
class SenderNameLoadResult:
    """Summary of loading sender display names."""

    source: str
    loaded: int
    preview: tuple[str, ...]


@dataclass(frozen=True)
class _TextNode:
    value: str


@dataclass(frozen=True)
class _ChoiceNode:
    options: tuple[tuple["_SpintaxNode", ...], ...]


_SpintaxNode = _TextNode | _ChoiceNode


class SenderNameManager:
    """Load, store, and choose sender display names."""

    def __init__(self, random_source: random.Random | None = None) -> None:
        self._names: list[str] = []
        self._source = ""
        self._random = random_source or random.SystemRandom()

    def load_from_file(self, path: str | Path) -> SenderNameLoadResult:
        """Load sender names from a TXT file, ignoring empty/comment lines."""
        file_path = Path(path).resolve()
        try:
            names = read_text_lines(file_path, ignore_comments=True)
        except StorageError as exc:
            raise ContentError(str(exc)) from exc

        if not names:
            raise ContentError("Файл имён отправителей пустой")

        self._names = names
        self._source = str(file_path)
        return SenderNameLoadResult(
            source=self._source,
            loaded=len(self._names),
            preview=tuple(self.preview(5)),
        )

    def set_names(self, names: list[str]) -> None:
        """Replace sender names programmatically."""
        self._names = [name.strip() for name in names if name.strip()]
        self._source = ""

    def clear(self) -> None:
        """Clear loaded sender names."""
        self._names = []
        self._source = ""

    def get_all(self) -> list[str]:
        """Return loaded sender names snapshot."""
        return list(self._names)

    def count(self) -> int:
        """Return loaded sender names count."""
        return len(self._names)

    def preview(self, limit: int = 5) -> list[str]:
        """Return first N sender names."""
        if limit < 1:
            return []
        return self._names[:limit]

    def choose_random(self, default: str = "") -> str:
        """Return one random sender name or default when list is empty."""
        if not self._names:
            return default
        return self._random.choice(self._names)

    @property
    def source(self) -> str:
        """Return current source path."""
        return self._source


class SubjectManager:
    """Load, store, and render subject lines for campaign emails."""

    def __init__(self, random_source: random.Random | None = None) -> None:
        self._subjects: list[str] = []
        self._source = ""
        self._random = random_source or random.SystemRandom()

    def load_from_file(self, path: str | Path) -> SubjectLoadResult:
        """Load subjects from a TXT file, ignoring empty lines."""
        file_path = Path(path).resolve()
        try:
            subjects = read_text_lines(file_path, ignore_comments=False)
        except StorageError as exc:
            raise ContentError(str(exc)) from exc

        if not subjects:
            raise ContentError("Файл тем пустой")

        self._subjects = subjects
        self._source = str(file_path)
        return SubjectLoadResult(
            source=self._source,
            loaded=len(self._subjects),
            preview=tuple(self.preview(5)),
        )

    def get_all(self) -> list[str]:
        """Return loaded subjects snapshot."""
        return list(self._subjects)

    def clear(self) -> None:
        """Clear loaded subject templates."""
        self._subjects = []
        self._source = ""

    def count(self) -> int:
        """Return number of loaded subjects."""
        return len(self._subjects)

    def preview(self, limit: int = 5) -> list[str]:
        """Return first N loaded subjects."""
        if limit < 1:
            return []
        return self._subjects[:limit]

    def choose_random(self) -> str:
        """Return one random subject template."""
        if not self._subjects:
            raise ContentError("Темы не загружены")
        return self._random.choice(self._subjects)

    def render_random(
        self,
        recipient: RecipientContext,
        sender_name: str = "",
        link_manager: "LinkManager | None" = None,
        link_context: "LinkRenderContext | None" = None,
    ) -> str:
        """Choose and render one random subject for a recipient."""
        return render_subject(
            self.choose_random(),
            recipient,
            sender_name,
            link_manager=link_manager,
            link_context=link_context,
        )

    @property
    def source(self) -> str:
        """Return the current source path."""
        return self._source


def render_subject(
    template: str,
    recipient: RecipientContext | dict[str, str],
    sender_name: str = "",
    link_manager: "LinkManager | None" = None,
    link_context: "LinkRenderContext | None" = None,
) -> str:
    """Render supported placeholders in one subject template."""
    rendered = render_placeholders(template, recipient, sender_name)
    if link_manager is None:
        return rendered
    return link_manager.render_macros(rendered, link_context)


class LinkRenderContext:
    """Per-message link selection context."""

    def __init__(self, unique_per_message: bool = False) -> None:
        self.unique_per_message = unique_per_message
        self._used_by_key: dict[str, set[str]] = {}

    def remember(self, key: str, link: str) -> None:
        if not self.unique_per_message:
            return
        self._used_by_key.setdefault(key, set()).add(link)

    def used_for(self, key: str) -> set[str]:
        return self._used_by_key.setdefault(key, set())


class LinkManager:
    """Load link lists and render [[LINK]] macros."""

    def __init__(self, random_source: random.Random | None = None) -> None:
        self._links_by_key: dict[str, list[str]] = {}
        self._sources_by_key: dict[str, str] = {}
        self._random = random_source or random.SystemRandom()

    def load_from_files(self, paths: list[str | Path] | tuple[str | Path, ...]) -> list[LinkLoadResult]:
        """Load multiple links*.txt files."""
        if not paths:
            raise ContentError("Файлы ссылок не выбраны")

        results: list[LinkLoadResult] = []
        for path in paths:
            results.append(self.load_from_file(path))
        return results

    def load_from_file(self, path: str | Path) -> LinkLoadResult:
        """Load one links file and map it to its macro key."""
        file_path = Path(path).resolve()
        key = link_key_from_filename(file_path.name)

        try:
            links = read_text_lines(file_path, ignore_comments=False)
        except StorageError as exc:
            raise ContentError(str(exc)) from exc

        if not links:
            raise ContentError(f"Файл ссылок пустой: {file_path.name}")

        self._links_by_key[key] = links
        self._sources_by_key[key] = str(file_path)
        return LinkLoadResult(
            key=key,
            filename=file_path.name,
            source=str(file_path),
            loaded=len(links),
        )

    def create_context(self, unique_per_message: bool = False) -> LinkRenderContext:
        """Create a per-message context for link replacement."""
        return LinkRenderContext(unique_per_message=unique_per_message)

    def render_macros(
        self,
        template: str,
        context: LinkRenderContext | None = None,
    ) -> str:
        """Replace all [[LINK]], [[LINK1]], ... macros in a template."""
        render_context = context or self.create_context(False)

        def replace(match: re.Match[str]) -> str:
            key = normalize_link_key(match.group(1))
            return self.choose_link(key, render_context)

        return LINK_MACRO_RE.sub(replace, template)

    def choose_link(self, key: str, context: LinkRenderContext | None = None) -> str:
        """Choose one random link for a macro key."""
        normalized_key = normalize_link_key(key)
        links = self._links_by_key.get(normalized_key)
        if not links:
            macro = link_macro_name(normalized_key)
            expected_file = link_filename(normalized_key)
            raise ContentError(f"Макрос {macro} найден, но файл {expected_file} не загружен")

        render_context = context or self.create_context(False)
        if not render_context.unique_per_message:
            return self._random.choice(links)

        used = render_context.used_for(normalized_key)
        available = [link for link in links if link not in used]
        if not available:
            macro = link_macro_name(normalized_key)
            raise ContentError(f"Недостаточно уникальных ссылок для макроса {macro} в одном письме")

        link = self._random.choice(available)
        render_context.remember(normalized_key, link)
        return link

    def get_counts(self) -> list[tuple[str, str, int]]:
        """Return loaded list counters sorted by macro key."""
        rows: list[tuple[str, str, int]] = []
        for key, links in self._links_by_key.items():
            rows.append((key, link_filename(key), len(links)))
        return sorted(rows, key=lambda row: _link_sort_key(row[0]))

    def count_lists(self) -> int:
        """Return number of loaded link lists."""
        return len(self._links_by_key)

    def get_sources(self) -> list[str]:
        """Return loaded link file sources sorted by macro key."""
        return [source for _, source in sorted(self._sources_by_key.items(), key=lambda row: _link_sort_key(row[0]))]

    def clear(self) -> None:
        """Clear loaded link lists."""
        self._links_by_key.clear()
        self._sources_by_key.clear()


class BodyManager:
    """Load, store, and render email body templates."""

    def __init__(self, random_source: random.Random | None = None) -> None:
        self._bodies: list[str] = []
        self._source = ""
        self._random = random_source or random.SystemRandom()

    def load_from_file(self, path: str | Path) -> BodyLoadResult:
        """Load multiline bodies split by ===END=== on its own line."""
        file_path = Path(path).resolve()
        try:
            text = read_text_file(file_path)
        except StorageError as exc:
            raise ContentError(str(exc)) from exc

        bodies = split_bodies(text)
        if not bodies:
            raise ContentError("Файл тел писем пустой")

        self._bodies = bodies
        self._source = str(file_path)
        return BodyLoadResult(source=self._source, loaded=len(self._bodies))

    def get_all(self) -> list[str]:
        """Return loaded body templates snapshot."""
        return list(self._bodies)

    def clear(self) -> None:
        """Clear loaded body templates."""
        self._bodies = []
        self._source = ""

    def count(self) -> int:
        """Return number of loaded body templates."""
        return len(self._bodies)

    def choose_random(self) -> str:
        """Return one random body template."""
        if not self._bodies:
            raise ContentError("Тела писем не загружены")
        return self._random.choice(self._bodies)

    def render_random(
        self,
        recipient: RecipientContext,
        sender_name: str = "",
        link_manager: LinkManager | None = None,
        link_context: LinkRenderContext | None = None,
    ) -> BodyRenderResult:
        """Choose and render one random body for a recipient."""
        return render_body(
            self.choose_random(),
            recipient,
            sender_name,
            self._random,
            link_manager=link_manager,
            link_context=link_context,
        )

    @property
    def source(self) -> str:
        """Return the current source path."""
        return self._source


def split_bodies(text: str, separator: str = BODY_SEPARATOR) -> list[str]:
    """Split a body file into non-empty multiline body templates."""
    bodies: list[str] = []
    current: list[str] = []

    for line in text.splitlines():
        if line.strip() == separator:
            body = "\n".join(current).strip()
            if body:
                bodies.append(body)
            current = []
            continue
        current.append(line)

    body = "\n".join(current).strip()
    if body:
        bodies.append(body)

    return bodies


def render_body(
    template: str,
    recipient: RecipientContext | dict[str, str],
    sender_name: str = "",
    random_source: random.Random | None = None,
    link_manager: LinkManager | None = None,
    link_context: LinkRenderContext | None = None,
) -> BodyRenderResult:
    """Render spintax first, then placeholders, and detect body format."""
    expanded = render_spintax(template, random_source=random_source)
    rendered = render_placeholders(expanded, recipient, sender_name)
    if link_manager is not None:
        rendered = link_manager.render_macros(rendered, link_context)
    return BodyRenderResult(body=rendered, body_format=detect_body_format(rendered))


def render_spintax(template: str, random_source: random.Random | None = None) -> str:
    """Render nested spintax with arbitrary depth."""
    rng = random_source or random.SystemRandom()
    nodes, index, stop_char = _parse_spintax_sequence(template, 0, set())
    if index != len(template) or stop_char is not None:
        raise ContentError("Некорректный спинтакс")
    return _render_spintax_nodes(nodes, rng)


def detect_body_format(body: str) -> str:
    """Detect body format by presence of HTML tags."""
    return "html" if HTML_TAG_RE.search(body) else "plain"


def render_placeholders(
    template: str,
    recipient: RecipientContext | dict[str, str],
    sender_name: str = "",
) -> str:
    """Render supported placeholders in a content template."""
    context = _normalize_recipient(recipient)
    values = {
        "name": context.name,
        "email": context.email,
        "sendername": sender_name,
    }

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        return values.get(key, "")

    return PLACEHOLDER_RE.sub(replace, template)


def link_key_from_filename(filename: str) -> str:
    """Return macro key for links.txt, links1.txt, links2.txt, ..."""
    match = LINKS_FILENAME_RE.match(filename)
    if not match:
        raise ContentError("Файл ссылок должен называться links.txt, links1.txt, links2.txt и т.д.")
    return normalize_link_key(match.group(1))


def normalize_link_key(value: str) -> str:
    """Normalize empty key to base LINK and numeric keys to digits."""
    key = value.strip()
    if not key:
        return ""
    if not key.isdigit():
        raise ContentError(f"Некорректный номер LINK-макроса: {value}")
    return str(int(key))


def link_macro_name(key: str) -> str:
    """Return visible macro name for a link key."""
    normalized_key = normalize_link_key(key)
    return f"[[LINK{normalized_key}]]"


def link_filename(key: str) -> str:
    """Return expected filename for a link key."""
    normalized_key = normalize_link_key(key)
    return f"links{normalized_key}.txt"


def _link_sort_key(key: str) -> tuple[int, int]:
    if key == "":
        return (0, 0)
    return (1, int(key))


def _parse_spintax_sequence(
    text: str,
    index: int,
    stop_chars: set[str],
) -> tuple[tuple[_SpintaxNode, ...], int, str | None]:
    nodes: list[_SpintaxNode] = []
    buffer: list[str] = []

    while index < len(text):
        char = text[index]
        if char in stop_chars:
            _flush_text_node(nodes, buffer)
            return tuple(nodes), index, char

        if char == "{":
            _flush_text_node(nodes, buffer)
            node, index = _parse_spintax_choice_or_literal(text, index)
            nodes.append(node)
            continue

        buffer.append(char)
        index += 1

    _flush_text_node(nodes, buffer)
    return tuple(nodes), index, None


def _parse_spintax_choice_or_literal(text: str, start_index: int) -> tuple[_SpintaxNode, int]:
    options: list[tuple[_SpintaxNode, ...]] = []
    index = start_index + 1
    has_separator = False

    while True:
        nodes, index, stop_char = _parse_spintax_sequence(text, index, {"|", "}"})
        options.append(nodes)

        if stop_char == "|":
            has_separator = True
            index += 1
            continue

        if stop_char == "}":
            end_index = index + 1
            if not has_separator:
                return _TextNode(text[start_index:end_index]), end_index
            return _ChoiceNode(tuple(options)), end_index

        raise ContentError("Незакрытый спинтакс: отсутствует }")


def _render_spintax_nodes(nodes: tuple[_SpintaxNode, ...], rng: random.Random) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, _TextNode):
            parts.append(node.value)
        else:
            selected = rng.choice(node.options)
            parts.append(_render_spintax_nodes(selected, rng))
    return "".join(parts)


def _flush_text_node(nodes: list[_SpintaxNode], buffer: list[str]) -> None:
    if not buffer:
        return
    nodes.append(_TextNode("".join(buffer)))
    buffer.clear()


def _normalize_recipient(recipient: RecipientContext | dict[str, str]) -> RecipientContext:
    if isinstance(recipient, RecipientContext):
        return recipient

    email = str(recipient.get("email", "")).strip()
    name = str(recipient.get("name", "")).strip()
    return RecipientContext(email=email, name=name)

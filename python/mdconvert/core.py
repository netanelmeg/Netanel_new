"""Core conversion engine for mdconvert.

Defines the result/option types, an extension -> handler registry, the public
``convert_*`` entry points, and the shared Markdown helpers (table + cell
rendering). Format-specific handlers live in ``converters.py`` and register
themselves against this registry on import.

The engine has no third-party dependencies. Individual handlers may import an
optional library lazily (e.g. openpyxl for .xlsx); when one is missing they
raise :class:`ConversionError` with a "pip install ..." hint.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence, Union

__all__ = [
    "ConversionError",
    "ConvertOptions",
    "ConversionResult",
    "register",
    "convert_file",
    "convert_to_file",
    "supported_extensions",
    "is_supported",
    "to_markdown_table",
]


class ConversionError(Exception):
    """Raised when a file cannot be converted to Markdown."""


@dataclass
class ConvertOptions:
    """Tunable behaviour shared by every handler."""

    has_header: bool = True       # treat first CSV/TSV/sheet row as a header
    front_matter: bool = False    # prepend a YAML front-matter block
    page_breaks: bool = True      # emit "## Page N" / "## Slide N" separators


@dataclass
class ConversionResult:
    """The Markdown produced for one source file, plus any soft warnings."""

    source: Path
    markdown: str
    warnings: list[str] = field(default_factory=list)

    def write(self, dest: Union[str, Path]) -> Path:
        """Write the Markdown to ``dest`` (utf-8) and return the path."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.markdown, encoding="utf-8")
        return dest


# A handler takes the source path + options and returns either a Markdown
# string or a fully-formed ConversionResult.
Handler = Callable[[Path, ConvertOptions], Union[str, ConversionResult]]

_REGISTRY: dict[str, Handler] = {}
_DESCRIPTIONS: dict[str, str] = {}
_LOADED = False


def register(*extensions: str, description: str = "") -> Callable[[Handler], Handler]:
    """Decorator that maps one or more file extensions to a handler.

    Extensions are matched case-insensitively and must include the leading dot
    (e.g. ``".csv"``).
    """

    def decorator(func: Handler) -> Handler:
        for ext in extensions:
            key = ext.lower()
            _REGISTRY[key] = func
            _DESCRIPTIONS[key] = description
        return func

    return decorator


def _ensure_loaded() -> None:
    """Import the converters module once so handlers register themselves."""
    global _LOADED
    if not _LOADED:
        _LOADED = True
        from . import converters  # noqa: F401  (import side effect: registration)


def supported_extensions() -> dict[str, str]:
    """Return ``{extension: description}`` for every registered format."""
    _ensure_loaded()
    return dict(sorted(_DESCRIPTIONS.items()))


def is_supported(path: Union[str, Path]) -> bool:
    """True if ``path``'s extension has a dedicated handler."""
    _ensure_loaded()
    return Path(path).suffix.lower() in _REGISTRY


def convert_file(
    path: Union[str, Path], options: ConvertOptions | None = None
) -> ConversionResult:
    """Convert a single file to Markdown.

    Unknown extensions are handled forgivingly: the file is read as plain text
    and a warning is attached to the result.
    """
    _ensure_loaded()
    path = Path(path)
    options = options or ConvertOptions()

    if not path.exists():
        raise ConversionError(f"File not found: {path}")
    if not path.is_file():
        raise ConversionError(f"Not a file: {path}")

    suffix = path.suffix.lower()
    handler = _REGISTRY.get(suffix)
    extra_warnings: list[str] = []
    if handler is None:
        handler = _REGISTRY.get(".txt")
        extra_warnings.append(
            f"Unsupported extension '{suffix or '(none)'}'; converted as plain text."
        )
        if handler is None:  # pragma: no cover - .txt is always registered
            raise ConversionError(f"No handler for '{suffix}' and no text fallback.")

    try:
        raw = handler(path, options)
    except ConversionError:
        raise
    except Exception as exc:  # wrap unexpected handler failures
        raise ConversionError(f"Failed to convert {path.name}: {exc}") from exc

    if isinstance(raw, ConversionResult):
        result = raw
    else:
        result = ConversionResult(source=path, markdown=raw)

    result.warnings = extra_warnings + list(result.warnings)
    if not result.markdown.endswith("\n"):
        result.markdown += "\n"
    if options.front_matter:
        result.markdown = _front_matter(path) + result.markdown
    return result


def convert_to_file(
    source: Union[str, Path],
    dest: Union[str, Path, None] = None,
    options: ConvertOptions | None = None,
    overwrite: bool = True,
) -> Path:
    """Convert ``source`` and write the Markdown next to it (or to ``dest``).

    ``dest`` may be a file path or a directory; if a directory, the output is
    ``<dir>/<source-stem>.md``. Returns the path written.
    """
    source = Path(source)
    result = convert_file(source, options)

    if dest is None:
        dest = source.with_suffix(".md")
    dest = Path(dest)
    if dest.is_dir() or (not dest.suffix and not dest.exists()):
        dest = dest / (source.stem + ".md")

    if dest.resolve() == source.resolve():
        raise ConversionError(f"Refusing to overwrite the source file: {source}")
    if dest.exists() and not overwrite:
        raise ConversionError(f"Output already exists (use overwrite): {dest}")

    return result.write(dest)


def _front_matter(path: Path) -> str:
    """Build a small YAML front-matter block for ``path``."""

    def q(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    return (
        "---\n"
        f"title: {q(path.stem)}\n"
        f"source: {q(path.name)}\n"
        f"converted: {_dt.date.today().isoformat()}\n"
        "generator: mdconvert\n"
        "---\n\n"
    )


# --------------------------------------------------------------------------- #
# Shared Markdown helpers
# --------------------------------------------------------------------------- #

def _cell(value: object) -> str:
    """Render a single table cell, escaping characters that break tables."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    text = text.replace("|", "\\|")
    return text.strip()


def to_markdown_table(
    rows: Sequence[Sequence[object]],
    has_header: bool = True,
    max_pad: int = 60,
) -> str:
    """Render a row matrix as a GitHub-flavoured Markdown table.

    Columns are padded to a readable width (capped at ``max_pad``). Ragged rows
    are padded to the widest row; fully empty rows are dropped. When
    ``has_header`` is False a ``Column N`` header is synthesised.
    """
    norm = [[_cell(c) for c in row] for row in rows]
    norm = [r for r in norm if any(c != "" for c in r)]
    if not norm:
        return "*(no data)*\n"

    ncols = max(len(r) for r in norm)
    norm = [r + [""] * (ncols - len(r)) for r in norm]

    if has_header:
        header, body = norm[0], norm[1:]
    else:
        header = [f"Column {i + 1}" for i in range(ncols)]
        body = norm

    widths: list[int] = []
    for i in range(ncols):
        width = len(header[i])
        for row in body:
            width = max(width, len(row[i]))
        widths.append(min(max(width, 3), max_pad))

    def fmt(row: Sequence[str]) -> str:
        return "| " + " | ".join(row[i].ljust(widths[i]) for i in range(ncols)) + " |"

    lines = [
        fmt(header),
        "| " + " | ".join("-" * widths[i] for i in range(ncols)) + " |",
    ]
    lines.extend(fmt(row) for row in body)
    return "\n".join(lines) + "\n"

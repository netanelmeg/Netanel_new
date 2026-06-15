"""mdconvert — convert PDF, Excel, CSV, Word, PowerPoint, JSON, HTML and text
files to Markdown.

Public API::

    from mdconvert import convert_file, convert_to_file, ConvertOptions

    result = convert_file("report.pdf")
    print(result.markdown)

    convert_to_file("data.xlsx", "out/data.md")

The conversion engine has no required third-party dependencies. Office and PDF
formats import their backing library lazily; install the extras you need
(``openpyxl``, ``pdfplumber``, ``python-docx``, ``python-pptx``) — see
``requirements.txt``.
"""

from __future__ import annotations

from .core import (
    ConversionError,
    ConversionResult,
    ConvertOptions,
    convert_bytes,
    convert_file,
    convert_to_file,
    is_supported,
    supported_extensions,
)

__all__ = [
    "ConversionError",
    "ConversionResult",
    "ConvertOptions",
    "convert_bytes",
    "convert_file",
    "convert_to_file",
    "is_supported",
    "supported_extensions",
]

__version__ = "0.1.0"

"""Command-line interface for mdconvert.

Examples::

    # Convert one file, writing report.md next to it
    python -m mdconvert report.pdf

    # Convert several files into an output directory
    python -m mdconvert data.xlsx notes.docx -o build/

    # Recurse into a folder and convert every supported file
    python -m mdconvert ./inbox -r -o ./markdown

    # Print to stdout instead of writing a file
    python -m mdconvert report.pdf --stdout

    # List the formats this build can handle
    python -m mdconvert --list-formats
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .core import (
    ConversionError,
    ConvertOptions,
    convert_file,
    supported_extensions,
)


def _gather_inputs(inputs: list[str], recursive: bool) -> list[tuple[Path, Path]]:
    """Resolve CLI inputs to (source, relative-base) pairs.

    ``relative-base`` is the path used to compute the output filename, so that
    directory inputs can mirror their structure under an output directory.
    """
    supported = set(supported_extensions())
    pairs: list[tuple[Path, Path]] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            walker = path.rglob("*") if recursive else path.glob("*")
            for child in sorted(walker):
                if child.is_file() and child.suffix.lower() in supported:
                    pairs.append((child, child.relative_to(path)))
        elif path.is_file():
            pairs.append((path, Path(path.name)))
        else:
            print(f"warning: skipping missing path: {path}", file=sys.stderr)
    return pairs


def _output_path(rel: Path, output_dir: Path | None, source: Path) -> Path:
    if output_dir is None:
        return source.with_suffix(".md")
    return output_dir / rel.with_suffix(".md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdconvert",
        description="Convert PDF, Excel, CSV, Word, PowerPoint, JSON, HTML and text files to Markdown.",
    )
    parser.add_argument("inputs", nargs="*", help="Files and/or directories to convert.")
    parser.add_argument("-o", "--output-dir", help="Write .md files into this directory.")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Recurse into input directories.")
    parser.add_argument("--stdout", action="store_true",
                        help="Print Markdown to stdout instead of writing files.")
    parser.add_argument("--no-header", action="store_true",
                        help="Treat the first CSV/TSV/sheet row as data, not a header.")
    parser.add_argument("--front-matter", action="store_true",
                        help="Prepend a YAML front-matter block to each output.")
    parser.add_argument("--no-page-breaks", action="store_true",
                        help="Omit '## Page N' / '## Slide N' separators.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing .md files (default: skip them).")
    parser.add_argument("--list-formats", action="store_true",
                        help="List supported file extensions and exit.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only print errors.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_formats:
        print("Supported formats:")
        for ext, desc in supported_extensions().items():
            print(f"  {ext:<11} {desc}")
        return 0

    if not args.inputs:
        build_parser().print_usage(sys.stderr)
        print("mdconvert: error: no input files (use --list-formats to see what's supported)",
              file=sys.stderr)
        return 2

    options = ConvertOptions(
        has_header=not args.no_header,
        front_matter=args.front_matter,
        page_breaks=not args.no_page_breaks,
    )
    output_dir = Path(args.output_dir) if args.output_dir else None

    pairs = _gather_inputs(args.inputs, args.recursive)
    if not pairs:
        print("mdconvert: no supported files found.", file=sys.stderr)
        return 2

    failures = 0
    for source, rel in pairs:
        try:
            result = convert_file(source, options)
        except ConversionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
            continue

        for warning in result.warnings:
            if not args.quiet:
                print(f"note: {source.name}: {warning}", file=sys.stderr)

        if args.stdout:
            sys.stdout.write(result.markdown)
            if not result.markdown.endswith("\n"):
                sys.stdout.write("\n")
            continue

        dest = _output_path(rel, output_dir, source)
        if dest.exists() and not args.overwrite:
            if not args.quiet:
                print(f"skip: {dest} already exists (use --overwrite)", file=sys.stderr)
            continue
        try:
            result.write(dest)
        except OSError as exc:
            print(f"error: could not write {dest}: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not args.quiet:
            print(f"ok: {source}  ->  {dest}")

    return 1 if failures else 0


def run(argv: list[str] | None = None) -> int:
    """Entry point wrapper that exits cleanly when output is piped to a reader
    that closes early (e.g. ``mdconvert ... | head``)."""
    try:
        return main(argv)
    except BrokenPipeError:
        # Redirect stdout to devnull so the interpreter's final flush is silent.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(run())

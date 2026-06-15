"""Unit tests for the mdconvert engine and its stdlib-only converters.

These tests exercise everything that does not need a third-party library
(text, CSV/TSV, JSON, HTML, dispatch, options, the CLI). Office/PDF handlers
are covered only at the "missing dependency raises a helpful error" level.

Run from the ``python/`` directory:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mdconvert
from mdconvert import cli
from mdconvert.core import ConversionError, ConvertOptions, to_markdown_table


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path


class TableHelperTests(unittest.TestCase):
    def test_basic_table_with_header(self):
        md = to_markdown_table([["a", "b"], ["1", "2"]])
        lines = md.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("| a"))
        self.assertRegex(lines[1], r"^\| -+ \| -+ \|$")
        self.assertIn("1", lines[2])

    def test_escapes_pipes_and_newlines(self):
        md = to_markdown_table([["h"], ["a|b\nc"]])
        self.assertIn(r"a\|b<br>c", md)

    def test_ragged_rows_are_padded(self):
        md = to_markdown_table([["a", "b", "c"], ["1"]], has_header=True)
        # The single-value data row gets padded to 3 columns.
        self.assertEqual(md.strip().splitlines()[2].count("|"), 4)

    def test_synthesised_header(self):
        md = to_markdown_table([["1", "2"]], has_header=False)
        self.assertIn("Column 1", md)
        self.assertIn("Column 2", md)

    def test_empty_returns_placeholder(self):
        self.assertEqual(to_markdown_table([]), "*(no data)*\n")


class TextTests(TempDirTest):
    def test_txt_passthrough(self):
        path = self.write("note.txt", "hello\r\nworld\r\n")
        result = mdconvert.convert_file(path)
        self.assertEqual(result.markdown, "hello\nworld\n")

    def test_markdown_passthrough(self):
        path = self.write("doc.md", "# Title\n\nbody")
        result = mdconvert.convert_file(path)
        self.assertEqual(result.markdown, "# Title\n\nbody\n")


class CsvTsvTests(TempDirTest):
    def test_csv_to_table(self):
        path = self.write("data.csv", "name,age\nAlice,30\nBob,25\n")
        md = mdconvert.convert_file(path).markdown
        self.assertIn("| name", md)
        self.assertIn("Alice", md)
        self.assertIn("Bob", md)
        # header + separator + 2 rows
        self.assertEqual(len(md.strip().splitlines()), 4)

    def test_csv_semicolon_sniffed(self):
        path = self.write("data.csv", "a;b;c\n1;2;3\n")
        md = mdconvert.convert_file(path).markdown
        self.assertIn("| a", md)
        self.assertIn("| 1", md)

    def test_csv_no_header_option(self):
        path = self.write("data.csv", "1,2\n3,4\n")
        md = mdconvert.convert_file(path, ConvertOptions(has_header=False)).markdown
        self.assertIn("Column 1", md)

    def test_tsv(self):
        path = self.write("data.tsv", "a\tb\n1\t2\n")
        md = mdconvert.convert_file(path).markdown
        self.assertIn("| a", md)
        self.assertIn("| 1", md)


class JsonTests(TempDirTest):
    def test_list_of_dicts_becomes_table(self):
        path = self.write("data.json", json.dumps([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25, "city": "NYC"},
        ]))
        md = mdconvert.convert_file(path).markdown
        self.assertIn("| name", md)
        self.assertIn("| city", md)   # union of keys
        self.assertIn("Alice", md)

    def test_object_becomes_code_block(self):
        path = self.write("data.json", json.dumps({"a": 1, "b": [1, 2]}))
        md = mdconvert.convert_file(path).markdown
        self.assertIn("```json", md)
        self.assertIn('"a": 1', md)

    def test_invalid_json_raises(self):
        path = self.write("bad.json", "{not valid}")
        with self.assertRaises(ConversionError):
            mdconvert.convert_file(path)


class HtmlTests(TempDirTest):
    def test_headings_and_emphasis(self):
        html = "<h1>Title</h1><p>Hello <strong>bold</strong> and <em>italic</em>.</p>"
        path = self.write("page.html", html)
        md = mdconvert.convert_file(path).markdown
        self.assertIn("# Title", md)
        self.assertIn("**bold**", md)
        self.assertIn("*italic*", md)

    def test_links_and_lists(self):
        html = '<ul><li>one</li><li><a href="http://x.com">two</a></li></ul>'
        path = self.write("page.html", html)
        md = mdconvert.convert_file(path).markdown
        self.assertIn("- one", md)
        self.assertIn("[two](http://x.com)", md)

    def test_script_and_style_dropped(self):
        html = "<style>.x{color:red}</style><p>kept</p><script>alert(1)</script>"
        path = self.write("page.html", html)
        md = mdconvert.convert_file(path).markdown
        self.assertIn("kept", md)
        self.assertNotIn("alert", md)
        self.assertNotIn("color:red", md)


class DispatchTests(TempDirTest):
    def test_unknown_extension_falls_back_to_text(self):
        path = self.write("weird.xyz", "just text")
        result = mdconvert.convert_file(path)
        self.assertEqual(result.markdown, "just text\n")
        self.assertTrue(any("Unsupported extension" in w for w in result.warnings))

    def test_missing_file_raises(self):
        with self.assertRaises(ConversionError):
            mdconvert.convert_file(self.tmp / "nope.txt")

    def test_front_matter_prepended(self):
        path = self.write("note.txt", "body")
        md = mdconvert.convert_file(path, ConvertOptions(front_matter=True)).markdown
        self.assertTrue(md.startswith("---\n"))
        self.assertIn('title: "note"', md)
        self.assertIn("body", md)

    def test_supported_extensions_includes_core_formats(self):
        exts = mdconvert.supported_extensions()
        for ext in (".txt", ".csv", ".tsv", ".json", ".html", ".pdf", ".xlsx", ".docx", ".pptx"):
            self.assertIn(ext, exts)

    def test_convert_to_file_writes_md(self):
        path = self.write("data.csv", "a,b\n1,2\n")
        dest = mdconvert.convert_to_file(path, self.tmp / "out")
        self.assertTrue(dest.exists())
        self.assertEqual(dest.name, "data.md")
        self.assertIn("| a", dest.read_text(encoding="utf-8"))

    def test_convert_to_file_refuses_source_overwrite(self):
        path = self.write("a.md", "# hi")
        with self.assertRaises(ConversionError):
            mdconvert.convert_to_file(path, path)


class OptionalDependencyTests(TempDirTest):
    """When an office/PDF library is absent, conversion fails clearly."""

    def _maybe(self, module: str, filename: str):
        import importlib.util
        if importlib.util.find_spec(module) is not None:
            self.skipTest(f"{module} is installed; skipping missing-dependency check")
        path = self.tmp / filename
        path.write_bytes(b"not a real office file")
        with self.assertRaises(ConversionError) as ctx:
            mdconvert.convert_file(path)
        self.assertIn("pip install", str(ctx.exception))

    def test_xlsx_without_openpyxl(self):
        self._maybe("openpyxl", "book.xlsx")

    def test_docx_without_python_docx(self):
        self._maybe("docx", "doc.docx")

    def test_pptx_without_python_pptx(self):
        self._maybe("pptx", "deck.pptx")


class ConvertBytesTests(unittest.TestCase):
    def test_csv_bytes(self):
        result = mdconvert.convert_bytes("data.csv", b"a,b\n1,2\n")
        self.assertIn("| a", result.markdown)
        self.assertEqual(result.source.name, "data.csv")

    def test_extension_drives_handler(self):
        # Same bytes, but the .json extension routes to the JSON handler.
        result = mdconvert.convert_bytes("x.json", b'{"a": 1}')
        self.assertIn("```json", result.markdown)

    def test_front_matter_uses_real_name(self):
        result = mdconvert.convert_bytes(
            "Report.txt", b"hi", ConvertOptions(front_matter=True)
        )
        self.assertIn('title: "Report"', result.markdown)


class BotModuleTests(unittest.TestCase):
    """The bot module must import without python-telegram-bot installed."""

    def test_import_and_metadata(self):
        from mdconvert import bot
        self.assertIn(".pdf", bot.WELCOME)  # welcome text lists supported formats
        self.assertTrue(callable(bot.main))
        self.assertTrue(callable(bot.on_document))

    def test_main_without_token_returns_2(self):
        import os
        from mdconvert import bot
        saved = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        try:
            self.assertEqual(bot.main(), 2)
        finally:
            if saved is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = saved

    def test_build_application_without_library_raises(self):
        import importlib.util
        if importlib.util.find_spec("telegram") is not None:
            self.skipTest("python-telegram-bot is installed")
        from mdconvert import bot
        with self.assertRaises(SystemExit):
            bot.build_application("dummy-token")


class CliTests(TempDirTest):
    def test_cli_converts_files(self):
        self.write("a.csv", "x,y\n1,2\n")
        self.write("b.txt", "hello")
        outdir = self.tmp / "out"
        rc = cli.main([str(self.tmp / "a.csv"), str(self.tmp / "b.txt"), "-o", str(outdir)])
        self.assertEqual(rc, 0)
        self.assertTrue((outdir / "a.md").exists())
        self.assertTrue((outdir / "b.md").exists())

    def test_cli_recursive_directory(self):
        sub = self.tmp / "src" / "nested"
        sub.mkdir(parents=True)
        (sub / "deep.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        outdir = self.tmp / "out"
        rc = cli.main([str(self.tmp / "src"), "-r", "-o", str(outdir)])
        self.assertEqual(rc, 0)
        self.assertTrue((outdir / "nested" / "deep.md").exists())

    def test_cli_no_inputs_returns_2(self):
        self.assertEqual(cli.main([]), 2)

    def test_cli_list_formats(self):
        self.assertEqual(cli.main(["--list-formats"]), 0)

    def test_cli_skips_existing_without_overwrite(self):
        self.write("a.txt", "hello")
        outdir = self.tmp / "out"
        self.assertEqual(cli.main([str(self.tmp / "a.txt"), "-o", str(outdir)]), 0)
        # Second run should skip (still rc 0, file unchanged).
        (outdir / "a.md").write_text("EDITED\n", encoding="utf-8")
        self.assertEqual(cli.main([str(self.tmp / "a.txt"), "-o", str(outdir)]), 0)
        self.assertEqual((outdir / "a.md").read_text(encoding="utf-8"), "EDITED\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)

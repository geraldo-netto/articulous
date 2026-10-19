"""REV-087/REV-089: empty archives and actual UTF-8 accounting."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from articulous import output_metrics as report

REGIONS = (("header", "//header"),)


class SizeReport(unittest.TestCase):
    def test_rev087_empty_missing_and_zero_byte_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (root / "missing", root):
                with redirect_stdout(io.StringIO()) as output:
                    report.overall(report.scan(directory))
                    report.class_weight(report.scan(directory))
                    report.repeated_markup(report.scan(directory))
                self.assertIn("0 pages", output.getvalue())
            (root / "asset.bin").write_bytes(b"asset")
            (root / "empty.html").write_bytes(b"")
            with redirect_stdout(io.StringIO()) as output:
                report.overall(report.scan(root, regions=REGIONS))
                report.class_weight(report.scan(root, regions=REGIONS))
                report.repeated_markup(report.scan(root, regions=REGIONS))
                report.one_page(root / "empty.html")
            self.assertIn("1 pages", output.getvalue())
            (root / "real.html").write_text(
                '<html><body class="long ' + "x" * 50 + '">Text</body></html>'
            )
            with redirect_stdout(io.StringIO()) as output:
                report.overall(report.scan(root, regions=REGIONS))
                report.class_weight(report.scan(root, regions=REGIONS))
                report.repeated_markup(report.scan(root, regions=REGIONS))
                report.one_page(root / "real.html")
            self.assertIn("2 pages", output.getvalue())
            self.assertIn("longest recipes", output.getvalue())

    def test_rev089_utf8_regions_and_classes_count_bytes(self):
        from unittest.mock import patch
        from lxml import html

        for text in ("ASCII", "ação", "日本語", "🌍"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / "index.html"
                markup = f'<html><head><meta charset="utf-8"></head><body><header class="{text * 50}">{text * 100}</header></body></html>'
                path.write_text(markup, encoding="utf-8")
                tree = html.fromstring(markup)
                header = tree.xpath("//header")[0]
                size = len(html.tostring(header, encoding="utf-8"))
                with (
                    patch.object(
                        report, "megabytes", side_effect=lambda n: f"{n} bytes"
                    ),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    report.repeated_markup(report.scan(root, regions=REGIONS))
                    report.class_weight(report.scan(root, regions=REGIONS))
                self.assertIn(str(size) + " bytes", output.getvalue())
                self.assertIn(
                    str(len((text * 50).encode())) + " bytes", output.getvalue()
                )
                self.assertIn(f"{len((text * 50).encode()):4}b", output.getvalue())
                with redirect_stdout(io.StringIO()) as output:
                    report.one_page(path, regions=REGIONS)
                self.assertIn(f"{size / 1024:7.1f} KB", output.getvalue())


class MetricsBoundaryTests(unittest.TestCase):
    def test_obs001_machine_readable_metrics_and_single_parse(self):
        import json
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "folder").mkdir()
            page = root / "index.html"
            page.write_text(
                '<html><body class="short"><header>ação</header><p>unclosed'
            )
            with patch.object(
                report.html, "fromstring", wraps=report.html.fromstring
            ) as parse:
                metrics = report.scan(root, regions=REGIONS)
            self.assertEqual(1, parse.call_count)
            self.assertEqual(len(page.read_bytes()), metrics["raw"])
            self.assertEqual(5, metrics["class_bytes"])
            with redirect_stdout(io.StringIO()):
                report.one_page(page, regions=(("missing", "//missing"),))
            self.assertEqual(metrics["raw"], json.loads(json.dumps(metrics))["raw"])

    def test_obs001_invalid_selectors_cannot_modify_artifacts(self):
        import lxml.etree as etree

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "index.html"
            page.write_text("<html><body>keep</body></html>")
            before = page.read_bytes()
            with self.assertRaises(etree.XPathEvalError):
                report.scan(root, regions=(("invalid", "["),))
            self.assertEqual(before, page.read_bytes())

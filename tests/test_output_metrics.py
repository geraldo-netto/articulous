"""REV-087/REV-089: empty archives and actual UTF-8 accounting."""

from contextlib import redirect_stdout
import gzip
import io
from pathlib import Path
import tempfile
import unittest

import pytest
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


def test_review29_08_region_bytes_exclude_following_body_text(tmp_path, capsys):
    path = tmp_path / 'page.html'
    selected = '<header>日<em>🌍</em>é</header>'
    tail = 'outside' * 1024
    path.write_text(f'<html><head><meta charset="utf-8"></head><body>{selected}{tail}</body></html>')
    size = len(selected.encode('utf-8'))
    assert report.scan(tmp_path, regions=REGIONS)['regions']['header'] == size
    report.one_page(path, regions=REGIONS)
    assert f'{size / 1024:7.1f} KB' in capsys.readouterr().out.splitlines()[-1]


@pytest.mark.parametrize('raw', [b'<!--comment-->', b'<!doctype html>', b'<?editor value?>'])
def test_review28_42_element_free_pages_count_all_bytes(tmp_path, raw):
    empty = tmp_path / 'a.html'
    empty.write_bytes(raw)
    markup = b'<header class="used">ok</header>'
    (tmp_path / 'b.html').write_bytes(markup)
    metrics = report.scan(tmp_path, regions=REGIONS)
    assert sorted(metrics['sizes']) == sorted([len(raw), len(markup)])
    assert metrics['raw'] == len(raw) + len(markup)
    assert metrics['gzip'] == len(gzip.compress(raw, 6)) + len(gzip.compress(markup, 6))
    assert metrics['region_pages'] == {'header': 1}
    assert metrics['class_bytes'] == 4


@pytest.mark.parametrize('raw', [b'<!--comment-->', b'<!doctype html>', b'<?editor value?>'])
def test_review28_42_one_element_free_page_reports_size(tmp_path, raw, capsys):
    page = tmp_path / 'one.html'
    page.write_bytes(raw)
    report.one_page(page, regions=REGIONS)
    assert capsys.readouterr().out.splitlines() == [
        f'{page}: {len(raw)/1024:.0f} KB raw, {len(gzip.compress(raw, 6))/1024:.0f} KB estimated gzip',
    ]

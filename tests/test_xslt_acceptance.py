"""CC-004: every packaged template stays within the calibrated metric limit."""
from pathlib import Path

from articulous.complexity_xpath import compile_xpath
from articulous import complexity_xslt


def test_cc004_packaged_template_complexity():
    root = Path(__file__).resolve().parents[1]
    report = complexity_xslt.measured_report(root, compile_xpath)
    assert complexity_xslt.check_report(root, report) > 0

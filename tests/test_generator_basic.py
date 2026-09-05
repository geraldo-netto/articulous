"""Subprocess-driven smoke test of the full build pipeline."""


def test_full_build_via_cli(site_root, run_sitegen):
    run_sitegen(["--force", "--verbose"])
    assert (site_root / "output").is_dir()


def test_required_output_files(site_root, run_sitegen):
    run_sitegen(["--force"])
    required = [
        site_root / "output" / "rss.xml",
        site_root / "output" / "sitemap.xml",
        site_root / "output" / "search.json",
        site_root / "output" / "en" / "articles" / "first-post" / "index.html",
        site_root / "output" / "en" / "articles" / "second-post" / "index.html",
        site_root / "output" / "fr" / "articles" / "premier-article" / "index.html",
        site_root / "output" / "assets" / "style.css",
    ]
    missing = [p for p in required if not p.exists()]
    assert not missing, f"Missing required output files: {missing}"


def test_dry_run_creates_nothing_meaningful(site_root, run_sitegen):
    run_sitegen(["--dry-run", "--force"])
    assert not (site_root / "output" / "rss.xml").exists()
    assert not (site_root / "output" / "search.json").exists()

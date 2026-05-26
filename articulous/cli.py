"""
Command-line parsing, CLI option container, and the top-level entry
point that wires every other module together.
"""
import argparse
import logging
import sys
from pathlib import Path

from .config import apply_cli_overrides, load_or_create_config
from .engines import check_dependencies


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def parse_cli_args(argv=None):
    """Parse command-line arguments for the static site generator."""
    parser = argparse.ArgumentParser(
        description="Static Site Generator — XML + XSLT pipeline"
    )
    parser.add_argument(
        "--config", type=str, default="config.json",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--only", type=str, default=None,
        help="Comma-separated list of sections to build "
             "(articles,index,tags,rss,sitemap,search)",
    )
    parser.add_argument(
        "--lang", action="append",
        help="Limit build to specific languages (can repeat)",
    )
    parser.add_argument(
        "--slug", action="append",
        help="Limit build to specific article slugs (can repeat)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run without writing output files",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force full rebuild, ignoring cache",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)


class CliOptions:
    """
    Wrapper around parsed CLI arguments.
    Normalizes lists and comma-separated values.
    """

    def __init__(self, args):
        self.config_path = Path(args.config)
        if args.only:
            self.only_sections = [s.strip() for s in args.only.split(",") if s.strip()]
        else:
            self.only_sections = None
        self.only_langs = args.lang if args.lang else None
        self.only_slugs = args.slug if args.slug else None
        self.dry_run = args.dry_run
        self.force_full_build = args.force
        self.verbose = args.verbose


def _resolve_log_level(level_name: str) -> int:
    name = (level_name or "INFO").upper()
    if name not in _VALID_LOG_LEVELS:
        name = "INFO"
    return getattr(logging, name)


def setup_logging(config, project_root: Path, verbose: bool = False):
    """Configure logging idempotently. Safe to call multiple times."""
    level = (
        logging.DEBUG if verbose
        else _resolve_log_level(config["logging"]["level"])
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(stream)

    log_file = config["logging"].get("file")
    if log_file:
        file_path = project_root / log_file
        fh = logging.FileHandler(file_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(fh)

    logging.debug("Logging initialized")


def main(argv=None) -> None:
    """Top-level entrypoint used by sitegen.py and python -m articulous."""
    from .pipeline import run_build

    args = parse_cli_args(argv)
    cli = CliOptions(args)
    project_root = Path.cwd()

    config = load_or_create_config(cli.config_path)
    apply_cli_overrides(config, cli, project_root)
    setup_logging(config, project_root, verbose=cli.verbose)
    check_dependencies(config, project_root)
    run_build(cli, config, project_root)

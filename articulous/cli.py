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
from .pipeline import run_build
from .sections import SECTION_HELP, SECTION_NAMES


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
        help=f"Comma-separated list of sections to build ({SECTION_HELP})",
    )
    parser.add_argument(
        "--lang", action="append",
        help="Limit article/listing languages; global feeds stay complete (can repeat)",
    )
    parser.add_argument(
        "--slug", action="append",
        help="Limit article slugs; shared listings/feeds stay complete (can repeat)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan without publishing outputs or saving the build cache",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild selected outputs and assets, ignoring fingerprints",
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
        self.only_sections = _parse_only_sections(args.only)
        self.only_langs = args.lang if args.lang else None
        self.only_slugs = args.slug if args.slug else None
        self.dry_run = args.dry_run
        self.force_full_build = args.force
        self.verbose = args.verbose


def _parse_only_sections(raw):
    """
    Split a comma-separated ``--only`` value and validate every name
    against the known section set. Unknown names previously fell through
    silently (the dispatcher just skipped them), turning a typo into a
    no-op build with no diagnostic.
    """
    if not raw:
        return None
    sections = [s.strip() for s in raw.split(",") if s.strip()]
    if not sections:
        return None
    invalid = [s for s in sections if s not in SECTION_NAMES]
    if invalid:
        raise ValueError(
            f"Unknown section(s) in --only: {invalid}. "
            f"Valid sections: {sorted(SECTION_NAMES)}"
        )
    return sections


def _resolve_log_level(level_name: str) -> int:
    name = (level_name or "INFO").upper()
    if name not in _VALID_LOG_LEVELS:
        name = "INFO"
    return getattr(logging, name)


def _resolve_log_file(project_root: Path, log_file: str) -> Path:
    root = project_root.resolve()
    resolved = (project_root / log_file).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"logging.file={log_file!r} resolves outside project root: "
            f"{resolved} (project_root={root})"
        )
    return resolved


def setup_logging(config, project_root: Path, verbose: bool = False):
    """Configure logging idempotently. Safe to call multiple times."""
    level = (
        logging.DEBUG if verbose
        else _resolve_log_level(config["logging"]["level"])
    )
    log_file = config["logging"].get("file")
    file_path = _resolve_log_file(project_root, log_file) if log_file else None

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(stream)

    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(file_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(fh)

    logging.debug("Logging initialized")


def main(argv=None) -> None:
    """Top-level entrypoint used by sitegen.py and python -m articulous."""
    args = parse_cli_args(argv)
    cli = CliOptions(args)
    project_root = Path.cwd()

    config = load_or_create_config(cli.config_path)
    apply_cli_overrides(config, cli, project_root)
    setup_logging(config, project_root, verbose=cli.verbose)
    check_dependencies(config, project_root)
    run_build(cli, config, project_root)

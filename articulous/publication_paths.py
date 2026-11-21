"""Shared filesystem admission for the reserved publication transaction tree."""
from pathlib import Path


def transaction_path(destination: Path) -> Path:
    return destination.parent / f'.{destination.name}.articulous-transaction'


def retirement_path(transaction: Path) -> Path:
    return transaction.with_name(transaction.name + '-retired')


def _require_disjoint(left: Path, right: Path) -> None:
    if left.is_relative_to(right) or right.is_relative_to(left):
        raise ValueError(f'State/source path overlaps publication transaction: {left}')


def validate_publication_paths(destination: Path, paths) -> None:
    transaction = transaction_path(destination)
    for path in paths:
        for reserved in (transaction, retirement_path(transaction)):
            _require_disjoint(path.absolute(), reserved.absolute())
            _require_disjoint(path.resolve(), reserved.resolve())

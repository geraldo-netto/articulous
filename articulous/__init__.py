"""
articulous — XML + XSLT static site generator.

Command-line entry point is :func:`main`, which the top-level ``sitegen.py``
script and ``python -m articulous`` both invoke.
"""
from .cli import main

__all__ = ["main"]

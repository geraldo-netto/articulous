#!/usr/bin/env python3
"""
Thin executable shim. The implementation lives in the
:mod:`articulous` package; this file exists so that
``./sitegen.py [args]`` keeps working as the legacy entry point.
"""
from articulous import main

if __name__ == "__main__":
    main()

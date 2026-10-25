# Development and verification

[Documentation](../README.md#documentation)

Run these commands from the repository root with the intended Python
environment activated. Installation commands can use the network; offline checks
reuse tools that are already installed.

## Acceptance checks

The [review-fix verification record](../reviews/correctness/README.md) links the
recent correctness fixes to their permanent regressions and states the tested
resource-ownership limits.

The [composition and publication guide](generator-composition.md) documents
implemented route, page, validation and publication APIs and their regression
coverage. Remaining decisions and declined work are tracked in [TODO.md](../TODO.md).

The package is covered by a pytest suite with fixture‑based site builds,
unit tests, and section‑order fuzz tests. Rendered fixture feeds are checked
for required RSS channel metadata, namespaced sitemap structure with both
native and lxml backends, and links to generated HTML pages. The RSS fixture
uses the test site's English first index page as its channel website.
Coverage is enforced at
**100 % line + branch** via `pytest-cov` (`--cov-fail-under=100`).
The subsequent native per-function gate independently inventories source, rejects
stale or inconsistent counters, and requires at least 80% executable lines for
each function. Empty protocol declarations must have genuinely empty native
regions; executable functions cannot substitute empty counters.

Seeded fuzz tests mutate configuration types and URL syntax, duplicate XML
metadata, and out-of-range dates. Boundary probes cover numeric minima,
platform-sized integers, URL lengths, ports, sitemap resource budgets, and
the target filesystem's byte limits. Valid boundary cases prevent excessive
rejection; failing builds must preserve published outputs and cache state.
Seeds are fixed for reproducibility.

## Run the checks

The tests use lxml for XML validation; `xmllint` is not required. Native JavaScript
tests require Node 24 and an installed Chromium executable. The browser test uses
`ARTICULOUS_CHROMIUM`, or finds `chromium`/`google-chrome` on PATH; missing native
tools fail acceptance. In an activated virtual environment, install the test
extra and run:

```sh
python -m pip install -e ".[test]"
python -m pytest
python -m articulous.coverage_gate coverage.json --directory articulous
ruff check --no-cache .
ruff check --no-cache --select C901 --config 'lint.mccabe.max-complexity = 9' articulous tests
PYRIGHT_PYTHON_IGNORE_WARNINGS=1 pyright --pythonpath .venv/bin/python
```

CI runs only on manual dispatch. In GitHub Actions, select
**Test Articulous Generator** and choose **Run workflow**.

## Offline tools

For offline checks, reuse installed dependencies and skip installation commands.
`PYRIGHT_PYTHON_IGNORE_WARNINGS=1` disables the Python launcher's registry query
for update warnings; use its already installed bundled engine. Do not request
`latest` or install missing tools on a metered connection without authorization.
The native JavaScript coverage gate uses the installed Acorn 8.17.0 parser.
Set `ARTICULOUS_ACORN` to its package directory when it is outside the normal
Node lookup path, for example the existing local cache:

```sh
export ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn
export ARTICULOUS_CHROMIUM=/home/netto/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell
```

`tests/test_code_browser.py` runs the maintained code adapter and copy plugin in
native Chromium against a loopback fixture. It checks DOM/controller lifetimes,
clipboard failures and stale callbacks, and requires >=80% native executable-line
coverage for every function. Clipboard calls use controlled promises; the test
does not write to the system clipboard. See the [recorded browser evidence](../reviews/browser/README.md).
The test never downloads a browser; manual CI uses its runner's installed Chrome.

`package-lock.json` pins that verification dependency for manual CI runs.
The parser and test commands never install it automatically; CI's explicit
`npm ci --ignore-scripts --no-audit --no-fund` step requires network access unless
its dependency is already cached. No local installation is needed to reuse the
cache above.

## Installed distribution acceptance

`tests/test_distributions.py` builds a wheel and an sdist, rebuilds the wheel from
the sdist, and installs each wheel outside the checkout. It verifies the complete
package byte inventory, tooling/theme resources, declarations and provenance,
both console commands, and a multilingual fixture build through the console and
module entry points. A deliberately missing-resource control checks the oracle.

The test extra includes setuptools, wheel and pip. Builds use their installed
PEP 517 backend directly; installation uses `--no-index --no-deps` in disposable
virtual environments. The already installed lxml package and its metadata are
copied into those environments, without downloading dependencies. Set
`ARTICULOUS_BUILD_PYTHON` to another installed interpreter with setuptools >=68,
wheel and pip >=24 when the test interpreter lacks those tools. For example:

```sh
ARTICULOUS_BUILD_PYTHON=/usr/bin/python3 python -m pytest --no-cov tests/test_distributions.py
```

Native commands use the owned-session runner without a total runtime cap.
Commands settle before their borrowed source, artifact or environment paths may
be released. Pytest owns the finite temporary source copies, distributions and
virtual environments through test/fixture retirement and its temporary-directory
retention policy. These Linux checks do not establish native Windows/macOS support.

## Locked dependencies and complexity

CI installs the versions in `uv.lock` with
`uv sync --locked --extra test --no-build --no-install-project` for each
Python version. To use those locked dependencies locally, run that
command with `--python 3.11` (or another CI version), then use the tools
in `.venv/bin/`. The CI job runs Ruff, Pyright and pytest; the separate
`C901` command above provides a supplementary complexity check. Every new or
changed function requires cyclomatic complexity <=9 without exemptions, measured
by SonarQube or an equivalent installed local analyzer. Record analyzer/version,
counting conventions, supported syntax and per-function results; validate analyzer
gaps rather than treating missing results as passes. Unsupported syntax fails
acceptance rather than receiving an estimated or missing score.
The [offline complexity workflow](../reviews/complexity/README.md) records calibrated
Lizard/ESLint and native XPath/XSLT measurements in one source-bound report.
`python -m articulous.complexity_gate check` validates every language component
without downloads; CI enforces this aggregate check.

## Native Saxon acceptance

A separate Linux integration job downloads the
[SaxonC-HE 12.10 executable](https://downloads.saxonica.com/SaxonC/HE/12/index.html),
verifies its pinned SHA-256 checksum, and runs all six sections with the real
backend. It also checks cache reuse, blocked file/HTTP reads and external
entities, disabled XInclude expansion and secondary writes, and preservation
of previous output when compilation or execution fails. The ordinary suite
keeps fast mocked subprocess tests and skips these integration checks unless
`ARTICULOUS_SAXONC_HOME` is set. A configured but unavailable executable fails
the integration checks rather than falling back to lxml.

To reproduce with the extracted Linux 12.10 archive:

```sh
saxonc_root=/path/to/SaxonCHE-linux-x86_64-12-10-0
ARTICULOUS_SAXONC_HOME="$saxonc_root/SaxonCHE" \
LD_LIBRARY_PATH="$saxonc_root/SaxonCCoreHE/lib:$saxonc_root/SaxonCHE/lib" \
.venv/bin/pytest --no-cov tests/test_saxonc_integration.py
```

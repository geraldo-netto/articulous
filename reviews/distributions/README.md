# Installed distribution acceptance — REVIEW-023

`tests/test_distributions.py` permanently builds a wheel and an sdist, rebuilds
the wheel from that sdist, and installs both wheels outside the checkout. Exact
package-byte inventories independently cover all production modules and packaged
resources, including declarations, tooling modules, XSLT, Prism provenance and
its maintained patch. An intentionally missing declaration must fail acceptance.
The isolated installed interpreter also invokes all three resource APIs and
validates the provenance hashes. No article/post code or Prism grammar is executed.

Both console entry points resolve from each disposable environment. The generator
builds the multilingual fixture through its installed console command and then
through `python -I -m articulous --force`. Assertions cover English/French article
routes, asset bytes and native search output. The probe asserts that imports live
under the disposable interpreter's prefix; neither PYTHONPATH nor pytest's source
path supplies the installed package.

Local verification uses Python 3.11.15, lxml 6.1.1 and the existing system Python
3.12 build tools: setuptools 68.1.2, wheel 0.42.0 and pip 24.0. No tool is installed
or downloaded. `ARTICULOUS_BUILD_PYTHON=/usr/bin/python3` selects those tools.
The test extra and offline-updated lock declare build/installation dependencies
for ordinary suite and manual CI execution; those locked versions are separate
from this local tool-version observation.

All three acceptance cases pass. Ruff and offline Pyright pass. The calibrated
Lizard 1.23.0 inventory measures all 14 new test/probe functions individually at
complexity 1–4, using the conventions and syntax checks in
[the complexity workflow](../complexity/README.md). Source identities and exact
per-function values are retained in `../complexity/functions.json`.
No production behavior changed and no packaging defect was found.

Full acceptance passed 2,997 tests and 359 subtests with 100% executable-line and
branch coverage; all 953 production functions passed the individual >=80% line
gate. The source-bound aggregate accepted 2,826 functions and 14 XSLT templates.
Cached Chromium and pinned SaxonC-HE 12.10 remained enabled during that run.

## Ownership and limits

Pytest owns the finite copied source, generated archives, fixture site and virtual
environments through fixture/test retirement and its temporary-directory retention
policy. The lxml package and metadata are copied from the already installed runtime
dependency; the test does not resolve or download dependencies. PEP 517 backend
hooks execute directly from installed tooling; pip uses `--no-index --no-deps`.

Every command runs through the existing owned native-session boundary. Completion
requires child settlement before source/artifact/environment paths can be reused;
failure and cancellation retain the runner's existing fence/recovery sponsor.
Synchronous inventories retain immutable digests and finite caller-funded package
bytes, with no native handle or borrowed archive escaping its context. These
Linux tests do not prove other-platform support, unrestricted native safety or
cleanup when underlying fence/storage operations never settle.

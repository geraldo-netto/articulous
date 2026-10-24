# Native SaxonC validation

On 2026-10-24, the owner authorized downloading the CI-pinned SaxonC-HE 12.10
Linux x86_64 archive. Its 40,032,605 bytes are cached at
`/backups/disk2/software/SaxonCHE-linux-x86_64-12-10-0.zip`; SHA-256 matches
the pin in `.github/workflows/main.yml`:
`8db496a54568fac34950d4e581e832087c82dd0924545f67a5c56031c003d9ce`.
The executable and matching libraries are extracted under
`/home/netto/.cache/articulous/SaxonCHE-linux-x86_64-12-10-0`.

At the source revision/hash recorded in `native.json`, the unchanged
`tests/test_saxonc_integration.py` suite passed **all 16 tests**
with zero failures, errors or skips in 4.63 seconds, using Python 3.11.15 and
pytest 9.0.3. This includes the exact HE 12.10 version assertion, literal
parameters, reciprocal alternates, safe and large JSON-LD, all-section rendering
and cache reuse, file/HTTP read denial, secondary-write denial, XInclude isolation,
external-entity denial and preservation of prior output after compilation failure.
TEST-003 is resolved. Archive, executable, library and test-source hashes are
recorded in `native.json`. This acceptance run establishes the tested Linux
behavior; it is not a native memory-leak or unrestricted lifetime-safety proof.
Later API-002 acceptance uses the independent `TransformFailure` error contract
while preserving the version, native status, security and output-preservation
assertions; its current full-suite evidence is in `../api/README.md`.

To repeat without further transfers:

```sh
saxonc_root=/home/netto/.cache/articulous/SaxonCHE-linux-x86_64-12-10-0
ARTICULOUS_SAXONC_HOME="$saxonc_root/SaxonCHE" \
LD_LIBRARY_PATH="$saxonc_root/SaxonCCoreHE/lib:$saxonc_root/SaxonCHE/lib" \
.venv/bin/pytest --no-cov -vv --tb=short tests/test_saxonc_integration.py
```

## Earlier supplemental validation

SAXON-001 supplies the protocol restriction through a Saxon configuration document:
`configuration/global@allowedProtocols="#none"` in namespace
`http://saxon.sf.net/ns/configuration`. The command retains `-ext:off` and
`-xi:off`. Cached SaxonC-PE 12.9 rejects the previous
`--allowedProtocols:#none` string option before transformation; its configuration
reader accepts the XML representation of the same restriction.

The permanent `tests/test_saxon_protocol_config.py` regression failed before the
fix and passes afterward. It verifies the exact policy document, its presence
through the native borrow, cleanup after success/subprocess failure, and cleanup
with prior output preserved after configuration write/close failure. The existing
atomic-output regression remains intact.

The configuration file has one `TempWorkspace` owner inside `_run_saxon`. Its
writer closes before the native process borrows the pathname. The workspace stays
alive through `subprocess.run` settlement and removes its owned file on every
exit. The static configuration has no caller-supplied XML or retained callback;
existing input/stylesheet and staged-output owners retain their separate scopes.

Before authorizing the pinned HE download, the owner selected offline
supplemental testing with the cached archive
`/backups/disk2/software/SaxonCPE-linux-x86_64-12-9-0.zip`. Its executable and
libraries were extracted to `/home/netto/.cache/articulous/SaxonCPE-12.9` without
downloads or package installation. To repeat from the repository root:

```sh
ARTICULOUS_SAXONC_HOME=/home/netto/.cache/articulous/SaxonCPE-12.9 \
LD_LIBRARY_PATH=/home/netto/.cache/articulous/SaxonCPE-12.9/lib \
.venv/bin/pytest --no-cov --tb=short tests/test_saxonc_integration.py
```

Observed on PE 12.9 after the fix: **15 passed, one expected version mismatch**. Before the
fix all 16 checks failed. The passing cases cover literal parameters, reciprocal
alternates, safe and large JSON-LD, all-section rendering and cache reuse,
file/HTTP read denial, secondary-write denial, XInclude isolation, external-entity
denial and preservation of prior output after compilation failure.

`test_real_saxonc_version` requires **SaxonC-HE 12.10** and intentionally fails
against the PE 12.9 archive. CI's pinned archive/version test and all security
assertions remain unchanged. These historical PE results are supplemental;
the HE 12.10 run above supplies the required acceptance evidence.

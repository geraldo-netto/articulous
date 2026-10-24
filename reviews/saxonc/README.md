# Offline SaxonC validation

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

Owner selected offline supplemental testing with the cached archive
`/backups/disk2/software/SaxonCPE-linux-x86_64-12-9-0.zip`. Its executable and
libraries were extracted to `/home/netto/.cache/articulous/SaxonCPE-12.9` without
downloads or package installation. To repeat from the repository root:

```sh
ARTICULOUS_SAXONC_HOME=/home/netto/.cache/articulous/SaxonCPE-12.9 \
LD_LIBRARY_PATH=/home/netto/.cache/articulous/SaxonCPE-12.9/lib \
.venv/bin/pytest --no-cov --tb=short tests/test_saxonc_integration.py
```

Observed after the fix: **15 passed, one expected version mismatch**. Before the
fix all 16 checks failed. The passing cases cover literal parameters, reciprocal
alternates, safe and large JSON-LD, all-section rendering and cache reuse,
file/HTTP read denial, secondary-write denial, XInclude isolation, external-entity
denial and preservation of prior output after compilation failure.

`test_real_saxonc_version` still requires **SaxonC-HE 12.10** and intentionally
fails against this PE 12.9 archive. CI's pinned archive/version test and all
security assertions remain unchanged. Supplemental PE results do not establish
HE 12.10 acceptance; the missing native version remains TEST-003. No network
transfer is authorized for that remaining prerequisite.

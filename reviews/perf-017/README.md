# PERF-017 — validation-scoped path resolution

The portal owner authorized this narrow engine change on 2026-10-30.
The validator borrows one stable publication tree and now owns a resolution
dictionary for that invocation. All references still receive their individual
existence, redirect and fragment checks. Standalone checks remain uncached.
The dictionary is cleared on success, validation failure and cancellation;
no cache or filesystem identity is reused by a later validation call.

Four permanent regressions in `tests/test_validation_resolution.py` cover
repeated resolution counts, duplicate diagnostics, changed symlink containment
between calls and cancellation cleanup. Two failed before the implementation;
all pass afterward. Existing seeded URL boundary and invalid-input tests remain.

Offline full-suite command:

```sh
ARTICULOUS_BUILD_PYTHON=/usr/bin/python3 \
ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn \
.venv/bin/python -m pytest
```

Result: 3,195 passed, 16 existing skips, 359 subtests passed; 100% measured
production line and branch coverage. The skips do not establish native support.
An initial invocation omitted the documented local parser/build-tool selectors;
its environmental failures were resolved without installation or downloads.
All 17 validator functions pass the independent per-function 80% line gate.
`native-counters.json` retains their native counters. `complexity.json` records calibrated
Lizard 1.23.0 measurements for production and regression functions (maximum 8).

On the portal's 1,393-page publication, repeated reference validation reduced
resolver calls from 78,718 to 3,174. Alternating uncached/cached runs took
6.885/2.373/2.545/6.847 seconds, all with zero diagnostics. These timings include
resolver-count instrumentation and exclude HTML parsing; they are not full-build
or network measurements. Portal review artifacts retain the raw observations.

Memory is O(distinct resolved URLs) within one admitted stable-output validation.
Paths are owned Python values with no open descriptors, native borrows, threads
or callbacks. The existing caller must keep the output stable during validation;
this finite regression evidence is not a claim about concurrent filesystem
mutation. Cleanup does not rely on successful validation or delayed collection.

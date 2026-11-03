# TYPE-001–004: full static acceptance

Verified 2026-11-03 on Linux with Python 3.11.15 and Pyright 1.1.411.
The initial full Pyright run reproduced the 13 diagnostics recorded in
[the earlier baseline](../social018-2026-11-01/pyright-final.log).
The 44 affected runtime cases passed before the corrections; these were static
acceptance defects, with no reproduced runtime behavior defect.

- TYPE-002: import the explicit `lxml.etree` module in the XML source adapter and
  HTML5 serialization tests, following the existing project import pattern.
- TYPE-003: assert the article, title element and task exist before their tests
  access them. Existing value, byte-preservation and rendering assertions remain.
- TYPE-004: annotate only deliberate invalid test inputs and the mutation target
  as dynamic `Any` values. Runtime rejection still requires the original exact
  exception classes. Production contracts and type-check configuration are unchanged;
  no casts, ignore directives or diagnostic suppressions were added.
- TYPE-001: the full Pyright check now reports zero errors and warnings. The
  existing manual CI Pyright step remains the permanent static acceptance gate;
  the retained BUILD-038, BUILD-039, PERF-018 and HTML5-001 tests exercise runtime
  behavior, invalid inputs, immutability and cleanup.

CC-004 was found during acceptance: the committed aggregate complexity report
predated committed sources. Its `articles.py` digest differed from the source at
the same HEAD, and its inventory omitted the already committed `xml_sources.py`.
The aggregate was regenerated with the installed calibrated analyzers. Its
unchanged counting conventions, syntax limits and explicit pre-policy exceptions
are documented in [the complexity contract](../complexity/README.md).

Lizard 1.23.0 records these changed function measurements in the refreshed
[source-bound report](../complexity/functions.json):

| file | function | complexity |
|------|----------|------------|
| tests/test_article_source_view.py | test_build038_parse_once_and_keep_original_bytes | 1 |
| tests/test_article_source_view.py | test_build038_invalid_source_contracts_reject_before_metadata | 3 |
| tests/test_captured_display_date.py | test_build039_native_and_captured_display_date | 3 |
| tests/test_model_projection.py | test_perf018_projection_contract_owns_immutable_parameters | 1 |
| tests/test_model_projection.py | test_perf018_streamed_artifacts_bypass_presentation_projection | 1 |

Acceptance results:

- Full Pyright 1.1.411: zero errors and warnings.
- Full pytest: 3,228 passed, 16 optional SaxonC integration tests skipped,
  359 subtests passed. No SaxonC native execution is claimed for this run.
- Coverage: all 7,743 executable production lines and 2,396 branches covered;
  989 of 989 maintained Python functions have native counters and meet 80% lines.
- Ruff 0.15.22: full lint and McCabe complexity checks passed.
- Aggregate complexity acceptance: 2,971 source-bound functions and 14 XSLT
  templates accepted; existing pre-policy exceptions remain explicit.

The full run reused the documented installed Acorn and Chromium paths and set
`ARTICULOUS_BUILD_PYTHON=/usr/bin/python3` for distribution tests. No dependency
installation was needed.

The production edit changes only the import spelling. Source bytes, XML trees
and serializer ownership remain with the existing `XmlSource` caller; file
readers close before it is returned. Test aliases and assertions remain within
their pytest invocation and fixture lifetime. No native allocation, callback,
handoff, cancellation, settlement or reuse boundary was added or changed.

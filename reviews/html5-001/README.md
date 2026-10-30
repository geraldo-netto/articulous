# HTML5-001 / Morpha REV-197 — 2026-10-30

Owner authorized this narrow Articulous correction and a separate local commit.
The previous libxslt HTML serializer wrote closing tags for source, track, wbr
and embed. Morpha correctly rejected that output during HTML5 validation.

The native adapter now identifies explicit or inferred HTML output and projects
only HTML-context void end tags out of its serialized text. XML/text output keeps
native bytes. Existing atomic publication remains the sole output owner; failure
before settlement leaves the prior publication intact. The serializer cache
identity is v3. Public engine interfaces are unchanged.

`tests/test_html5_serialization.py` and `tests/test_html_serialization.py` are
permanent normal-suite regressions. The initial native controls failed 12 cases
before correction (2 existing-method controls passed). The final focused suite
passed 113 tests, with 100% line and branch coverage for both new modules. It
includes bounded generated Unicode/whitespace cases, invalid inputs, raw text,
comments, SVG/MathML contexts, five encodings, explicit dependency methods,
inferred HTML and injected serialization failure. These finite controls do not
claim exhaustive HTML-parser or codec equivalence.

Full verification command (offline, using the installed wheel build interpreter):

```sh
ARTICULOUS_BUILD_PYTHON=/usr/bin/python3 \
ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn \
.venv/bin/pytest
```

Result: **3,190 passed, 16 skipped, 359 subtests passed; 100% line and branch
coverage** across the full measured production scope. Existing skips are not
native-support evidence. An earlier invocation without the documented build
interpreter selector encountered three distribution-fixture setup errors because
the project virtualenv lacks setuptools; no package download or installation was
needed to correct the invocation.

`complexity.json` records each new/changed function using Lizard 1.23.0, with an
independent Python AST inventory check; maximum 9, no violations. Source hashes
bind those measurements to this implementation.

Lifetime review: the transform owns its native result through synchronous
serialization. The parser, stack, source spans and result parts are per-call,
O(serialized length), and retain no native borrow or callback after return or
failure. Existing stylesheet-cache lifetime is unchanged; its additional boolean
is immutable. Atomic staging continues to own cleanup on write/serialization
failure. There is no new thread, descriptor, global mutable cache or reuse pool.

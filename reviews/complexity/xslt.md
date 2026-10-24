# Scoped offline XSLT complexity metric

CC-005 defines `xslt1-control-xpath-v1`, a static per-template cyclomatic metric
for the maintained packaged XSLT. It uses the installed libxml2 XPath compiler
(native version `20914`, meaning 2.9.14) through an isolated Linux worker.
This is a calibrated equivalent complexity workflow; it does not claim numerical
identity with an unavailable SonarQube XSLT analyzer.

Each template scores **1 + explicit control decisions + XPath decisions**.
Explicit decisions are `xsl:if`, each `xsl:when`, and `xsl:for-each`.
`xsl:otherwise` is the remaining path of its choose. XPath decisions are native
compiled `AND`, `OR`, `PREDICATE` and `FILTER` operations. Boolean operators
short-circuit; predicates and filters condition inclusion. Union, arithmetic,
function calls and `not()` introduce no separate static branch. Calls and template
dispatch do not inline callee complexity into their caller.

The independent schema is `complexity_xslt_contracts.py`. The counter inventories
templates/control nodes and extracts XPath from selects, tests, match patterns,
numbering expressions and attribute value templates. This includes literal result
attributes, computed XSLT names/namespaces, sort controls and numbering formats.
Counting match predicates inside their template is conservative about dispatcher
work. AVTs distinguish `{{`/`}}`, delimiters and braces inside quoted XPath.
Native compilation distinguishes operators from names and literal text.

The scope is explicit XSLT 1.0 containing top-level templates and the instruction/
attribute schema in the contract. Every current packaged instruction is covered.
Unknown instructions/attributes, includes, imports, non-template globals,
forward-compatible versions, DTDs and extension instructions are rejected.
Moving decisions into an unmeasured global/import cannot pass. EXSLT function
calls such as `exsl:node-set` remain calls, not executed analyzer extensions.

The worker first compiles original XPath for syntax admission. It then compiles
a projection with literal strings replaced by one fixed literal, preserving
decision shape and preventing literal newlines/words from injecting fake debug
operations. Neither expression is evaluated. A closed operation/header decoder
rejects unknown formats; streaming expressions have no boolean/predicate nodes.
Compiler provenance must remain consistent throughout calibration/measurement.

Independent calibration covers operators, keyword/qualified names, inert literal
tokens/newlines, nested/successive predicates, primary-expression filters, union,
comparisons, arithmetic, choose branches, loops, AVTs/quoted braces/computed names
and the threshold of 9. `xslt.json` records calibration source, expected/actual
results and trace identities. Template records contain source identities/lines,
controls, expressions and scores; file digests bind exact original bytes.

```sh
.venv/bin/python -m articulous.complexity_xslt measure
.venv/bin/python -m articulous.complexity_xslt check
```

Measurement atomically writes the complete inventory, then checks the limit.
Above-limit evidence returns failure; there is no override or suppression.
Check validates a trusted snapshot against current sources and recalculates
scores from recorded native decisions. It does not authenticate an edited report
or rerun the compiler. Remeasure after source edits.

Each command belongs to the existing isolated session/group/fence backend, with
browser tooling disabled. Native pointers remain inside the worker: the original
compiled object is freed before projection admission, and the projection is freed
after its synchronous trace borrow settles. Library code handles remain funded
by worker lifetime. No pointer, callback, descriptor or borrowed buffer crosses
the JSON boundary.

Python owns the temporary trace file. C borrows a duplicated descriptor through
`fdopen`; failed admission closes that duplicate, successful admission ends with
one `fclose` before Python seeks/reads its own descriptor. Failure frees the
compiled pointer and closes the Python file. A native close error fails the
command without retry/reuse; owned worker exit settles any remaining descriptor
obligation. Cancellation/native failure settles the owned process context before
caller resources are reused, under the existing fence/recovery contract.

Bounds: immutable stylesheet input at most 1 MiB; native expressions at most
16 KiB UTF-8 without NUL; at most 128 expressions per AVT; a 128 KiB trace-file
capacity enforced by the worker's Linux `RLIMIT_FSIZE` and bounded read.
Per-stylesheet memoization retains at most 256 immutable results and is released
with the invocation. Exhaustion rejects; other OS-native adapters are unsupported.

Permanent tests cover invalid/boundary/property inputs, duplicate/missing/stale
evidence, deliberately faulty calibration/above-limit controls, trace exhaustion,
bounded pointer lifecycle faults and descriptor churn. The lifecycle model checks
allocation/free conservation, exact identity and no trace access after release
for original/projection admission and trace failure. Cleanup liveness assumes
synchronous calls return or owned exit/fence eventually settles; unknown native
obligations remain under that process owner. These checks establish the wrapper's
bounded contract, not unrestricted memory safety of libxml2 internals.

CC-004 decomposes the attribute sanitizer's score of 18 into attribute dispatch,
image-dimension admission and URL admission helpers. All 12 resulting templates
measure at most 9. Helpers borrow the current attribute and immutable scalar
parameters during one synchronous transform. Intermediate result fragments and
copied attributes belong to the engine's transform/result document; admission
emits at most one attribute and rejection emits none. No cross-transform state,
callback or new native resource owner is introduced.

`test_cc004_packaged_template_complexity` fails on the previous sanitizer and
passes after decomposition. The permanent attribute suite covers protocol,
event/style/srcdoc rejection, namespace/case context, ASCII numeric boundaries,
unrelated literal attributes, bounded malformed-value properties and element
identity/order. Its pre-refactor cases pass unchanged afterward. A separate
90-element packet produces identical elements, attributes and text on libxslt
and cached SaxonC-PE 12.9; source identities are in `theme-native.json`.
That native run also exposed ambiguous fallback priorities (THEME-002).
The identity rule now has explicit priority -1. A permanent declaration-order
permutation regression fails before that fix and passes afterward; the same
90-element native packet remains identical and produces no stderr warnings.

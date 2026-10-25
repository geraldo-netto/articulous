# Native translation HTTP acceptance — REVIEW-024

The permanent `test_review024_http_error_response_is_closed` regression failed
before the fix for real loopback HTTP 400, 429 and 500 responses: the retained
`HTTPError.closed` property remained false. `urlopen` raises that response-owning
error before the successful-response context can be entered. The transport
admission helper now closes rejected responses before rethrowing the original
error; status, URL, reason and headers remain available. Those same three
regressions pass after the fix, retaining and then closing each error again as
an idempotent cleanup control.

Real-provider calls in the new tests also failed offline Pyright because the
independent `TranslationProvider.model` field required mutation while the native
provider is frozen. The contract now exposes a read-only property, matching the
consumer's actual read-only use. The permanent calls remain in the normal
Pyright inventory; no cast, suppression or adapter workaround is required.

The initial REVIEW-024 planning criterion incorrectly prohibited failed-unit
drafts. That contradicted `translation_xml.mirror_xml`, the existing failed-
provenance regression and the optional-translation guide. REVIEW-025 recorded
the contradiction; the criterion was corrected to the documented behavior.
Permanent real-HTTP single-unit job controls verify preserved source text, a failed-unit
count, absent clean provenance and an empty successful-result cache. Existing
incomplete-draft behavior remains intact.

## Permanent acceptance

`tests/test_translation_http.py` contains 65 loopback cases. They verify POST
path/headers/body, model settings, Unicode prompt/input/result, cache reuse,
HTTP rejection, fixed-seed malformed JSON and invalid schema/encoding values,
empty/whitespace/Unicode/4,096-character valid results, response truncation,
header/body deadlines, disconnects and successful retries. Fault controls raise
`KeyboardInterrupt` during an actual acquired response's read and fail an HTTP
error's close operation. The latter retains the exact response owner in the
exception chain until the test sponsor completes native close.

All 115 focused HTTP/translation/setup tests pass. Ruff and offline Pyright pass.
Lizard 1.23.0 measures `_open_response` at 2, changed `HttpProvider.post` at 3 and
the new contract property at 1. All 25 new test/server helpers measure 1–4.
Source identities and per-function results are recorded in
`../complexity/functions.json`, using the calibrated counting conventions and
syntax support described in [the complexity workflow](../complexity/README.md).

Full Linux acceptance passed 3,062 tests and 359 subtests with 100% executable-
line and branch coverage. All 955 production functions passed individual native
coverage acceptance; `_open_response` and `HttpProvider.post` each measured 100%.
The aggregate accepted 2,853 source-bound functions and 14 XSLT templates. Cached
Chromium and checksum-verified SaxonC-HE 12.10 remained enabled.

## Ownership and limits

The adapter owns every acquired response through JSON observation and context
exit; rejected-status errors are settled before handoff to the caller. Close
failure preserves the response owner in the exception chain rather than claiming
settlement. The receiving caller must sponsor explicit retry if close fails.
Schema rejection, truncation and interrupted reads retain the existing context's
cleanup sponsor. The provider retains only immutable connection/settings values
between calls; caches and parsed XML drafts have separate containing owners.

The conservation invariant is one cleanup sponsor for each unsettled response:
the active response context, the transport's rejected-error scope, or the caller's
retained close-failure chain. Successful settlement leaves no open response for
that identity. JSON observation occurs only inside the live response context;
status diagnostics after close use parsed metadata and never read a retired body.
The permanent controls cover normal admission/settlement, rejection, interrupted
observation and failed-close/retry transitions. They are finite native traces,
not an exhaustive model of urllib, the socket stack or arbitrary concurrency.

The fixture owns one IPv4 loopback listener and one server thread. Each accepted
socket has a three-second read deadline. Fixed replies and requests are finite;
request bodies are at most 8,192 bytes in this fixture. Client timeout cases use
one-second HTTP deadlines, with an explicit release event settling delayed server
work on every exit. These are protocol contracts, not total suite runtime caps.
The single server thread owns admitted connections and request/peer observations;
the caller observes final state after shutdown/join. No worker survives fixture
retirement, all accepted socket objects are closed, and non-disconnect cases
require actual peer EOF before server-side socket retirement. The listener closes
at context exit. Errors become scalar fixture diagnostics, without retained
traceback/socket cycles.

The SQLite context owns its connection; the translator only borrows it. Failed
requests cannot add success-cache entries. XML/digest observations are synchronous
and bounded by the fixed test documents, without escaping native views. Eventual
cleanup assumes scheduler progress, delivered socket deadlines and eventual
successful close; the close-fault control supplies an explicit retry sponsor.
These Linux/Python 3.11.15 native observations do not prove unrestricted response
size, arbitrary interleavings, semantic translation accuracy or native support
on untested platforms. No external provider request, model startup, tool download
or article/post-code execution occurs.

# Regex denial-of-service review — 2026-10-24

Offline review following the API work at `c977f26`. No dependency downloads,
network requests or post-code execution occurred. The managed security scan tools
were unavailable; this is a local source review with bounded supporting probes,
not a managed security scan or an unrestricted complexity proof.

## Owner scope decision

After the initial observations, the owner instructed: “we must NOT evaluate the
code in the posts, let it go and if needed, set as wont fix”. Content-oriented
taxonomy/highlighting analysis stopped. Findings remain explicitly declined in
TODO.md as REDOS-001, REDOS-002 and WIRING-001. No further post-content probes or
vendor hardening were performed. This disposition does not establish that all
Prism patterns are safe. The probes treated generated strings as matcher input;
they never evaluated or executed a snippet as a program.

## Inventory and source dispositions

Python AST inventory found 22 `re` calls in 14 production/tooling files, including
the dynamic taxonomy factory's escaping/splitting. An installed Acorn walk found
349 regex literals and 19 `RegExp` calls/constructions across packaged JavaScript
and tooling, including all 20 Prism files. Constructors without `new` were
included. Inventory is a source count, not a claim of exhaustive runtime coverage.

| Surface | Source/control | Disposition |
|---------|----------------|-------------|
| Article metadata | articles.py:148-166; slug/translation identifiers capped at 128 characters; timestamp components have fixed finite widths. | No superlinear failure path identified. Identifier separator and alphanumeric repetitions consume disjoint characters. |
| Configuration, taxonomy policy and translation language admission | config.py:168, taxonomy_policy.py:9, translation_jobs.py:10; full-string character classes and delimiter-separated identifier runs. translations.py:11 has fixed-width language/script/region components. | No ambiguous repeated partition identified. Uncapped identifiers still consume caller-funded linear-sized input; this does not establish a total build resource bound. |
| URLs and slug normalization | sections.py:166-168, slugs.py:8-9; one character-class scan, fixed-width percent lookahead, nonoverlapping replacement runs. | No regex backtracking amplification identified. |
| Protected markup placeholders | markup.py:9,80,97; fixed `<z`/`</z` prefixes, digit runs followed by disjoint whitespace/closing syntax. | No ambiguous repetition identified; malformed candidates cannot consume a following placeholder prefix as digits/whitespace. No provider response or article program was executed. |
| Optional taxonomy completeness | taxonomy_completeness.py:31-44; escaped names joined with variable separators and word guards. | Confirmed separator-leading retry path; declined REDOS-001. This API is opt-in, with no default generator dispatch. Escaping prevents regex injection but does not prevent repeated search-start work. |
| XSLT AVT parsing | complexity_xslt.py:22-37; anchored match at the current offset, disjoint unquoted/single-quoted/double-quoted alternatives and explicit brace syntax. parse_stylesheet admits at most 1 MiB; expression count separately bounded. | No ambiguous consuming partition identified. Direct avt_expressions calls remain caller-funded by string length; native XSLT compilation has separate behavior. |
| Native XPath tooling | backends/xpath.py:11-19,80-85; expressions limited to 16 KiB and validated by the native compiler before quoted-literal substitution. complexity_xpath.py:15-39 checks traces at 128 KiB. | Quote-delimited literals, fixed headers and disjoint space/uppercase runs have no identified exponential path. Native XML/XPath processing is outside this regex conclusion. |
| Analyzer evidence | complexity_native.py:10,87-94, complexity_contracts.py:19; anchored fixed-suffix diagnostics and exactly 64 hexadecimal digits. Persisted evidence admission is limited to 32 MiB. | No nested ambiguous consuming repetition identified. Lazy diagnostic prefix scans for a fixed-size suffix; this is not equivalent to nested arbitrary repetition. |
| Maintained browser code | search-client.js:30 uses character-class and hyphen-run replacements with anchored edge removal. code-blocks.js and the maintained copy plugin have no regex of their own. | No search-client regex amplification identified. Highlighting reaches vendor patterns synchronously; declined REDOS-002. |
| Browser tooling | browser-session.mjs:45 uses a two-character path-separator class. native-coverage.mjs:64-65 uses anchored leading whitespace, fixed comment prefixes or a punctuation run followed by disjoint whitespace, and a single nonspace search. javascript-syntax.mjs delegates parsing to Acorn. | No ambiguous nested partition identified. Regex review does not claim the parser or browser has unlimited resource capacity. |
| Prism dependency | Exact manifest-pinned Prism 1.30.0, including dynamic grammar construction and regex cloning in core. | Reviewed initial candidates and runtime reachability; further content-focused analysis intentionally stopped. Known quadratic examples and missing dependency are declined below. No all-pattern safety claim. |

The generator itself has no default browser JavaScript dependency. Optional
resource consumers select and load the highlighting assets. The content XSL
preserves code as text/markup; the observed denial-of-service sink is the
highlighter's own regex execution over that text.

## Completed bounded observations before the scope decision

Python 3.11.15: `tag_pattern('-a')` yields
`(?<!\w)[\s-]+a(?!\w)`. `missing_tags` with that vocabulary and a title of N
spaces plus `!` completed at N=1,000/2,000/4,000/8,000 in approximately
5/21/79/156 ms on this host. There is a valid start at each space and a failed
suffix after scanning the remaining run, giving quadratic retry work. The timing
samples support this source argument; they are neither stable thresholds nor a
prediction of other hosts. No remote input endpoint was established.

Node 24.18.0 / V8 13.6.233.17-node.50 loaded packaged, unmodified grammars into an
isolated VM context. Calls to `Prism.highlight(text, grammar, language)` completed
for four sizes per case; strings were data, never passed to eval or a compiler.

| Language/input construction | Character sizes | Observed milliseconds | Relevant pattern |
|-----------------------------|-----------------|-----------------------|------------------|
| batch: `set ` followed by N `a` characters | 1,004 / 2,004 / 4,004 / 8,004 | 1.6 / 5.0 / 19.6 / 76.9 | prism-batch.js byte 1266: unanchored `\w+` with assignment lookahead inside the set grammar. |
| bash: N repetitions of `a-` | 2,000 / 4,000 / 8,000 / 16,000 | 6.1 / 19.3 / 76.3 / 313.7 | prism-bash.js byte 2251: `\b[\w-]+` and function lookahead; repeated word boundaries permit rescans. |
| markup: N repetitions of `<x ` | 3,000 / 6,000 / 12,000 / 24,000 | 8.5 / 32.6 / 131.5 / 522.6 | prism-markup.js byte 558: unterminated tag/attribute scans restart at later tag candidates. |

The real `highlight` path was used because earlier grammar rules can consume a
candidate before a suspect later regex runs. Initial PHP comment, Java generic,
Python quote, SQL quote, CMake string and INI key cases also completed at these
four sizes without comparable growth; this provides controls for those particular
strings, not proofs of their grammars. No Chromium measurement or cross-browser
worst-case result is claimed. Timings remain historical evidence, with production
code unchanged by this review.

VB.NET loading failed before tokenization: prism-vbnet.js extends `basic`, which
is not in the package manifest. The distinct `visual-basic` grammar does not
satisfy that dependency. Existing browser acceptance logs script-load exceptions
and measures maintained integration functions, so its passing result does not
contradict this dependency failure. WIRING-001 records the missing acceptance
coverage and the owner's disposition together.

## Verification and resource scope

The completed API acceptance run passed 2,868 tests and 359 subtests with 100%
line/branch coverage, individual coverage for all 936 maintained Python functions,
calibrated complexity, Ruff and offline Pyright. Existing XPath/AVT/tooling tests
include invalid values, capacity edges, seeded malformed inputs and cleanup
controls; they remain permanent. This review changes documentation/dispositions
only and adds no artificial behavioral tests.

After the scope decision, the focused offline XPath, XSLT and complexity-tooling
suite passed all 219 tests (`pytest --no-cov tests/test_complexity_xpath.py
tests/test_complexity_xslt.py tests/test_complexity_gate.py`, with the installed
Acorn path supplied). The full acceptance coverage evidence was preserved.

Probes owned their small generated strings, regexes and VM objects until their
synchronous process exited successfully; no callback, worker, descriptor, process
or stored native pointer escaped. All admitted cases completed and the owned
process was reaped. Finite input cases and source reasoning establish the stated
scope only. Larger content, all possible grammar inputs, native regex internals,
concurrent callers and other platforms remain outside the measured claim.

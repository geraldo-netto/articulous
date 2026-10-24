# Native code and clipboard acceptance

REVIEW-009 adds the normal-suite test `tests/test_code_browser.py`. It launches
`tests/tooling/code-browser.mjs` and `code-block-page.js` against installed local
Prism and maintained theme assets. No package or browser download is implicit.

Reproduce from the repository root using installed dependencies:

```sh
export ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn
export ARTICULOUS_CHROMIUM=/home/netto/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell
.venv/bin/pytest --no-cov tests/test_code_browser.py
```

The report is written to that pytest case's temporary `browser-coverage.json`.
`code-coverage.json` records the 2026-10-24 Linux run with Chromium
149.0.7827.55, V8 14.9.207.21, Node 24.18.0 and Acorn 8.17.0. Source SHA-256
values bind its results to both maintained modules. All 25 explicit functions
and both module bodies measured 100% executable-line coverage; acceptance
requires >=80% for each. Source parsing independently inventories functions,
so absent native counters cannot silently reduce the denominator. This is
line coverage, not a claim of complete branch or interleaving coverage.

Sixteen named scenarios exercise invalid/detached admission, language aliases,
exact text/markup normalization, real Prism tokenization, accessible labels,
pending admission, success, synchronous/asynchronous rejection, defaults,
disposal before native write, detach/reparent/class changes, stale timers,
initialization and remounts with late success/error. Missing Prism, toolbar and
clipboard capabilities are checked explicitly. The fixture replaces Clipboard
API writes with controlled promises; it never touches the system clipboard.
OS clipboard contents and browser permission prompts are outside this evidence.
Upstream Prism coverage exemptions remain tied to their exact recorded hashes.

Each case owns its controller and DOM fixtures until disposal and promise
settlement. Remounts retain the retired controller until its delayed result is
observed; old callbacks cannot change the new controller. Timers/listeners are
cut off by disposal, and fixture references are released before page navigation.
The runner retains source and counter identities before destroying a context.
Only immutable asset bytes, finite case results and scalar coverage rows survive
those page lifetimes. Inputs are the fixed local asset and case inventory.

The loopback server serves that fixed inventory only. External browser requests
are routed to an unavailable loopback proxy and external name resolution is
disabled. CDP calls and browser/page startup retain explicit 10-second protocol
deadlines; completed cases report progress without a total suite runtime cap.
Python's owned session contains Node, Chromium, helper modules and private
profile storage. `stopBrowser` closes admission and waits for generation-bound
native process exit before releasing the profile. The outer process-group fence
also covers partial startup, failure and cancellation; unknown obligations use
the existing retained recovery path. Linux is the validated supervision backend;
these checks establish no Windows/macOS native support or unrestricted leak proof.

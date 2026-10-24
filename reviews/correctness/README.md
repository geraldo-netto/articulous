# Review-fix verification — 2026-10-24

Nine findings from the review of `7edb0b0` were fixed in separate commits.
For each behavioral bug, a permanent reproduction was added before its fix and
observed failing. Resolved entries were removed from TODO.md; existing declined
content/highlighting findings were preserved.

| Finding | Fix commit | Permanent regression |
|---------|------------|----------------------|
| REVIEW-019: failed SQLite setup | `37aaa10` | [Translation setup](../../tests/test_translation_setup.py): every setup statement, cancellation and cursor/connection settlement. |
| REVIEW-021: ownership admission | `7a005c5` | [Ownership admission](../../tests/test_ownership_admission.py): exact version types, seeded invalid identity components and valid numeric boundaries. |
| REVIEW-014: CLI output aliases | `ade4cb4` | [CLI admission](../../tests/test_cli_output_admission.py): actual CLI and API rejection of root/ancestor symlinks, preserving destination and state. |
| REVIEW-022: transaction namespace | `6f0d4ba` | [Publication namespace](../../tests/test_publication_namespace.py): absent/existing reserved paths, resolved aliases, direct backend admission and valid nearby cache names. |
| REVIEW-016: listing URL metadata | `15e77fe` | [Listing routes](../../tests/test_listing_route_values.py): rendered canonical, catalog and sitemap agreement for both slash styles, first-page overrides, paginated tags and cacheless retention. |
| REVIEW-015: retained sitemap pages | `7fe5d6c` | [Retained sitemap](../../tests/test_retained_sitemap.py): native/XSLT parity, cache loss, inclusion categories, replacements and unknown metadata. |
| REVIEW-017: originless link checks | `59340e8` | [Deployment bases](../../tests/test_local_validation_bases.py): absolute/root-relative/empty bases, local files, remote exclusion, encoded paths and traversal. |
| REVIEW-018: redirect fragments | `0bb7a47` | [Redirect fragments](../../tests/test_redirect_fragments.py): fragment replacement/inheritance/clearing, chains, Unicode and seeded invalid anchors. Existing site-validation loop controls remain in the suite. |
| REVIEW-020: native Saxon ownership | `35fa662` | [Native lifetime](../../tests/test_saxon_lifetime.py) and [borrow controls](../../tests/test_native_borrows.py): descendants retaining files/pipes, success/failure/cancellation, buffered exit output, descriptor bounds, copied-input identity, uncertain fencing and recovery-storage faults. |

The final code acceptance run passed **2,994 tests and 359 subtests** with
**100% executable-line and branch coverage**. All **953 maintained production
Python functions** had native counters and at least 80% individual executable-line
coverage. Installed Ruff and offline Pyright passed. The calibrated complexity
gate accepted 2,812 source-bound functions and 14 XSLT templates; every changed
or new function was at most 9. Per-function values, source identities, analyzer
versions and counting conventions are retained in
[the complexity evidence](../complexity/README.md).

The pinned Saxon HE 12.10 acceptance remained enabled. Existing prohibited
resource-read, secondary-write, entity-isolation and previous-output assertions
were preserved. Captured native diagnostics are emitted after settlement, so
those assertions still inspect the native failure reason. No tool installation,
download, fetch, push or artifact upload was needed.

Final documentation checks verified 33 local Markdown links and referenced
headings. Dry-run, full-build, sitemap-only and forced-build command forms all
succeeded on a disposable fixture site. After clarifying the transformation
contract's documentation, 30 contract/import tests passed and source-bound
complexity and individual coverage checks passed again.

## Ownership scope

SQLite setup owns one connection until successful construction or failure
cleanup. Setup cursors close before the next statement. Route/URL admission is
synchronous and retains only immutable values or call-scoped path projections;
its work is bounded by the admitted routes, names and strings.

The Saxon adapter owns copied XML, stylesheet and configuration directories.
The native child receives the staging descriptor within its owned session;
the leader's PID lease remains held through group quiescence, pipe drainage and
closure. Atomic installation happens after that settlement. On uncertain fencing,
the recovery broker retains the process reservation and acknowledged directory
claims. Storage-handoff failures retain the private directories and recovery token,
with manual-recovery notes; they do not authorize deleting possibly live inputs.

The faulty-tool fixtures execute controlled local native-process code. They never
evaluate article/post code. The containing fixture owns and reaps its descendants.
Tests cover a finite set of transitions and faults, supplemented by the existing
bounded process/recovery models. Conditional eventual cleanup assumes contained
workloads, eventual native exit/fence evidence, successful resource close/storage
and an owner or operator that completes retained recovery. These checks do not
prove unrestricted kernel behavior, detached workload containment or native
Windows/macOS support.

The [build and recovery guide](../../docs/building.md) explains user actions.
The [integration reference](../../docs/generator-composition.md) describes the
independent contracts, adapters and advanced recovery boundaries.

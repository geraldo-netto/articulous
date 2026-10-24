# API contract and correctness acceptance

All checks reuse installed tools and Linux x86_64 native dependencies. The full
suite enables cached Acorn, Chromium and checksum-verified SaxonC-HE 12.10, as
documented in the development and native acceptance guides. No repository upload
or additional tool transfer is required.

## API-007: publication journal admission

The permanent `test_api007_invalid_identity_preserves_recovery_obligations`
regression failed before the fix (`DID NOT RAISE ValueError`). All 24 combinations
of invalid mandatory identities/version and transaction phases now reject before
mutation and preserve backup, staged input and journal bytes. Existing initial,
replacement, crash, rollback and cleanup cases remain in the normal suite.

Validation borrows a finite decoded journal synchronously; it creates no native
resource or retained callback. The publisher retains ownership of every directory
and recovery obligation until validated identities permit the existing native
transition. Invalid admission cannot release or reuse any directory.

Verification: 2,638 tests and 359 subtests passed; 100% executable-line/branch
coverage; 852 production functions passed the individual >=80% line gate. The
source-bound Lizard 1.23.0/ESLint 10.8.1 acceptance passed (counting and syntax
conventions in `../complexity/README.md`). Changed/new production complexities:
`_validate_journal_header` 7, `_validate_identity_part` 3,
`PosixPublicationBackend._validate_journal` 7, `_validate_identity` 6; both new
test/helper functions measure 1. Per-function evidence is in
`../complexity/functions.json`.

## API-004: validation handle revocation

Both permanent revalidation regressions failed before their fixes. Diagnostic
errors, callback exceptions, malformed return values and changed artifacts now
retire the prior validation revision before checks run. A fresh success produces
a new revision; old handles cannot regain publication rights after restoration.

The prepared generation remains the sole state/revision owner. Handles borrow it
until context cutoff; revision numbers never decrease or reuse an admitted
validation identity. Validation is synchronous and retains only caller-funded
diagnostics. Errors leave the rendered generation owned by its preparation
context for retry or cleanup; no native resources are newly admitted.

Verification: 2,643 tests and 359 subtests passed; 100% line/branch coverage and
individual coverage acceptance. Calibrated complexity acceptance passed; all
changed/new function measurements remain in `../complexity/functions.json`.

## API-005: partial-build extras

The permanent resupplied-extra regression failed before the fix with
`Duplicate generated output path: about/index.html`. Nine new cases cover page
and artifact repeats/edits under section/language/slug filters, stable page-key
moves, rejection of different retained owners, and dry-run preservation.

Explicit extra identities now participate in selection before migration planning,
collision validation, route discovery and ownership settlement. The existing
manifest remains the single output owner; selection sets are synchronous derived
values bounded by declared extras. No resource ownership or native cleanup
boundary changes. Omitted artifact paths remain retained in partial builds.

Verification: 2,652 tests and 359 subtests passed; 100% line/branch coverage,
individual >=80% function coverage and calibrated complexity acceptance. Exact
per-function measurements are retained in `../complexity/functions.json`.

## API-003: composition contracts and route storage

`composition_contracts` owns route/page/artifact schemas, path admission and
`RouteReader`/`RouteWriter` interfaces. Composition callbacks import these
contracts without loading SQLite, filesystem locking or the pipeline. Current
callers and documented imports use this independent boundary; `composition`
contains the SQLite catalog and output projection adapter.

The import regression failed before extraction because SQLite was loaded.
Catalog construction and reader-admission failures now close new resources;
catalog close finalizes active cursors before the connection. Borrowed iterators
check cutoff before another native read. Cursor identity stays retained until
close settles, preventing premature reuse; a close error leaves the catalog as
cleanup sponsor for an explicit retry. Conditional cleanup assumes native close
eventually succeeds. No thread sharing is admitted by this adapter.

Verification: 2,656 tests and 359 subtests passed; 100% line/branch coverage,
860 production functions passed individual coverage acceptance, and calibrated
complexity acceptance passed. Per-function results include every moved contract
and new catalog boundary in `../complexity/functions.json`.

## API-006: durable route semantics

The cache-loss regression failed before the fix with changed custom-page,
artifact and noindex-article routes. Ownership now persists route values and is
authoritative; cache metadata is a disposable derived projection. Both normal
and whole-site publishers preserve exact routes across missing/corrupt/switched
caches. Malformed authoritative metadata rejects before publication. Legacy
metadata is admitted from a known cache once; missing semantics require a full
build for route discovery rather than fabricated URLs or sitemap policy.

The native boundary borrows `PublicationInput.output_routes`, a read-only mapping
of immutable contract values, without parsing cache internals. Metadata values
are finite caller-funded projections; synchronous serialization retains no native
handles, callbacks or DOMs. Existing atomic sidecar writes and journal rollback
retain their owners and cleanup boundaries. The old corrupt-route regression now
damages authoritative ownership; a separate permanent control proves damaged
cache metadata cannot override it. The final-ownership fault sponsor accepts and
checks the new explicit route argument while preserving its recovery oracle.

Verification: 2,678 tests and 359 subtests passed; 100% line/branch coverage,
864 production functions passed individual coverage, calibrated complexity
acceptance passed, and installed Pyright reports zero errors/warnings. Use the
installed `pyright/dist/index.js` entrypoint (which sets its bundled typeshed root)
for direct offline Node invocation; no registry lookup or installation is needed.

## API-008: bounded formatter grammar

The large-width regression failed before the fix because admission invoked the
deliberately forbidden `format()` method. Formatter traversal, conversions and
nonempty format specifications now reject while parsing placeholder names,
before expansion. Fixed-seed grammar cases cover every section; valid plain
Unicode route literals and bare-default-language combinations remain accepted.

Admission is pure, synchronous and bounded by the supplied pattern text. It
allocates no width-dependent output, owns no native resource and retains no
borrowed state. Actual generated paths retain their existing filesystem limits.

Verification: 2,705 tests and 359 subtests passed; 100% line/branch coverage,
individual function coverage and calibrated complexity acceptance. All new test
and changed admission functions measure <=9 in the source-bound report.

## API-009: malformed engine identifiers

The permanent JSON-type regression failed before the fix with
`TypeError: unhashable type: 'list'`. Configuration validation and direct engine
factory admission now share a string guard before set membership. Seeded file
mutations verify invalid JSON kinds cannot rewrite configuration, published
outputs, fingerprint cache or ownership state; valid names and native-section
restrictions remain independently checked.

The guard is pure and synchronous, borrowing one value without retaining it or
admitting resources. Its result is bounded to one boolean; native engine creation
and ownership remain downstream of successful validation.

Verification: 2,720 tests and 359 subtests passed; 100% line/branch coverage,
865 production functions passed individual coverage, and calibrated complexity
acceptance passed with every changed/new function <=9.

## API-002: independent transformation interface

`transform_contracts` defines path/byte inputs, read-only parameters, execution
capabilities, the synchronous structural engine protocol and `TransformFailure`.
It imports no concrete XML, filesystem or process implementation. Concrete
adapters share `XsltEngine`; external engines need no implementation inheritance.
The independent fake exercises captured revision resolution, real task dispatch,
cache settlement and automatic worker policy through the production pipeline.

Operational errors cross the public preparation/render boundary as the neutral
error contract, preserving native status and chained adapter diagnostics. Capture
does not wrap an already neutral failure again. Current callers/tests use the
contract; lxml/subprocess-specific exceptions remain private adapter observations.
Saxon version, nonzero native status, prohibited-resource checks and atomic prior
output assertions remain intact. Fixed invalid input/capability/parameter cases
reject before output admission.

An engine's build context owns captured stylesheet revisions and compiled caches;
wrappers retain that owner for their own containing context. Native borrows are
synchronous and settle through existing adapter scopes before error projection.
Parameter validation is pure, bounded by admitted mapping entries and string
sizes, and retains no caller state. Failure values retain scalar contract data;
chained diagnostics may retain Python frames, whose native resources have already
settled. Existing Linux acceptance does not establish other-platform support or
unrestricted native memory safety.

Verification: 2,749 tests and 359 subtests passed; 100% line/branch coverage,
880 production functions passed individual coverage, calibrated complexity
acceptance passed, Ruff passed, and installed Pyright reported zero diagnostics.

## API-010: independent requests and configuration schemas

`configuration_contracts` owns immutable build requests, narrow configuration
options, composed TypedDict schemas, immutable schema-key inventories, engine
names/admission and `ConfigurationError`. Importing it loads no CLI, concrete
engine, storage or native locking implementation. The schema/default fault
control failed before extraction; implementation-only default keys no longer
redefine accepted API fields. A standalone request drives both check and normal
build workflows, and CLI parsing converts through the same contract.

All build entry points share normalization of a private configuration copy.
Admission validates the complete independent schema before its static type
projection; the projection performs no unchecked engine/storage conversion.
Request constructors own tuple snapshots of selection sequences; JSON/source
adapters use the narrower configuration-options view. The migration fixtures now
use valid file-style routes, preserving their original unowned/special-file
oracles while schema errors reject earlier than planning.

Schema/request admission is pure and bounded by caller-funded input fields and
sequence/string sizes. Normalization owns its deep copy; returned build contexts
own their projected inputs, without mutable aliases to caller configuration.
No new native resource or callback escapes; existing path/lock, output and
publication owners retain their acquisition, settlement and cleanup boundaries.

Verification: 2,774 tests and 359 subtests passed; 100% line/branch coverage,
895 production functions passed individual coverage, calibrated complexity
acceptance passed, Ruff passed, and offline Pyright reported zero diagnostics.

## API-001: independent lifecycle capabilities

`build_contracts` defines lifecycle protocols, diagnostic/result values and the
typed build API independently of planner, storage and native filesystem modules.
Private implementation handles share one authoritative generation owner. Callers
receive read-only routes and bounded artifact readers; publication crosses an
explicit adapter into the existing independent backend contract.

The retained-reader regression failed against the old implementation: closing a
generation left a borrowed file readable. Generation retirement now cuts off all
capabilities before settling readers and route cursors. Publication settles live
artifact borrows before backend handoff. Admission failure closes acquired files;
failed cleanup retains ownership and permits explicit close retry. No descriptor
or mutable catalog escapes the public capabilities. Byte reads cannot exceed the
file size admitted at open, including arbitrarily large requested counts.

Permanent controls cover foreign handles, invalid reads/paths/diagnostics,
superseded validation, reader admission and cleanup faults, callback failure and
cancellation. An independent lifecycle oracle checks all 64 three-step traces
over validate, reject, publish and close. This finite model complements native
Linux tests; it does not prove unrestricted concurrency or other-platform safety.
Eventual cleanup assumes the cleanup sponsor retries retained failures and the
underlying close eventually succeeds. Pure contract admission retains only owned
immutable values, bounded by caller-funded fields and strings.

Verification: 2,868 tests and 359 subtests passed; 100% line/branch coverage,
936 production functions passed individual coverage, 2,755 source-bound functions
and 14 XSLT templates passed calibrated complexity acceptance, Ruff passed, and
offline Pyright reported zero diagnostics. Per-function values and installed
analyzer versions/conventions remain in `reviews/complexity/functions.json` and
its README. Dependency/import and production-call-site checks retain the explicit
publication adapter and find no newly orphaned capability exports.

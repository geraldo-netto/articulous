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

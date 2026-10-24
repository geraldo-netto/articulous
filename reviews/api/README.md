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

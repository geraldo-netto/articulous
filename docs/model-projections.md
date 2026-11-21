# Captured model projections (PERF-018 / PERF-023)

[Documentation](../README.md#documentation)

`BuildComposition.project_model` optionally accepts a `ModelInput` and returns
XML bytes for the existing transform. `ModelInput` is independent of parser and
engine implementations: captured bytes, a canonical relative output path and a
copied read-only string parameter map. Preparation finishes template/artifact
factories before callbacks run. Callbacks may read build-owned indexes prepared
by those factories. They must be thread-safe: tasks use the existing worker pool.

The projection receives captured data, never a freshly opened article path.
It owns its output bytes and any transient DOM. Returned bytes use the existing
safe parser, source base URI, stylesheet and transform parameters. Wrong return
types or malformed XML fail the staged build. Existing error aggregation and
cancellation settlement remain authoritative; failed stages cannot publish.

A projected task cannot be skipped on the original model hash. Its successful
cache entry records the projected bytes and resolved stylesheet revision. This
callback applies to byte-backed presentation models: articles, indexes, tags,
feeds and extra pages. Streamed search/sitemap files remain direct engine inputs
and retain file-based memory and cache behavior; they are not read into memory
for projection. Other inputs remain unchanged when no callback is supplied. No compatibility adapter or new persistent cache
is added. The prepared build retains the callback/index owner until worker
settlement and disposal. Callers must release retained indexes with that owner;
individual transient models are released after their transform. Bounds are the
finite captured build and existing admitted worker count, without a result cap.

Permanent tests cover immutable parameters, capture after source mutation,
factory ordering, native rendered output, cache identity, invalid input/output,
malformed XML, cancellation, cleanup and preservation of existing publication.

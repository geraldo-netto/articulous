# Rendering engines

[Documentation](../README.md#documentation)

Choose a renderer per section through `engines` in the site configuration.
Standard lxml builds require Unix file locking; the supervised SaxonC runner
requires Linux. Native Windows and macOS Saxon supervision is unsupported.

## Selection and fallback

Engine identifiers must be strings; malformed JSON values use the same
`ValueError` validation channel as unknown names.
An unknown engine name aborts the build immediately. Requesting
`"saxonc"` without a usable `Transform` executable falls back to lxml;
an invalid explicit `saxonc.home` also emits a warning. A configured
home is checked at `<home>/bin/Transform`; `PATH` discovery is used only
when no home is set. A nonzero exit from a selected executable fails
the build; it does not trigger fallback.

Ordinary engine preparation/render failures use
`transform_contracts.TransformFailure`, with operation, detail and optional native
return code. Uncertain native cleanup raises `process_contracts.NativeCleanupError`
and retains private input copies for recovery. See [native recovery](generator-composition.md#transformation-boundary).
Concrete adapter exceptions remain chained for diagnostics.

## Execution restrictions and snapshots

lxml blocks XSLT document reads and writes to files or network resources,
while allowing local stylesheet includes/imports. SaxonC is invoked with
`-ext:off`, `-xi:off` and `-config:<temporary-configuration.xml>` to disable
external functions, XInclude and external resource URIs. The configuration uses
`<global allowedProtocols="#none"/>` in the Saxon configuration namespace.
Pinned SaxonC-HE 12.10 acceptance covers these restrictions; see
[native validation](../reviews/saxonc/README.md) for the recorded evidence.
SaxonC requires standalone stylesheets: external includes and imports
are rejected. Use lxml for stylesheets with local includes or imports.
Planning captures stylesheet bytes and local dependencies; workers compile
that snapshot, so edits during execution apply on the next build. Fingerprints
include the captured bytes and logical file URIs. With lxml, relative includes
resolve beside the configured stylesheet path, including symlink paths;
`xml:base` applies consistently to both capture and compilation. Every dependency
must be a regular file and is opened without blocking on special files.
Captured article documents retain their effective base URI. SaxonC preserves
it by inserting or normalizing the root `xml:base` attribute in its temporary
XML input; stylesheets inspecting that attribute can observe this metadata.
The `"native"` engine is available only for `sitemap` and `search`; it
streams those standard formats with bounded memory. Select `lxml` or
`saxonc` for either section when custom XSLT output is required.

## Workers

With `parallelism="auto"`, the worker count is `max(4, os.cpu_count() or 4)`
unless a configured engine resolves to SaxonC, in which case it is
`os.cpu_count() or 4`. An explicit positive integer overrides that choice.

For settings, see [configuration](configuration.md). Sitemap constraints and
partitioning are documented in [search discovery](search-discovery.md).

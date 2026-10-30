# Caller-owned XML source views (BUILD-038)

`xml_sources.read_source(Path)` captures a regular file through the existing
safe XML parser and closes its reader before returning. `XmlSource`, defined
independently in `xml_contracts`, owns original bytes, their base URI, a matching
mutable `XmlElement` view and a serializer. The adapter is responsible for their
consistency. The native serializer retains the tree, including document-level
processing instructions; it does not retain an open file.

Call `articles.parse_article_source(path, source, ...)` before editing that view.
This applies the same admission, date, language, slug and publication rules as
`parse_article_xml`. Metadata admission borrows the view synchronously. Original
bytes remain immutable after tree edits; `serialize()` returns the current tree.
Callers own edits and any writes and must not share mutable views between workers.
Dropping the view/serializer releases their tree references. Capture failures
close readers; no global cache or additional native worker is introduced.

Input size remains bounded by the admitted file; this API adds no arbitrary
content limit. Byte/tree equality is a provider obligation, not a second parse.
Permanent tests cover one native parse, original-byte preservation, no-op source
identity, malformed XML, symlink rejection and invalid contract values.

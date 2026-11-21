"""Check generated artifacts before making a completed build visible."""
from dataclasses import dataclass, replace
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
import json
import re

import lxml.etree as etree
import lxml.html as html
from .sections import url_origin
from .tree_entries import tree_entries
from .validation_contracts import PageReferences, ReferenceSource, ValidationPlan, ValidationResult


def page_route(output, path):
    route = '/' + path.relative_to(output).as_posix()
    route = route.removesuffix('index.html') if path.name == 'index.html' else route
    return quote(route, safe='/')


def _same_publication_origin(parsed, origin):
    if not origin.scheme and not origin.netloc:
        return not parsed.scheme and not parsed.netloc
    return parsed.scheme in ('http', 'https') and url_origin(parsed) == url_origin(origin)


def local_path(output, value, base):
    parsed = urlsplit(urljoin(base.rstrip('/') + '/', value))
    origin = urlsplit(base)
    if not _same_publication_origin(parsed, origin):
        return None
    prefix = unquote(origin.path).rstrip('/') + '/'
    decoded = unquote(parsed.path)
    if decoded == prefix.rstrip('/'):
        decoded += '/'
    if not decoded.startswith(prefix):
        return None
    target = (output / decoded[len(prefix):]).resolve()
    if not target.is_relative_to(output.resolve()):
        raise ValueError(f'Local URL escapes output: {value}')
    if parsed.path.endswith('/') or target.is_dir():
        target /= 'index.html'
    return target


def resolved_path(output, value, base, resolved_paths):
    if resolved_paths is None:
        return local_path(output, value, base)
    parsed = urlsplit(urljoin(base.rstrip('/') + '/', value))
    key = output, base, parsed.scheme, parsed.netloc, parsed.path
    if key not in resolved_paths:
        resolved_paths[key] = local_path(output, value, base)
    return resolved_paths[key]


def read_pages(output, failures, html_errors=None):
    pages = {}
    root = output.resolve()
    for path in sorted(path for path in tree_entries(output) if path.name.endswith('.html')):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            failures.append(f'{path.relative_to(output)}: HTML page escapes output')
            continue
        source = path.read_bytes()
        errors = html_errors(source) if html_errors is not None else ()
        if errors:
            failures.append(f'{path.relative_to(output)}: HTML parse errors: {errors}')
        try:
            document = html.fromstring(source)
        except etree.ParserError as error:
            failures.append(f'{path.relative_to(output)}: HTML parse errors: {error}')
            continue
        pages[resolved] = page_references(document)
    return pages


def _canonical_links(document):
    links = '//link[@rel and @href and not(ancestor::template)]'
    attributes = zip(document.xpath(links + '/@rel'), document.xpath(links + '/@href'), strict=True)
    return tuple(str(href) for rel, href in attributes
                 if 'canonical' in re.split(r'[ \t\r\n\f]+', str(rel).lower()))


def page_references(document: ReferenceSource) -> PageReferences:
    """Detach plain values; never retain the borrowed document or smart strings."""
    return PageReferences(
        _canonical_links(document),
        tuple(map(str, document.xpath('//@href[not(ancestor::template) and not(parent::base)] | //@src[not(ancestor::template)] | '
                                      '//head/meta[@property="og:image" or @name="twitter:image"]/@content'))),
        frozenset(map(str, document.xpath('//@id[not(ancestor::template)] | //a/@name[not(ancestor::template)]'))),
        next(map(str, document.xpath('//base[not(ancestor::template)]/@href')), None),
    )


def _redirect_url(previous, destination):
    if '#' in destination:
        return destination
    return urlunsplit(urlsplit(destination)._replace(fragment=urlsplit(previous).fragment))


@dataclass(frozen=True)
class _RedirectSuffix:
    target: object = None
    url: str = ''
    error: str = ''

    def after(self, url):
        if not self.error and '#' not in self.url and '#' in url:
            return replace(self, url=self.url + '#' + urlsplit(url).fragment)
        return self


class _RedirectResolver:
    def __init__(self, output, base, redirects, paths):
        self.output = output
        self.base = base
        self.redirects = dict(redirects)
        self.paths = paths
        self.suffixes = {}
        self.links = {}

    def _step(self, route):
        value = self.redirects[route]
        url = self.base.rstrip('/') + value
        target = resolved_path(self.output, url, self.base, self.paths)
        if target is None:
            self.suffixes[route] = _RedirectSuffix(error=f'missing redirect target {value}')
            return None, url
        following = page_route(self.output, target)
        if following not in self.redirects:
            self.suffixes[route] = _RedirectSuffix(target, url)
            return None, url
        return following, url

    def _record_loop(self, trail, repeated):
        routes = tuple(trail)
        for route in routes[routes.index(repeated):]:
            self.suffixes[route] = _RedirectSuffix(error=f'redirect loop for {route}')

    def _resolve(self, first):
        route = first
        trail = {}
        while route is not None and route not in self.suffixes:
            if route in trail:
                self._record_loop(trail, route)
                break
            following, url = self._step(route)
            trail[route] = following, url
            route = following
        for route in reversed(trail):
            if route not in self.suffixes:
                following, url = trail[route]
                self.suffixes[route] = self.suffixes[following].after(url)
        return self.suffixes[first]

    def follow(self, target, resolved, failures, label):
        route = page_route(self.output, target)
        if route not in self.redirects:
            return target, resolved
        suffix = self._resolve(route)
        if suffix.error:
            failures.append(f'{label}: {suffix.error}')
            return None, resolved
        return suffix.target, _redirect_url(resolved, suffix.url)

    def link(self, resolved, failures, label):
        url = resolved.partition('#')[0]
        key = url.partition('?')[0]
        if key not in self.links:
            result = _link_target(self.output, self.base, resolved, url, self, failures, label, self.paths)
            if result[0] is None:
                return result
            self.links[key] = result
        target, final, exists = self.links[key]
        return target, final if '#' in final else resolved, exists


def redirect_target(output, target, resolved, base, redirects, failures, label, resolved_paths=None):
    if isinstance(redirects, _RedirectResolver):
        return redirects.follow(target, resolved, failures, label)
    seen = set()
    route = page_route(output, target)
    while route in redirects:
        if route in seen:
            failures.append(f'{label}: redirect loop for {route}')
            return None, resolved
        seen.add(route)
        value = redirects[route]
        resolved = _redirect_url(resolved, base.rstrip('/') + value)
        target = resolved_path(output, resolved, base, resolved_paths)
        if target is None:
            failures.append(f'{label}: missing redirect target {value}')
            return None, resolved
        route = page_route(output, target)
    return target, resolved


def _link_target(output, base, resolved, redirect_url, redirects, failures, label, paths):
    target = resolved_path(output, resolved, base, paths)
    if target is None:
        return None, resolved, False
    target, final = redirect_target(output, target, redirect_url, base, redirects, failures, label, paths)
    return target, final, target is not None and target.is_file()


def check_link(output, value, page_url, base, redirects, pages, failures, label, resolved_paths=None):
    try:
        resolved = urljoin(page_url, value)
        if isinstance(redirects, _RedirectResolver):
            target, final, exists = redirects.link(resolved, failures, label)
        else:
            target, final, exists = _link_target(
                output, base, resolved, resolved, redirects, failures, label, resolved_paths,
            )
        if target is not None:
            if exists:
                _check_fragment(final, pages.get(target), value, failures, label)
            else:
                failures.append(f'{label}: missing {value}')
    except ValueError as error:
        failures.append(f'{label}: invalid reference {value}: {error}')


def _check_fragment(resolved, document, value, failures, label):
    fragment = unquote(urlsplit(resolved).fragment).split(':~:text=', 1)[0]
    if not fragment:
        return
    if document is not None and fragment.lower() != 'top':
        if fragment not in document.anchors:
            failures.append(f'{label}: missing fragment {value}')


def document_base(page_url, href):
    if href is None:
        return page_url
    try:
        resolved = urljoin(page_url, href)
        parsed = urlsplit(resolved)
        if parsed.scheme in ('http', 'https') and not url_origin(parsed)[1]:
            return page_url
        if parsed.scheme in ('data', 'javascript'):
            return page_url
        return resolved
    except ValueError:
        return page_url


def validate_pages(output, base, plan, pages, failures, resolved_paths=None):
    redirects = _RedirectResolver(output, base, plan.redirects, resolved_paths)
    for filename in plan.page_urls:
        if (output / filename).resolve() not in pages:
            failures.append(f'{filename}: expected HTML page missing')
    try:
        for path, references in pages.items():
            filename = path.relative_to(output).as_posix()
            expected = plan.page_urls.get(filename)
            if references.canonicals != (expected,):
                failures.append(f'{filename}: canonical must be {expected}')
            route = page_route(output, path)
            reference_base = document_base(base + route, references.base_href)
            for value in references.links:
                check_link(output, value, reference_base, base, redirects, pages, failures, filename, resolved_paths)
    finally:
        redirects.links.clear()


def validate_search(output, plan, failures):
    search = json.loads((output / plan.search_path).read_text())
    if not isinstance(search, list):
        raise ValueError('Search index must be an array')
    urls = []
    for row in search:
        if not isinstance(row, dict) or not isinstance(row.get('url'), str):
            raise ValueError('Search entry must have a string URL')
        urls.append(row['url'])
    if len(urls) != len(plan.search_urls) or set(urls) != plan.search_urls:
        failures.append('Search article set does not match publication policies')
    return len(search)


def sitemap_document(path):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    document = etree.parse(str(path), parser)
    namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    root = document.getroot()
    entries = {namespace + 'urlset': 'url', namespace + 'sitemapindex': 'sitemap'}
    if root.tag not in entries:
        raise ValueError(f'Unsupported sitemap document: {root.tag}')
    locations = []
    for entry in root.iterchildren(tag=etree.Element):
        if entry.tag != namespace + entries[root.tag]:
            raise ValueError('Unexpected sitemap entry')
        locations.append(_sitemap_location(entry, namespace))
    return etree.QName(root).localname, tuple(locations)


def _sitemap_location(entry, namespace):
    nodes = entry.findall(namespace + 'loc')
    if len(nodes) != 1 or len(nodes[0]) or not (nodes[0].text or '').strip():
        raise ValueError('Sitemap entry requires one nonempty loc')
    return nodes[0].text.strip()


def _sitemap_target(output, value, base, resolved_paths):
    try:
        return resolved_path(output, value, base, resolved_paths)
    except ValueError:
        return None


def sitemap_index_targets(output, base, values, failures, resolved_paths=None):
    for value in values:
        target = _sitemap_target(output, value, base, resolved_paths)
        if target is None or not target.is_file():
            failures.append(f'Sitemap index target missing: {value}')
        else:
            yield target


def sitemap_locations(output, base, path, failures, resolved_paths=None):
    pending, seen, urls = [path.resolve()], set(), []
    while pending:
        current = pending.pop()
        if current in seen:
            failures.append(f'Duplicate or cyclic sitemap index target: {current}')
            continue
        seen.add(current)
        kind, values = sitemap_document(current)
        if kind == 'sitemapindex':
            pending.extend(sitemap_index_targets(output, base, values, failures, resolved_paths))
        else:
            urls.extend(values)
    return urls


def validate_sitemap(output, base, plan, failures, resolved_paths=None):
    urls = sitemap_locations(output, base, output / plan.sitemap_path, failures, resolved_paths)
    if len(urls) != len(set(urls)):
        failures.append('Duplicate sitemap URLs')
    if set(urls) != plan.sitemap_urls:
        failures.append('Sitemap URL set does not match publication plan')
    canonicals = {(output / name).resolve(): url for name, url in plan.page_urls.items()}
    for url in urls:
        target = _sitemap_target(output, url, base, resolved_paths)
        if target not in canonicals or canonicals[target] != url:
            failures.append(f'Sitemap target missing or noncanonical: {url}')
    return len(urls)


def validate_site(output, base: str, plan: ValidationPlan, *, html_errors=None):
    """Borrow the stable output/plan during validation; return only scalar counts."""
    output = output.resolve()
    base = base.rstrip('/')
    failures = []
    pages = read_pages(output, failures, html_errors)
    resolved_paths = {}
    try:
        validate_pages(output, base, plan, pages, failures, resolved_paths)
        search = validate_search(output, plan, failures)
        sitemap = validate_sitemap(output, base, plan, failures, resolved_paths)
        if failures:
            raise ValueError('\n'.join(failures))
        return ValidationResult(len(pages), search, sitemap)
    finally:
        resolved_paths.clear()

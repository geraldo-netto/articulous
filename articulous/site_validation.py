"""Check generated artifacts before making a completed build visible."""
from urllib.parse import quote, unquote, urljoin, urlsplit
import json

import lxml.etree as etree
import lxml.html as html
from .validation_contracts import PageReferences, ValidationPlan, ValidationResult


def page_route(output, path):
    route = '/' + path.relative_to(output).as_posix()
    route = route.removesuffix('index.html') if path.name == 'index.html' else route
    return quote(route, safe='/')


def url_origin(parsed):
    default = 443 if parsed.scheme == 'https' else 80
    return parsed.scheme, parsed.hostname, parsed.port or default


def local_path(output, value, base):
    parsed = urlsplit(urljoin(base.rstrip('/') + '/', value))
    origin = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or url_origin(parsed) != url_origin(origin):
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


def read_pages(output, failures, html_errors=None):
    pages = {}
    for path in sorted(output.rglob('*.html')):
        source = path.read_bytes()
        errors = html_errors(source) if html_errors is not None else ()
        if errors:
            failures.append(f'{path.relative_to(output)}: HTML parse errors: {errors}')
        try:
            document = html.fromstring(source)
        except etree.ParserError as error:
            failures.append(f'{path.relative_to(output)}: HTML parse errors: {error}')
            continue
        # Plain strings release lxml's document owner; smart strings would keep it alive.
        # Template placeholders are inert and are not followed during link validation.
        pages[path.resolve()] = PageReferences(
            tuple(map(str, document.xpath('//link[@rel="canonical"]/@href'))),
            tuple(map(str, document.xpath('//@href[not(ancestor::template)] | //@src[not(ancestor::template)] | '
                                          '//head/meta[@property="og:image" or @name="twitter:image"]/@content'))),
            frozenset(map(str, document.xpath('//@id[not(ancestor::template)] | //a/@name[not(ancestor::template)]'))),
        )
    return pages


def redirect_target(output, target, base, redirects, failures, label):
    seen = set()
    route = page_route(output, target)
    while route in redirects:
        if route in seen:
            failures.append(f'{label}: redirect loop for {route}')
            return None
        seen.add(route)
        value = redirects[route]
        target = local_path(output, base.rstrip('/') + value, base)
        if target is None or not target.is_file():
            failures.append(f'{label}: missing redirect target {value}')
            return None
        route = page_route(output, target)
    return target


def check_link(output, value, page_url, base, redirects, pages, failures, label):
    resolved = urljoin(page_url, value)
    target = local_path(output, resolved, base)
    if target is None:
        return
    if not target.is_file():
        failures.append(f'{label}: missing {value}')
        return
    target = redirect_target(output, target, base, redirects, failures, label)
    fragment = unquote(urlsplit(resolved).fragment).split(':~:text=', 1)[0]
    if not fragment:
        return
    document = pages.get(target)
    if document is not None and fragment.lower() != 'top':
        if fragment not in document.anchors:
            failures.append(f'{label}: missing fragment {value}')


def validate_pages(output, base, plan, pages, failures):
    for filename in plan.page_urls:
        if (output / filename).resolve() not in pages:
            failures.append(f'{filename}: expected HTML page missing')
    for path, references in pages.items():
        filename = path.relative_to(output).as_posix()
        expected = plan.page_urls.get(filename)
        if references.canonicals != (expected,):
            failures.append(f'{filename}: canonical must be {expected}')
        route = page_route(output, path)
        for value in references.links:
            check_link(output, value, base + route, base, plan.redirects, pages, failures, filename)


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
    return etree.QName(document.getroot()).localname, tuple(map(str, document.xpath('//*[local-name()="loc"]/text()')))


def sitemap_index_targets(output, base, values, failures):
    for value in values:
        target = local_path(output, value, base)
        if target is None or not target.is_file():
            failures.append(f'Sitemap index target missing: {value}')
        else:
            yield target


def sitemap_locations(output, base, path, failures):
    pending, seen, urls = [path.resolve()], set(), []
    while pending:
        current = pending.pop()
        if current in seen:
            failures.append(f'Duplicate or cyclic sitemap index target: {current}')
            continue
        seen.add(current)
        kind, values = sitemap_document(current)
        if kind == 'sitemapindex':
            pending.extend(sitemap_index_targets(output, base, values, failures))
        elif kind == 'urlset':
            urls.extend(values)
        else:
            failures.append(f'Unsupported sitemap document: {kind}')
    return urls


def validate_sitemap(output, base, plan, failures):
    urls = sitemap_locations(output, base, output / plan.sitemap_path, failures)
    if len(urls) != len(set(urls)):
        failures.append('Duplicate sitemap URLs')
    if set(urls) != plan.sitemap_urls:
        failures.append('Sitemap URL set does not match publication plan')
    canonicals = {(output / name).resolve(): url for name, url in plan.page_urls.items()}
    for url in urls:
        target = local_path(output, url, base)
        if target not in canonicals or canonicals[target] != url:
            failures.append(f'Sitemap target missing or noncanonical: {url}')
    return len(urls)


def validate_site(output, base: str, plan: ValidationPlan, *, html_errors=None):
    """Borrow the stable output/plan during validation; return only scalar counts."""
    output = output.resolve()
    base = base.rstrip('/')
    failures = []
    pages = read_pages(output, failures, html_errors)
    validate_pages(output, base, plan, pages, failures)
    search = validate_search(output, plan, failures)
    sitemap = validate_sitemap(output, base, plan, failures)
    if failures:
        raise ValueError('\n'.join(failures))
    return ValidationResult(len(pages), search, sitemap)

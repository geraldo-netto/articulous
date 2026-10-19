"""Local output byte accounting; gzip values are estimates, not HTTP evidence."""
import gzip
from collections import Counter
from pathlib import Path
from typing import TypedDict

from lxml import html


class OutputMetrics(TypedDict):
    extensions: Counter[str]
    sections: Counter[str]
    regions: Counter[str]
    region_pages: Counter[str]
    recipes: Counter[str]
    sizes: list[int]
    raw: int
    gzip: int
    class_bytes: int


def megabytes(value: int) -> str:
    return f'{value/1048576:.1f} MB'


def _class_metrics(document, metrics: OutputMetrics):
    for element in document.iter():
        value = element.get('class')
        if value:
            size = len(value.encode('utf-8'))
            metrics['class_bytes'] += size
            if size >= 40:
                metrics['recipes'][value] += 1


def scan(output: Path, *, regions=()) -> OutputMetrics:
    """Accumulate counters in one pass, retaining no page bytes or DOMs."""
    metrics: OutputMetrics = {
        'extensions': Counter(), 'sections': Counter(), 'regions': Counter(),
        'region_pages': Counter(), 'recipes': Counter(), 'sizes': [],
        'raw': 0, 'gzip': 0, 'class_bytes': 0,
    }
    for path in output.rglob('*'):
        if not path.is_file():
            continue
        size = path.stat().st_size
        metrics['extensions'][path.suffix or 'none'] += size
        metrics['sections'][path.relative_to(output).parts[0]] += size
        if path.suffix != '.html':
            continue
        raw = path.read_bytes()
        metrics['sizes'].append(len(raw))
        metrics['raw'] += len(raw)
        metrics['gzip'] += len(gzip.compress(raw, 6))
        if not raw.strip():
            continue
        document = html.fromstring(raw)
        for label, selector in regions:
            found = document.xpath(selector)
            if found:
                metrics['regions'][label] += sum(len(html.tostring(e, encoding='utf-8')) for e in found)
                metrics['region_pages'][label] += 1
        _class_metrics(document, metrics)
    return metrics


def overall(metrics: OutputMetrics) -> None:
    by_extension, by_section = metrics['extensions'], metrics['sections']
    print(f'output total {megabytes(sum(by_extension.values()))}')
    print('  by type:    ' + ', '.join(f'{e}={megabytes(s)}' for e, s in by_extension.most_common(5)))
    print('  by section: ' + ', '.join(f'{d}={megabytes(s)}' for d, s in by_section.most_common(6)))
    raw, estimated_gzip = metrics['raw'], metrics['gzip']
    sizes = sorted(metrics['sizes'], reverse=True)
    print(f'\n{len(sizes)} pages: {megabytes(raw)} raw, {megabytes(estimated_gzip)} estimated gzip '
          f'({estimated_gzip/raw if raw else 0:.0%} of raw)')
    if sizes:
        print(f'  median {sizes[len(sizes)//2]/1024:.0f} KB, largest {sizes[0]/1024:.0f} KB')


def repeated_markup(metrics: OutputMetrics) -> None:
    """What each repeated region costs across the whole site."""
    print('\nreserialized UTF-8 blocks, summed over every page that carries one:')
    for label, size in metrics['regions'].most_common():
        print(f'  {label:22} {megabytes(size):>9}  on {metrics["region_pages"][label]} pages')


def class_weight(metrics: OutputMetrics) -> None:
    """Class attributes are the usual hidden cost: the same recipe, everywhere."""
    total, spent, repeats = metrics['raw'], metrics['class_bytes'], metrics['recipes']
    print(f'\nclass attributes: {megabytes(spent)} of {megabytes(total)} ({spent/total if total else 0:.0%})')
    if repeats:
        print('  longest recipes still spelled out in the markup:')
        def recipe_weight(item):
            return -len(item[0].encode('utf-8')) * item[1]
        for value, count in sorted(repeats.items(), key=recipe_weight)[:5]:
            size = len(value.encode('utf-8'))
            print(f'    {size:4}b x {count:6} = {megabytes(size*count):>8}  {value[:52]}...')


def one_page(path: Path, *, regions=()) -> None:
    raw = path.read_bytes()
    if not raw.strip():
        print(f'{path}: empty HTML file')
        return
    document = html.fromstring(raw)
    print(f'{path}: {len(raw)/1024:.0f} KB raw, {len(gzip.compress(raw, 6))/1024:.0f} KB estimated gzip')
    for label, selector in regions:
        size = sum(len(html.tostring(e, encoding='utf-8')) for e in document.xpath(selector))
        if size:
            print(f'   {label:22} {size/1024:7.1f} KB  {size/len(raw):5.0%}')



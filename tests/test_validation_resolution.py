"""PERF-017: validation-scoped resolution, with fresh identities on each call."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch
from articulous import site_validation as validation
from articulous.validation_contracts import ValidationPlan


class ResolutionScope(unittest.TestCase):
    def setUp(self):
        owner = tempfile.TemporaryDirectory()
        self.addCleanup(owner.cleanup)
        self.root = Path(owner.name)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.base = 'https://example.test'
        self.page('<a href="target.html#anchor">target</a>' * 100)
        (self.output / 'target.html').write_text(
            '<html><head><link rel="canonical" href="https://example.test/target.html"></head>'
            '<body><p id="anchor">Target</p></body></html>')
        (self.output / 'search.json').write_text('[]')
        (self.output / 'sitemap.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>')
        self.plan = ValidationPlan({'index.html': self.base + '/', 'target.html': self.base + '/target.html'},
                                   frozenset(), frozenset(), 'search.json', 'sitemap.xml', {})

    def page(self, body):
        (self.output / 'index.html').write_text(
            '<html><head><link rel="canonical" href="https://example.test/"></head><body>'
            + body + '</body></html>')

    def test_perf017_each_resolved_url_is_computed_once(self):
        with patch.object(validation, 'local_path', wraps=validation.local_path) as resolve:
            result = validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(2, result.html_pages)
        self.assertEqual(2, resolve.call_count, 'PERF-017 repeated target resolution')

    def test_perf017_diagnostics_remain_per_reference(self):
        self.page('<base href="https://example.test/"><a href="target.html?x=1#missing">bad</a>' * 2)
        with self.assertRaises(ValueError) as failure:
            validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(2, str(failure.exception).count('missing fragment'))

    def test_perf017_new_validation_rechecks_symlink_containment(self):
        link = self.output / 'link.html'
        link.symlink_to(self.output / 'target.html')
        self.page('<a href="link.html#anchor">target</a>')
        validation.validate_site(self.output, self.base, self.plan)
        link.unlink()
        outside = self.root / 'outside.html'
        outside.write_text('outside')
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes output'):
            validation.validate_site(self.output, self.base, self.plan)

    def test_perf017_failed_validation_does_not_retain_cache(self):
        retained = []
        original = validation.validate_pages

        def failed(*args):
            original(*args)
            retained.append(args[-1])
            raise KeyboardInterrupt

        with patch.object(validation, 'validate_pages', failed), self.assertRaises(KeyboardInterrupt):
            validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual([{}], retained)

    def test_perf18_fragment_and_query_variants_share_the_path(self):
        source = ''.join(f'<a href="target.html?view={index}#anchor">target</a>' for index in range(100))
        self.page(source)
        with patch.object(validation, 'local_path', wraps=validation.local_path) as resolve:
            validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(2, resolve.call_count)

    def test_review28_43_redirect_target_checked_once_across_query_and_fragment_variants(self):
        self.plan.redirects['/old.html'] = '/target.html'
        links = ('old.html#anchor', 'old.html#absent', 'old.html#',
                 'old.html?variant=1#missing', 'old.html#absent')
        self.page(''.join(f'<a href="{link}">link</a>' for link in links))
        with patch.object(Path, 'is_file', autospec=True, side_effect=Path.is_file) as exists:
            with self.assertRaises(ValueError) as failure:
                validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(str(failure.exception).splitlines(), [
            'index.html: missing fragment old.html#absent',
            'index.html: missing fragment old.html?variant=1#missing',
            'index.html: missing fragment old.html#absent',
        ])
        self.assertLessEqual(exists.call_args_list.count(call(self.output / 'target.html')), 2)

    def test_review28_43_missing_target_rechecked_on_next_validation(self):
        self.page('<img src="picture.png#x"><img src="picture.png#y">')
        with patch.object(Path, 'is_file', autospec=True, side_effect=Path.is_file) as exists:
            with self.assertRaises(ValueError) as failure:
                validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(str(failure.exception).splitlines(), [
            'index.html: missing picture.png#x', 'index.html: missing picture.png#y',
        ])
        self.assertEqual(exists.call_args_list.count(call(self.output / 'picture.png')), 1)
        (self.output / 'picture.png').touch()
        validation.validate_site(self.output, self.base, self.plan)

    def test_review28_43_aborted_validation_releases_link_cache(self):
        retained = []
        original = validation.check_link

        def interrupt(output, value, page_url, base, redirects, *rest):
            original(output, value, page_url, base, redirects, *rest)
            self.assertTrue(redirects.links)
            retained.append(redirects.links)
            raise KeyboardInterrupt

        with patch.object(validation, 'check_link', interrupt), self.assertRaises(KeyboardInterrupt):
            validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(retained, [{}])

    def test_review28_43_redirect_outcomes_remain_per_link_and_in_order(self):
        self.plan.redirects.update({
            '/replace': '/target.html#missing',
            '/clear': '/next#',
            '/next': '/target.html',
            '/cycle': '/cycle',
        })
        links = ('/replace#anchor', '/clear#absent', '/cycle#one', '/cycle#two', '/replace#top')
        self.page(''.join(f'<a href="{link}">link</a>' for link in links))
        with self.assertRaises(ValueError) as failure:
            validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(str(failure.exception).splitlines(), [
            'index.html: missing fragment /replace#anchor',
            'index.html: redirect loop for /cycle',
            'index.html: redirect loop for /cycle',
            'index.html: missing fragment /replace#top',
        ])

    def test_audit1121_21_reuses_only_successful_page_independent_links(self):
        body = '<a href="/target.html#anchor">good</a><a href="/target.html#absent">bad</a>'
        self.page(body)
        (self.output / 'other.html').write_text(
            f'<link rel="canonical" href="{self.base}/other.html">{body}')
        self.plan.page_urls['other.html'] = self.base + '/other.html'
        with patch.object(validation, 'check_link', wraps=validation.check_link) as check:
            with self.assertRaises(ValueError) as failure:
                validation.validate_site(self.output, self.base, self.plan)
        checked = [args[1] for args, _ in check.call_args_list]
        self.assertEqual(checked.count('/target.html#anchor'), 1)
        self.assertEqual(checked.count('/target.html#absent'), 2)
        self.assertEqual(str(failure.exception).count('missing fragment'), 2)

    def test_audit1121_21_eviction_and_base_dependent_references(self):
        self.page('<p id="first"></p><a href="#first">self</a><a href="//">page</a>'
                  '<a href="/target.html#anchor">one</a><a href="/search.json">two</a>'
                  '<a href="/target.html#anchor">one</a>')
        (self.output / 'second.html').write_text(
            f'<link rel="canonical" href="{self.base}/second.html"><a href="#first">missing</a>')
        self.plan.page_urls['second.html'] = self.base + '/second.html'
        with patch.object(validation, '_MAX_VERIFIED_LINKS', 1):
            with self.assertRaises(ValueError) as failure:
                validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(str(failure.exception), 'second.html: missing fragment #first')

    def test_audit1121_21_explicit_base_never_shares_default_base_results(self):
        self.page('<base href="https://elsewhere.test/"><img src="/absent.png">')
        (self.output / 'second.html').write_text(
            f'<link rel="canonical" href="{self.base}/second.html"><img src="/absent.png">')
        self.plan.page_urls['second.html'] = self.base + '/second.html'
        with self.assertRaises(ValueError) as failure:
            validation.validate_site(self.output, self.base, self.plan)
        self.assertEqual(str(failure.exception), 'second.html: missing /absent.png')

    def test_audit1121_23_parallel_extraction_keeps_callbacks_on_caller(self):
        import threading
        pages = 80
        for index in range(pages):
            (self.output / f'p{index:02}.html').write_text(f'<p>{index}</p>')
        caller = threading.get_ident()
        parsing_threads = set()
        observed = []
        parser = validation.html.fromstring

        def parse(*args, **kwargs):
            parsing_threads.add(threading.get_ident())
            return parser(*args, **kwargs)

        def inspect_source(source):
            self.assertEqual(caller, threading.get_ident())
            observed.append(source)
            return []

        with patch.object(validation, 'available_cpus', return_value=2), patch.object(validation.html, 'fromstring', parse):
            refs = validation.read_pages(self.output, [], inspect_source)
        self.assertEqual(observed, [p.read_bytes() for p in sorted(self.output.glob('*.html'))])
        self.assertEqual(len(refs), pages + 2)
        self.assertNotIn(caller, parsing_threads)

    def test_audit1121_23_parallel_and_serial_preserve_diagnostic_order(self):
        for index in range(65):
            (self.output / f'e{index:02}.html').write_bytes(b'' if index % 3 == 0 else b'<p>ok</p>')
        def warnings(source):
            return ['empty source'] if not source else []
        def inspect(cpus):
            failures = []
            with patch.object(validation, 'available_cpus', return_value=cpus):
                pages = validation.read_pages(self.output, failures, warnings)
            return list(pages.items()), failures
        serial, parallel = inspect(1), inspect(2)
        self.assertEqual(serial, parallel)
        self.assertIn('empty source', parallel[1][0])
        self.assertIn('Document is empty', parallel[1][1])

    def test_audit1121_23_workers_settle_when_checker_raises(self):
        import threading
        for index in range(65):
            (self.output / f'p{index:02}.html').write_bytes(b'<p>ok</p>')
        workers = set()
        parse_batch = validation._parse_batch
        def observe(*args):
            workers.add(threading.current_thread())
            return parse_batch(*args)
        def cancel(_):
            raise KeyboardInterrupt
        with patch.object(validation, 'available_cpus', return_value=2), patch.object(validation, '_parse_batch', observe):
            with self.assertRaises(KeyboardInterrupt):
                validation.read_pages(self.output, [], cancel)
        self.assertTrue(workers)
        self.assertFalse(any(worker.is_alive() for worker in workers))

    def test_audit1121_23_batches_bound_bytes_and_keep_oversize_pages_whole(self):
        sizes = (1, 1024 * 1024 - 1, 2, 1024 * 1024 + 1, 0)
        values = [validation._PageRead(self.output, source=bytes(size)) for size in sizes]
        batches = list(validation._page_batches(values))
        self.assertEqual(batches, [values[:2], values[2:3], values[3:4], values[4:]])
        self.assertEqual(list(validation._page_batches([])), [])

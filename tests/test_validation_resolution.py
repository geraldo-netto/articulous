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

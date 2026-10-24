"""ARCH-004: immutable preparation, bounded readers and validation before publication."""
from dataclasses import replace
import random
from unittest.mock import Mock

import pytest

from articulous.builds import (
    Diagnostic, check_build, prepare_build, render_prepared, validate_generated,
)
from articulous.pipeline import run_build
from articulous.publication import publish_validated
from articulous.transform_contracts import TransformFailure
from test_composition import page


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_arch004_preparation_snapshot_and_cleanup(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    previous = snapshot(site_root / 'output')
    cache = (site_root / '.build-cache.json').read_bytes()
    with prepare_build(cli, config, site_root, extra_pages=[page(config)]) as prepared:
        assert len(prepared.routes) > 0
        (site_root / 'assets/style.css').write_text('changed after preparation')
        (site_root / 'content/en/first-post.xml').write_text('<broken')
        (site_root / 'xsl/pages/index.xsl').write_text('<broken')
        staged = render_prepared(prepared)
        with staged.open_artifact('assets/style.css') as source:
            assert source.read() == previous['assets/style.css']
        validated = validate_generated(staged)
        validated.assert_unchanged()
        assert snapshot(site_root / 'output') == previous
        assert (site_root / '.build-cache.json').read_bytes() == cache
    assert not staged.root.exists()
    with pytest.raises(ValueError, match='closed'):
        validated.assert_unchanged()


@pytest.mark.parametrize('field', ['only_sections', 'only_langs', 'only_slugs'])
def test_arch004_rejects_partial_builds_before_staging(site_root, seo_config, field):
    cli, config = seo_config
    setattr(cli, field, ['en'])
    with pytest.raises(ValueError, match='unfiltered'):
        with prepare_build(cli, config, site_root):
            pytest.fail('partial build accepted')
    assert not list(site_root.glob('.articulous-stage-*'))


def test_arch004_validation_diagnostics_and_mutation(site_root, seo_config):
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        warning = Diagnostic('Optional metadata absent', 'warning', 'index.html')
        result = validate_generated(staged, validators=[lambda _: [warning]])
        assert result.diagnostics == (warning,)
        (staged.root / 'rss.xml').write_text('changed')
        with pytest.raises(ValueError, match='changed'):
            result.assert_unchanged()
    assert not (site_root / 'output').exists()


def test_arch004_errors_and_bad_lifecycle(site_root, seo_config):
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        with pytest.raises(ValueError, match='state'):
            render_prepared(prepared)
        with pytest.raises(ValueError, match='missing canonical'):
            validate_generated(staged, validators=[lambda _: [Diagnostic('missing canonical')]])
    with pytest.raises(ValueError, match='severity'):
        Diagnostic('bad', 'other')


@pytest.mark.parametrize('failure', [
    [Diagnostic('API-004 rejected')], ValueError('API-004 callback failed'),
    ['malformed diagnostic'], 42,
])
def test_api004_revalidation_revokes_prior_handle(site_root, seo_config, failure):
    cli, config = seo_config
    validator = Mock(return_value=failure)
    if isinstance(failure, Exception):
        validator.side_effect = failure
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        prior = validate_generated(staged)
        with pytest.raises(ValueError):
            validate_generated(staged, validators=[validator])
        with pytest.raises(ValueError):
            publish_validated(prior)
        assert not (site_root / 'output').exists()
        fresh = validate_generated(staged)
        with pytest.raises(ValueError):
            prior.assert_unchanged()
        publish_validated(fresh)
        assert (site_root / 'output/rss.xml').is_file()


def test_api004_artifact_rejection_revokes_handle_after_restoration(site_root, seo_config):
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        prior = validate_generated(staged)
        artifact = staged.root / 'rss.xml'
        original = artifact.read_bytes()
        artifact.write_bytes(b'changed')
        with pytest.raises(ValueError, match='changed'):
            validate_generated(staged)
        artifact.write_bytes(original)
        with pytest.raises(ValueError):
            prior.assert_unchanged()
        validate_generated(staged).assert_unchanged()


@pytest.mark.parametrize('seed', range(24))
def test_arch004_artifact_path_fuzz(site_root, seo_config, seed):
    cli, config = seo_config
    value = random.Random(seed).choice(['../config.json', '/etc/passwd', 'assets/../rss.xml', 'a\\b', '', 'a//b'])
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        with pytest.raises(ValueError, match='artifact'):
            with staged.open_artifact(value):
                pytest.fail('unsafe path accepted')


def test_arch004_validator_exception_and_modification(site_root, seo_config):
    cli, config = seo_config
    run_build(cli, config, site_root)
    previous = snapshot(site_root / 'output')
    cache = (site_root / '.build-cache.json').read_bytes()
    def failing(staged):
        raise RuntimeError('validator failed')
    with pytest.raises(RuntimeError, match='validator failed'):
        check_build(cli, config, site_root, validators=[failing])
    def mutate(staged):
        (staged.root / 'new.html').write_text('unvalidated')
    with pytest.raises(ValueError, match='changed'):
        check_build(cli, config, site_root, validators=[mutate])
    assert snapshot(site_root / 'output') == previous
    assert (site_root / '.build-cache.json').read_bytes() == cache


def test_arch004_render_failure_and_lock_release(site_root, seo_config):
    cli, config = seo_config
    invalid = replace(page(config), model=b'<broken')
    with pytest.raises(TransformFailure, match='Start Tag'):
        check_build(cli, config, site_root, extra_pages=[invalid])
    assert check_build(cli, config, site_root).routes > 0
    with prepare_build(cli, config, site_root):
        with pytest.raises(FileExistsError):
            with prepare_build(cli, config, site_root):
                pytest.fail('concurrent writer accepted')


@pytest.mark.parametrize('relative', [None, 42, ['file'], 'C:/file'])
def test_arch004_invalid_artifact_values(site_root, seo_config, relative):
    cli, config = seo_config
    with prepare_build(cli, config, site_root) as prepared:
        staged = render_prepared(prepared)
        with pytest.raises(ValueError, match='artifact'):
            with staged.open_artifact(relative):
                pytest.fail('invalid value accepted')


def test_arch004_rejects_symlink_output(site_root, seo_config):
    cli, config = seo_config
    target = site_root / 'external'
    target.mkdir()
    (site_root / 'output').symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        check_build(cli, config, site_root)
    assert list(target.iterdir()) == []


def test_arch004_invalid_configuration_and_extra_values(site_root, seo_config):
    cli, _ = seo_config
    with pytest.raises(ValueError, match='Configuration'):
        check_build(cli, None, site_root)
    with pytest.raises(ValueError, match='ExtraPage'):
        check_build(cli, {}, site_root, extra_pages=['invalid'])


def test_arch005_workspace_swap_never_deletes_replacement(site_root, seo_config):
    cli, config = seo_config
    replacements = []
    def swap(staged):
        workspace = staged.root.parent
        workspace.rename(site_root / 'original-stage')
        workspace.mkdir()
        manual = workspace / 'manual.txt'
        manual.write_text('keep replacement')
        replacements.append(manual)
        raise RuntimeError('validator failed after swap')
    with pytest.raises(RuntimeError, match='validator failed after swap'):
        check_build(cli, config, site_root, validators=[swap])
    assert replacements[0].read_text() == 'keep replacement'
    assert (site_root / 'original-stage/output/rss.xml').exists()

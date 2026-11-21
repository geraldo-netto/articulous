"""ARCH-008: normalized membership and immutable cached language projections."""
from dataclasses import dataclass

import pytest

from articulous.article_contracts import PublicationPolicy
from articulous.catalogue import PublicationCatalogue, TagCount, normalized_tag_counts


@dataclass(frozen=True)
class Metadata:
    lang: str
    tags: tuple[str, ...]
    policy: PublicationPolicy


def article(language='en', listed=True):
    return Metadata(language, ('C++', 'C#', 'C++', '!!!'),
                    PublicationPolicy(True, listed, listed, listed, listed))


def test_arch008_normalized_membership_and_cached_views():
    first = article()
    catalogue = PublicationCatalogue([first, first, article(listed=False)], ['en', 'es'])
    assert catalogue.tag_counts('en') == (TagCount('c', 2, 'C++'),)
    assert catalogue.tag_counts('en') is catalogue.tag_counts('en')
    assert catalogue.tag_counts('es') == ()
    assert catalogue.articles[0] is first
    with pytest.raises(ValueError, match='disabled'):
        catalogue.tag_counts('fr')


@pytest.mark.parametrize('languages', ['en', b'en', [], ['en', 'en'], [''], [42], ['en', ' ']])
def test_arch008_invalid_language_collections(languages):
    with pytest.raises(ValueError):
        PublicationCatalogue([], languages)


@pytest.mark.parametrize('articles', ['bad', b'bad', {}, [None], [article('disabled')]])
def test_arch008_invalid_article_collections(articles):
    with pytest.raises(ValueError):
        PublicationCatalogue(articles, ['en'])


@pytest.mark.parametrize('codes', [('en', 'EN'), ('pt-BR', 'pt-br'), ('a/b',), ('en us',), ('日本語',)])
def test_audit1121_13_catalogue_uses_shared_language_identity(codes):
    with pytest.raises(ValueError, match='Catalogue languages'):
        PublicationCatalogue([], iter(codes))
    valid = ('en', 'PT-br', 'x_CA', 'a1')
    catalogue = PublicationCatalogue([], iter(valid))
    assert [catalogue.tag_counts(code) for code in valid] == [()] * len(valid)


def test_audit1121_16_counts_each_record_in_one_language_pass():
    visits = []
    class Observed:
        tags = ('C++', 'C#')
        policy = PublicationPolicy(True, True, True, True, True)

        @property
        def lang(self):
            visits.append('en')
            return 'en'

    records = (Observed(),) * 32
    catalogue = PublicationCatalogue(records, ('en', 'de'))
    assert catalogue.tag_counts('en') == (TagCount('c', len(records), 'C++'),)
    assert catalogue.tag_counts('de') == ()
    assert len(visits) == len(records)

    assert normalized_tag_counts([article('de'), article(), article(listed=False)], 'en') == (TagCount('c', 1, 'C++'),)

"""REVIEW-019: failed schema setup settles the newly owned connection."""
from unittest.mock import Mock

import pytest

from articulous import translations


@pytest.mark.parametrize('step', range(3))
@pytest.mark.parametrize('failure', [RuntimeError('setup'), KeyboardInterrupt()])
def test_review019_failed_setup_closes_connection(monkeypatch, step, failure):
    connection = Mock()
    connection.execute.side_effect = [Mock() for _ in range(step)] + [failure]
    monkeypatch.setattr(translations.sqlite3, 'connect', Mock(return_value=connection))
    with pytest.raises(type(failure)) as caught:
        translations.TranslationStore()
    assert caught.value is failure
    connection.close.assert_called_once_with()


def test_review019_setup_releases_cursors_and_keeps_connection(monkeypatch):
    connection = Mock()
    cursors = [Mock() for _ in range(3)]
    connection.execute.side_effect = cursors
    monkeypatch.setattr(translations.sqlite3, 'connect', Mock(return_value=connection))
    store = translations.TranslationStore()
    connection.close.assert_not_called()
    for cursor in cursors:
        cursor.close.assert_called_once_with()
    store.close()
    connection.close.assert_called_once_with()

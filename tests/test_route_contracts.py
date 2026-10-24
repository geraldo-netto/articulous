"""API-003: storage-free composition contracts and bounded catalog borrows."""
import subprocess
import sys
from unittest.mock import Mock

import pytest

from articulous import composition


def test_api003_contract_import_excludes_storage_and_native_adapters():
    script = '''
import sys
sys.modules['sqlite3'] = None
sys.modules['fcntl'] = None
from articulous.extensions import CapturedSite, BuildComposition
from articulous.composition_contracts import Route, RouteReader, RouteWriter
assert 'articulous.composition' not in sys.modules
assert 'articulous.pipeline' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_api003_catalog_closes_active_readers_before_storage():
    from articulous.composition_contracts import Route
    catalog = composition.RouteCatalog()
    route = Route('page:about', 'pages', '/about/', 'about/index.html')
    catalog.record(route)
    catalog.record(Route('page:other', 'pages', '/other/', 'other/index.html'))
    reader = iter(catalog)
    assert next(reader) == route
    catalog.close()
    with pytest.raises(ValueError, match='closed'):
        next(reader)
    with pytest.raises(ValueError, match='closed'):
        len(catalog)
    with pytest.raises(ValueError, match='closed'):
        list(catalog)
    with pytest.raises(ValueError, match='closed'):
        catalog.record(route)
    catalog.close()


def test_api003_failed_catalog_initialization_closes_connection(monkeypatch):
    connection = Mock()
    connection.execute.side_effect = RuntimeError('database setup failed')
    monkeypatch.setattr(composition.sqlite3, 'connect', Mock(return_value=connection))
    with pytest.raises(RuntimeError, match='setup failed'):
        composition.RouteCatalog()
    connection.close.assert_called_once_with()


def test_api003_reader_admission_failure_closes_unregistered_cursor():
    catalog = composition.RouteCatalog.__new__(composition.RouteCatalog)
    catalog._closed = False
    catalog._db = Mock()
    catalog._readers = Mock()
    catalog._readers.add.side_effect = MemoryError('reader admission failed')
    cursor = catalog._db.execute.return_value
    with pytest.raises(MemoryError, match='admission failed'):
        catalog._reader()
    cursor.close.assert_called_once_with()

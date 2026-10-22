"""Offline guard checks for the consolidated source map; no application startup."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest

path = Path(__file__).resolve().parents[2] / 'scripts/verify_published_sources.py'
spec = importlib.util.spec_from_file_location('published_sources', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_published_sources_match():
    result = module.verify()
    assert result['application_files'] == 451
    assert result['outer_files'] == 5
    assert result['remote_tests_executed'] is False


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'C:/private', 'a\\b'])
def test_paths_cannot_escape(name):
    with pytest.raises(ValueError, match='UNSAFE_CORRESPONDENCE_PATH'):
        module.checked_path(name)


def test_real_hash_difference_still_blocks():
    with patch.object(module, 'sha', return_value='0' * 64):
        with pytest.raises(ValueError, match='SOURCE_CORRESPONDENCE_DIFFERS'):
            module.verify()

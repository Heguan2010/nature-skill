"""Regression tests for the stand-alone converter scripts (no network access)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, filename: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


converters = _load("nature_search_converters", "converters.py")
format_converter = _load("nature_search_format_converter", "format-converter.py")


def test_format_converter_imports_urlopen_for_real_downloads():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"PMID- 1\n"
    with patch.object(format_converter, "urlopen", return_value=response) as opened:
        assert format_converter.efetch_medline("1") == "PMID- 1\n"
    opened.assert_called_once()

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/nature-figure/scripts"


def load_module(name: str, filename: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PlotTemplatePathTests(unittest.TestCase):
    def test_dotted_prefix_is_not_clipped(self) -> None:
        try:
            module = load_module("plot_templates_regression", "plot_templates.py")
        except ImportError as exc:  # matplotlib/numpy are optional in minimal CI
            self.skipTest(str(exc))
        for prefix in ("Fig.2", "fig2.v3"):
            path = module.with_extension(Path("out") / prefix, ".svg")
            self.assertEqual(path.name, prefix + ".svg")
        self.assertNotEqual(
            module.with_extension(Path("Fig.2"), ".pdf"), module.with_extension(Path("Fig.3"), ".pdf")
        )


if __name__ == "__main__":
    unittest.main()

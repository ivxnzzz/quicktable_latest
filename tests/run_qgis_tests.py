"""Run the suite with QGIS's Python, using isolated settings and offscreen Qt."""

import os
from pathlib import Path
import sys
import unittest
import tempfile

root = Path(__file__).resolve().parents[1]
temporary_profile = tempfile.TemporaryDirectory(prefix="quicktable-qgis-", ignore_cleanup_errors=True)
profile = Path(temporary_profile.name)
if os.environ.get("QUICKTABLE_REQUIRE_POSTGIS") == "1" and not os.environ.get("QUICKTABLE_TEST_POSTGIS_URI"):
    raise SystemExit("PostGIS is required but QUICKTABLE_TEST_POSTGIS_URI is missing")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = str(profile)
if os.name == "nt":
    os.environ["QT_QPA_FONTDIR"] = str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
sys.path.insert(0, str(root))

from qgis.PyQt.QtCore import QSettings

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(profile))
suite = unittest.defaultTestLoader.discover(str(root / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
unexpected_skips = [(test, reason) for test, reason in result.skipped
                    if reason != "PostGIS test connection not configured"
                    or os.environ.get("QUICKTABLE_REQUIRE_POSTGIS") == "1"]
if unexpected_skips:
    print("Required tests were skipped:", unexpected_skips, file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and result.testsRun and not unexpected_skips else 1)

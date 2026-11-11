"""Run the suite with QGIS's Python, using isolated settings and offscreen Qt."""

import argparse
import os
from pathlib import Path
import sys
import unittest
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--skip-postgis', action='store_true',
                    help='Exclude the live PostGIS test (used by online CI).')
args = parser.parse_args()
if args.skip_postgis and os.environ.get('QUICKTABLE_REQUIRE_POSTGIS') == '1':
    parser.error('--skip-postgis conflicts with QUICKTABLE_REQUIRE_POSTGIS=1')

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


class QgisTestLoader(unittest.TestLoader):
    def getTestCaseNames(self, test_case_class):
        names = super().getTestCaseNames(test_case_class)
        if args.skip_postgis:
            names = [name for name in names
                     if name != 'test_real_postgis_schema_edits_constraints_and_reopen']
        return names


if args.skip_postgis:
    print('Live PostGIS test excluded (--skip-postgis).', flush=True)
suite = QgisTestLoader().discover(str(root / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
unexpected_skips = [(test, reason) for test, reason in result.skipped
                    if reason != "PostGIS test connection not configured"
                    or os.environ.get("QUICKTABLE_REQUIRE_POSTGIS") == "1"]
if unexpected_skips:
    print("Required tests were skipped:", unexpected_skips, file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and result.testsRun and not unexpected_skips else 1)

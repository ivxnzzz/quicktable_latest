"""Run the suite with QGIS's Python, using isolated settings and offscreen Qt."""

import os
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
profile = root / ".qgis-test-profile"
profile.mkdir(exist_ok=True)
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
sys.exit(0 if result.wasSuccessful() else 1)

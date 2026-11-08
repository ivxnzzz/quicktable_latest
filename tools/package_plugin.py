"""Build and verify the QGIS plugin ZIP using an explicit runtime file list."""

import configparser
import os
from pathlib import Path
import re
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "quicktable_latest"
FILES = (
    "__init__.py",
    "quicktable/__init__.py",
    "quicktable/layer_filter.py",
    "quicktable/compact_filters.py",
    "quicktable/filter_widgets.py",
    "quicktable/filter_utils.py",
    "quicktable/filter_logic.py",
    "quicktable/pagination.py",
    "metadata.txt",
    "README.md",
    "LICENSE",
    "icons/icon.png",
    "icons/check_dark.svg",
    "icons/check_light.svg",
    "icons/down_dark.svg",
    "icons/down_light.svg",
    "icons/up_dark.svg",
    "icons/up_light.svg",
)
MAX_SIZE = 25_000_000


def build():
    metadata = configparser.ConfigParser()
    metadata.read(ROOT / "metadata.txt", encoding="utf-8")
    general = metadata["general"]
    required = (
        "name", "qgisMinimumVersion", "description", "about", "version",
        "author", "email", "homepage", "repository", "tracker", "icon",
    )
    missing = [key for key in required if not general.get(key, "").strip()]
    if missing:
        raise ValueError("Missing metadata: " + ", ".join(missing))
    version = general["version"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise ValueError("Expected a numeric dotted release version")
    if general["icon"] not in FILES:
        raise ValueError("Metadata icon is not included in the package")
    for name in FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(ROOT / name)

    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    destination = output / (PACKAGE + "-" + version + ".zip")
    # Validate a temporary archive before replacing a previous good release.
    # Create the temporary file directly in dist so the finished ZIP inherits
    # its permissions. Moving a file out of a private temporary directory can
    # retain an owner-only Windows ACL and prevent QGIS from reading it.
    descriptor, temporary = tempfile.mkstemp(prefix="package-", suffix=".zip", dir=output)
    os.close(descriptor)
    candidate = Path(temporary)
    try:
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in FILES:
                archive.write(ROOT / name, PACKAGE + "/" + name)
        if candidate.stat().st_size > MAX_SIZE:
            raise ValueError("Release ZIP exceeds the 25 MB limit")
        with zipfile.ZipFile(candidate) as archive:
            expected = [PACKAGE + "/" + name for name in FILES]
            if archive.namelist() != expected:
                raise ValueError("Unexpected archive contents")
            corrupt = archive.testzip()
            if corrupt:
                raise ValueError("Corrupt archive member: " + corrupt)
            for name in FILES:
                if archive.read(PACKAGE + "/" + name) != (ROOT / name).read_bytes():
                    raise ValueError("Packaged file differs from source: " + name)
        candidate.replace(destination)
    finally:
        candidate.unlink(missing_ok=True)
    print("Created {} ({} files, {:,} bytes)".format(
        destination, len(FILES), destination.stat().st_size))
    print("Verified archive structure, metadata, integrity and source equality.")
    return destination


if __name__ == "__main__":
    build()

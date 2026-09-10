"""Source downloads must be identical on developer machines and Linux CI."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

import package_sdks


class SDKArchiveTests(unittest.TestCase):
    def test_archives_are_portable_and_exclude_build_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend/public/downloads").mkdir(parents=True)
            for language in ("python", "javascript"):
                source = root / "sdk" / language
                source.mkdir(parents=True)
                # Mixed case catches Windows Path ordering versus Linux ordering.
                for name, data in {
                    "README.md": b"Install\r\n",
                    "LICENSE": b"License\r\n",
                    "example.py": b"print('example')\r\n",
                    "MANIFEST.in": b"include LICENSE\r\n",
                    "client/py.typed": b"",
                    "client/index.ts": b"export {};\r\n",
                    "build/generated.py": b"build output",
                    "dist/generated.js": b"build output",
                    "oreag_sdk.egg-info/PKG-INFO": b"build metadata",
                    "node_modules/dependency/index.js": b"dependency",
                    "__pycache__/cached.py": b"cache",
                    ".env": b"not for distribution",
                }.items():
                    file = source / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(data)

            def build_for_platform(platform):
                def zip_info(*args, **kwargs):
                    info = ZipInfo(*args, **kwargs)
                    info.create_system = platform
                    return info

                with patch.object(package_sdks, "ROOT", root), \
                     patch.object(package_sdks, "ZipInfo", side_effect=zip_info), \
                     contextlib.redirect_stdout(io.StringIO()):
                    package_sdks.build()
                return {
                    file.name: file.read_bytes()
                    for file in (root / "frontend/public/downloads").glob("*.zip")
                }

            windows = build_for_platform(0)
            linux = build_for_platform(3)
            self.assertEqual(windows, linux)
            self.assertEqual(len(linux), 2)
            for data in linux.values():
                with ZipFile(io.BytesIO(data)) as archive:
                    names = archive.namelist()
                    relative = [name.split("/", 1)[1] for name in names]
                    self.assertEqual(relative, [
                        "LICENSE", "MANIFEST.in", "README.md",
                        "client/index.ts", "client/py.typed", "example.py",
                    ])
                    self.assertIsNone(archive.testzip())
                    for info in archive.infolist():
                        self.assertEqual(info.create_system, 3)
                        self.assertEqual(info.external_attr >> 16, 0o644)
                        self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))
                        self.assertNotIn(b"\r\n", archive.read(info))


if __name__ == "__main__":
    unittest.main()

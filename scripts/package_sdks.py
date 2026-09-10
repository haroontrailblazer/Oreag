"""Build reproducible source SDK downloads without caches or credentials."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def build():
    output = ROOT / "frontend/public/downloads"
    output.mkdir(exist_ok=True)
    for language in ("python", "javascript"):
        source = ROOT / "sdk" / language
        prefix = f"oreag-{language}-sdk"
        with ZipFile(output / f"{prefix}.zip", "w", ZIP_DEFLATED) as archive:
            for file in sorted(source.rglob("*")):
                if not file.is_file() or any(p in ("__pycache__", "node_modules", ".pytest_cache", "build", "dist") or p.endswith(".egg-info") for p in file.relative_to(source).parts):
                    continue
                if file.suffix not in (".py", ".md", ".toml", ".js", ".mjs", ".ts", ".json", ".typed"):
                    continue
                info = ZipInfo(f"{prefix}/{file.relative_to(source).as_posix()}", (2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, file.read_bytes().replace(b"\r\n", b"\n"))
        print(f"Built {prefix}.zip")


if __name__ == "__main__": build()

"""Check shared SDK version and release tag without importing the application."""
import argparse
import json
import os
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--github-output",action="store_true")
args = parser.parse_args()
js = json.loads((ROOT/"sdk/javascript/package.json").read_text(encoding="utf-8"))
py = tomllib.loads((ROOT/"sdk/python/pyproject.toml").read_text(encoding="utf-8"))["project"]
version = js["version"]
assert re.fullmatch(r"\d+\.\d+\.\d+",version) and py["version"] == version, "SDK versions differ"
ref = os.getenv("GITHUB_REF","")
if ref.startswith("refs/tags/"): assert ref == f"refs/tags/sdk-v{version}", "Release tag and package versions differ"
for language in ("python","javascript"):
    assert f"## {version}" in (ROOT/f"sdk/{language}/CHANGELOG.md").read_text(encoding="utf-8"), "Missing changelog"
    assert (ROOT/f"sdk/{language}/LICENSE").is_file(), "SDK license must be decided before release"
if args.github_output:
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as out: out.write(f"version={version}\n")
print(f"SDK versions and release metadata agree: {version}")

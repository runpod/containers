"""Remove .dist-info/.egg-info directories whose Version: line disagrees
with the version pip just installed for one of our pinned packages.

NGC base images bundle several Python packages as in-tree source builds
that carry their own egg-info next to the source. `pip install --upgrade`
upgrades the wheel install but cannot reach those bundled trees, so
Trivy keeps reporting the (now-unused) older version. This script removes
the orphaned metadata for packages listed in the supplied requirements
file."""
import pathlib
import re
import shutil
import sys


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def main(requirements_path: str) -> None:
    pinned: dict[str, str] = {}
    for line in pathlib.Path(requirements_path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        pinned[canonical(name)] = version.strip()

    name_re = re.compile(r"^Name:\s*(.+)$", re.MULTILINE)
    version_re = re.compile(r"^Version:\s*(.+)$", re.MULTILINE)

    for root in (pathlib.Path("/usr"), pathlib.Path("/opt")):
        if not root.is_dir():
            continue
        for meta_dir in [*root.rglob("*.dist-info"), *root.rglob("*.egg-info")]:
            if not meta_dir.is_dir():
                continue
            metadata = meta_dir / "METADATA"
            if not metadata.exists():
                metadata = meta_dir / "PKG-INFO"
            if not metadata.exists():
                continue
            try:
                text = metadata.read_text(errors="ignore")
            except OSError:
                continue
            name_match = name_re.search(text)
            version_match = version_re.search(text)
            if not name_match or not version_match:
                continue
            pkg = canonical(name_match.group(1))
            ver = version_match.group(1).strip()
            expected = pinned.get(pkg)
            if expected is None or ver == expected:
                continue
            print(f"scrub-stale-metadata: removing {meta_dir} (Version: {ver}, pinned {expected})")
            shutil.rmtree(meta_dir, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1])
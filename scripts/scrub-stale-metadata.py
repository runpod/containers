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

NAME_RE = re.compile(r"^Name:\s*([^\n]*)$", re.MULTILINE)
VERSION_RE = re.compile(r"^Version:\s*([^\n]*)$", re.MULTILINE)
SEARCH_ROOTS = (pathlib.Path("/usr"), pathlib.Path("/opt"))


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_pinned(requirements_path: str) -> dict[str, str]:
    """Read a requirements file, return {canonical_name: version} for `==` pins."""
    pinned: dict[str, str] = {}
    for raw in pathlib.Path(requirements_path).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        pinned[canonical(name)] = version.strip()
    return pinned


def read_meta(meta_dir: pathlib.Path) -> tuple[str, str] | None:
    """Return (canonical_name, version) for a metadata dir, or None if unreadable."""
    metadata = meta_dir / "METADATA"
    if not metadata.exists():
        metadata = meta_dir / "PKG-INFO"
    if not metadata.exists():
        return None
    try:
        text = metadata.read_text(errors="ignore")
    except OSError:
        return None
    name_match = NAME_RE.search(text)
    version_match = VERSION_RE.search(text)
    if not name_match or not version_match:
        return None
    return canonical(name_match.group(1)), version_match.group(1).strip()


def iter_meta_dirs() -> "Iterator[pathlib.Path]":
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for meta_dir in (*root.rglob("*.dist-info"), *root.rglob("*.egg-info")):
            if meta_dir.is_dir():
                yield meta_dir


def main(requirements_path: str) -> None:
    pinned = parse_pinned(requirements_path)
    for meta_dir in iter_meta_dirs():
        meta = read_meta(meta_dir)
        if meta is None:
            continue
        pkg, ver = meta
        expected = pinned.get(pkg)
        if expected is None or ver == expected:
            continue
        print(f"scrub-stale-metadata: removing {meta_dir} (Version: {ver}, pinned {expected})")
        shutil.rmtree(meta_dir, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1])
"""Validate archive scope, runtime parity, metadata and wheel RECORD hashes.

Run from the source root after building one sdist and its derived wheel:
``python tools/check_dist.py dist``. This never imports the package or executes
archive contents. Unexpected files fail validation instead of being ignored.
"""

import base64
import csv
import hashlib
import io
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


def check(folder: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    wheel, = folder.glob("*.whl")
    sdist, = folder.glob("*.tar.gz")
    runtime = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in (root / "commentail").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)), "Duplicate wheel members"
        metadata_root = f"commentail-{version}.dist-info/"
        assert all(n.startswith(("commentail/", metadata_root)) for n in names)
        shipped = {n: archive.read(n) for n in names if n.startswith("commentail/")}
        assert shipped == runtime, "Wheel runtime differs from source"
        metadata = archive.read(metadata_root + "METADATA").decode()
        assert f"Version: {version}\n" in metadata
        assert "License-Expression: MIT\n" in metadata
        assert archive.read(metadata_root + "licenses/LICENSE") == (root / "LICENSE").read_bytes()
        rows = list(csv.reader(io.StringIO(archive.read(metadata_root + "RECORD").decode())))
        assert {row[0] for row in rows} == set(names), "Incomplete RECORD"
        for name, digest, size in rows:
            if name.endswith("/RECORD"):
                assert not digest and not size
                continue
            data = archive.read(name)
            expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert digest == "sha256=" + expected and int(size) == len(data), name
    public_docs = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for folder_name, pattern in (
            ("wiki", "*.md"), ("releases", "*.md"), ("assets", "*.png")
        )
        for p in (root / "docs" / folder_name).glob(pattern)
    }
    assert public_docs, "Missing public documentation"
    roots = {"commentail", "tests", "example", "tools", "commentail.egg-info"}
    files = {"README.md", "LICENSE", "MANIFEST.in", "pyproject.toml", "requirements-test.txt", "requirements-test-common.txt", "PKG-INFO", "setup.cfg", "CHANGELOG.md"}
    with tarfile.open(sdist) as archive:
        shipped = {}
        shipped_docs = {}
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and ".." not in path.parts
            assert path.parts[0] == f"commentail-{version}"
            assert member.isdir() or member.isfile(), "Non-regular archive member"
            if len(path.parts) == 1:
                continue
            relative = PurePosixPath(*path.parts[1:])
            assert (
                relative.parts[0] in roots
                or relative.as_posix() in files
                or relative.as_posix() in public_docs
                or (member.isdir() and relative.parts[0] == "docs")
            ), member.name
            assert not any(part.startswith(".") or part == "__pycache__" for part in relative.parts)
            if member.isfile() and relative.parts[0] == "commentail":
                shipped[relative.as_posix()] = archive.extractfile(member).read()
            if member.isfile() and relative.parts[0] == "docs":
                shipped_docs[relative.as_posix()] = archive.extractfile(member).read()
        assert shipped_docs == public_docs, "sdist documentation differs from source"
        assert shipped == runtime, "sdist runtime differs from source"
        names = {PurePosixPath(*PurePosixPath(n).parts[1:]).as_posix() for n in archive.getnames()}
        assert {"tests/test_reply.js", "example/manage.py", "tools/check_dist.py", "requirements-test.txt", "requirements-test-common.txt", "CHANGELOG.md"} <= names
    print(f"Validated {version}: {len(runtime)} runtime files, archive scope and RECORD")


if __name__ == "__main__":
    check(Path(sys.argv[1]))

"""Restore the saved shallow Git database without fetching from the network."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root = Path(sys.argv[1]).resolve()
repository = root / "rstudio"
archive_dir = root / "workspace-state/git-history"
manifest = json.loads((archive_dir / "manifest.json").read_text())
if (repository / ".git").exists() or (repository / ".git").is_symlink():
    raise SystemExit("Refusing to overwrite rstudio/.git")
if not manifest["parts"]:
    raise SystemExit("Git history archive has no parts")
with tempfile.TemporaryFile() as joined:
    for part in manifest["parts"]:
        if Path(part["file"]).name != part["file"]:
            raise SystemExit("Invalid archive part name")
        path = archive_dir / part["file"]
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                joined.write(chunk)
        if size != part["size"] or digest.hexdigest() != part["sha256"]:
            raise SystemExit("Git history part failed verification: " + path.name)
    joined.seek(0)
    with tarfile.open(fileobj=joined, mode="r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != ".git":
                raise SystemExit("Unexpected history archive path")
            if not (member.isdir() or member.isfile()):
                raise SystemExit("Unexpected history archive link or special file")
        # Archive names/types were checked above; compatible with macOS Python 3.9.
        archive.extractall(repository)
head = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
if head != manifest["head"]:
    raise SystemExit("Restored Git HEAD does not match the saved VM HEAD")
expected = (root / "workspace-state/rstudio-refs.txt").read_text().strip()
actual = subprocess.check_output(["git", "-C", str(repository), "for-each-ref",
    "--format=%(refname) %(objectname)"], text=True).strip()
if actual != expected:
    raise SystemExit("Restored refs do not match the saved VM refs")
print("Restored all saved RStudio refs and shallow Git objects at " + head)

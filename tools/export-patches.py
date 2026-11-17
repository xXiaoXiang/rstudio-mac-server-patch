#!/usr/bin/env python3
"""Export the maintained source branch as a checksummed, versioned patch series."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--base", default="macos-server/base-main-2da6d1b")
parser.add_argument("--branch", default="feature/macos-server")
parser.add_argument("--revision", type=int, required=True)
args = parser.parse_args()
if args.revision < 1:
    parser.error("revision must be positive")
base = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", args.base], text=True).strip()
subprocess.run(["git", "-C", str(args.source), "merge-base", "--is-ancestor", args.base, args.branch], check=True)
with tempfile.TemporaryDirectory(prefix="rstudio-export-") as directory:
    subprocess.run(["git", "-C", str(args.source), "format-patch", "--no-signature", "--full-index",
                    "--output-directory", directory, args.base + ".." + args.branch], check=True)
    exported = sorted(Path(directory).glob("*.patch"))
    if not exported:
        parser.error("no patch commits found")
    manifest_path = ROOT / "patches/series.json"
    data = json.loads(manifest_path.read_text())
    previous = {item["file"] for item in data["patches"]}
    items = []
    for path in exported:
        content = path.read_bytes()
        (ROOT / "patches" / path.name).write_bytes(content)
        items.append({"file": path.name, "sha256": hashlib.sha256(content).hexdigest()})
    for name in previous - {item["file"] for item in items}:
        if Path(name).name == name and name.endswith(".patch"):
            (ROOT / "patches" / name).unlink()
    data.update(revision=args.revision, base_commit=base, patches=items)
    manifest_path.write_text(json.dumps(data, indent=2) + "\n")
print("Exported", len(items), "patches; revision", args.revision)

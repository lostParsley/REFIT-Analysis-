"""Download the exact official REFIT release used by the assignment."""
from pathlib import Path
import hashlib
import json
import urllib.request
import time

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "RAW_READ_ME_081116.txt": "62090176",
    "CLEAN_READ_ME_081116.txt": "62090183",
    "REFIT_RAW_081116.7z": "62090177",
    "CLEAN_REFIT_081116.7z": "62090184",
}

def main():
    target = ROOT / "data" / "downloads"
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, file_id in FILES.items():
        url = f"https://pure.strath.ac.uk/ws/portalfiles/portal/{file_id}/{name}"
        path = target / name
        if not path.exists():
            print(f"Downloading {name}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "REFIT-research-assignment/1.0"})
            partial = path.with_suffix(path.suffix + ".partial")
            with urllib.request.urlopen(req, timeout=90) as response, partial.open("wb") as out:
                last = time.monotonic()
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
                    if time.monotonic() - last > 20:
                        print(f"  {name}: {out.tell()/1e6:.0f} MB", flush=True)
                        last = time.monotonic()
            partial.replace(path)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        manifest.append(dict(file=name, url=url, bytes=path.stat().st_size, sha256=digest.hexdigest()))
        print(f"Ready: {name} ({path.stat().st_size/1e6:.1f} MB)", flush=True)
    destination = ROOT / "artifacts" / "tables"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "source_manifest.json").write_text(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    main()

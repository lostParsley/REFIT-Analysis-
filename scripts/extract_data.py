"""Extract only the required house files; archive integrity is checked on extraction."""
from pathlib import Path
import re
import py7zr

ROOT = Path(__file__).resolve().parents[1]

def main():
    for release, houses in [("REFIT_RAW_081116", [1]), ("CLEAN_REFIT_081116", [1, 2, 3, 5])]:
        destination = ROOT / "data" / ("raw" if "RAW" in release else "official_clean")
        destination.mkdir(parents=True, exist_ok=True)
        with py7zr.SevenZipFile(ROOT / "data" / "downloads" / f"{release}.7z") as archive:
            expected_sizes = {item.filename: item.uncompressed for item in archive.list()}
            names = archive.getnames()
            print(f"{release} members: {names}", flush=True)
            targets = [name for name in names if any(re.search(rf"House_?{house}(?:_|\.|/)", name, re.I) for house in houses) and name.lower().endswith(".csv")]
            if not targets:
                raise ValueError("No expected house CSV names found in archive")
            if all((destination / name).exists() and (destination / name).stat().st_size == expected_sizes[name] for name in targets):
                print("Already extracted; file sizes match archive metadata", flush=True)
                continue
            print(f"Extracting {targets}",flush=True)
            archive.extract(path=destination, targets=targets)

if __name__ == "__main__":
    main()

"""Build a small submission archive without source data, caches or local models."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    files = [ROOT / name for name in ["README.md", "DATA.md", "RESULTS.md", "Recommendation.md",
                                      "requirements.txt", "config.json", ".gitignore"]]
    for directory, extensions in [("refit", {".py"}), ("scripts", {".py"}), ("tests", {".py"}),
                                   ("output", {".png", ".svg"}), ("artifacts/tables", {".csv", ".json"})]:
        files.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and p.suffix in extensions)
    path = destination / "flock-energy-submission.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(file, file.relative_to(ROOT).as_posix())
    print(f"Packaged {len(files)} files: {path} ({path.stat().st_size/1e6:.2f} MB)")

if __name__ == "__main__":
    main()

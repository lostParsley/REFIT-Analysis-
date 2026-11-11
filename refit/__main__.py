import argparse
import time
from .data import prepare, read_prepared
from .plots import setup

def main():
    parser = argparse.ArgumentParser(description="REFIT assignment: reproducible analysis")
    parser.add_argument("stage", choices=["all", "prepare", "eda", "model", "report"])
    args = parser.parse_args()
    started = time.perf_counter()
    setup()
    if args.stage in ("all", "prepare"):
        homes = prepare()
    elif args.stage != "report":
        homes = read_prepared()
    if args.stage in ("all", "eda"):
        from .eda import analyse
        analyse(homes)
    if args.stage in ("all", "model"):
        from .model import run
        run(homes)
    if args.stage in ("all", "report"):
        from .report import write_reports
        write_reports()
    print(f"Finished {args.stage} in {time.perf_counter()-started:.1f}s", flush=True)

if __name__ == "__main__":
    main()

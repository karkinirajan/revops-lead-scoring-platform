"""Mutation check: deliberate bugs, one at a time, each of which the test suite must notice.

usage: mutate.py MUTANTS.py [name-filter ...] -- <test command ...>      (run from the directory the mutants' file paths are relative to)

MUTANTS.py defines `M = [(name, file, old, new), ...]`. Each `old` must occur exactly once in `file`. The suite must pass unmutated (checked first, since with a
failing suite every mutant would look killed); each mutant is then applied alone and the suite is run, and the mutant counts as killed only if the suite fails.
Every file is restored afterwards, even if the run is interrupted. Do not edit the tree while it runs.
"""

import pathlib
import subprocess
import sys

TIMEOUT_SECONDS = 180


def run(command: list[str]) -> int:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS).returncode
    except subprocess.TimeoutExpired:
        return 124  # a mutant that makes the suite hang is noticed too


def main() -> int:
    divider = sys.argv.index("--")
    spec, filters, command = sys.argv[1], sys.argv[2:divider], sys.argv[divider + 1 :]

    namespace: dict = {}
    exec(pathlib.Path(spec).read_text(), namespace)  # the list is code that is part of the repository
    mutants = [m for m in namespace["M"] if not filters or any(word in m[0] for word in filters)]
    originals = {name: pathlib.Path(name).read_text() for name in {m[1] for m in mutants}}

    baseline = subprocess.run(command, capture_output=True, text=True)
    if baseline.returncode:
        tail = (baseline.stdout + baseline.stderr).splitlines()[-15:]
        print("BASELINE FAILS: the suite must pass before any mutation.\n" + "\n".join(tail))
        return 2
    print("baseline green", flush=True)

    survivors: list[str] = []
    try:
        for name, file, old, new in mutants:
            occurrences = originals[file].count(old)
            if occurrences != 1:
                print(f"PATTERN? ({occurrences}x) {name}", flush=True)
                survivors.append(name)
                continue
            pathlib.Path(file).write_text(originals[file].replace(old, new))
            try:
                killed = run(command) != 0
            finally:
                pathlib.Path(file).write_text(originals[file])
            print(("killed   " if killed else "SURVIVED ") + name, flush=True)
            if not killed:
                survivors.append(name)
    finally:
        for file, text in originals.items():
            pathlib.Path(file).write_text(text)

    restored = all(pathlib.Path(file).read_text() == text for file, text in originals.items())
    print(f"\n{len(mutants) - len(survivors)}/{len(mutants)} killed; restored: {restored}")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())

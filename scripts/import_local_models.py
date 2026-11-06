"""Copy optional research model folders from a local FlowLens installation.

Copied files are ignored by Git. Restart the desktop after importing.
"""

import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installation", type=Path)
    args = parser.parse_args()
    source = args.installation.resolve()
    if source == ROOT:
        raise ValueError("Select the existing research installation, not this repository.")
    if (
        not (source / "model" / "visual_forest.npz").is_file()
        or not (source / "interface-models" / "current.json").is_file()
    ):
        raise ValueError("The selected installation does not contain both research models.")
    for name in ("model", "interface-models"):
        shutil.copytree(source / name, ROOT / name, dirs_exist_ok=True)
    print(
        "Local models imported into Git-ignored folders. Review their model cards before inference."
    )


if __name__ == "__main__":
    main()

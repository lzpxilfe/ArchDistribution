import os
import argparse

DEFAULT_ROOT = os.path.dirname(os.path.abspath(__file__))


def find_insite_folders(root):
    found = False
    for dirpath, dirnames, filenames in os.walk(root):
        if "insite" in os.path.basename(dirpath).lower():
            print(f"Found folder: {dirpath}")
            found = True
            for f in filenames:
                print(f" - {f}")
    if not found:
        print("Folder 'insite' not found.")


def main():
    parser = argparse.ArgumentParser(description="Find folders named like 'insite' and list their files.")
    parser.add_argument(
        "root",
        nargs="?",
        default=DEFAULT_ROOT,
        help=f"Search root directory (default: {DEFAULT_ROOT})",
    )
    args = parser.parse_args()
    find_insite_folders(args.root)


if __name__ == "__main__":
    main()

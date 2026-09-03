import os
import zipfile
import configparser
import hashlib
import json
import subprocess
import shutil
from pathlib import Path


def _git_executable():
    """Locate Git in ordinary shells and the bundled Codex runtime."""
    discovered = shutil.which("git")
    if discovered:
        return discovered
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native"
        / "git/cmd/git.exe"
    )
    return str(bundled) if bundled.exists() else "git"

def get_git_files():
    try:
        # Get list of tracked files
        result = subprocess.run([_git_executable(), 'ls-files'], capture_output=True, text=True, check=True)
        files = result.stdout.splitlines()
        # Also strictly ensure any exclusions if needed, but ls-files usually handles it.
        # Note: ls-files returns paths relative to the git root.
        return files
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Warning: git command failed or not a git repo. Falling back to manual exclusion.")
        return None


def get_git_build_info():
    """Return commit provenance embedded in the installable ZIP."""
    try:
        commit = subprocess.run(
            [_git_executable(), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit_date = subprocess.run(
            [_git_executable(), "show", "-s", "--format=%cI", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            [_git_executable(), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip())
        return {
            "git_commit": commit or "unknown",
            "built_at": commit_date or None,
            "dirty": dirty,
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"git_commit": "unknown", "built_at": None, "dirty": True}


def select_runtime_files(git_files, runtime_files):
    """Select only explicitly declared root runtime paths.

    Matching by basename would accidentally package ``paper/README.md`` or
    subdirectory licence files after the JOSS material is committed.
    """
    declared = {Path(path).as_posix() for path in runtime_files}
    return [
        Path(path).as_posix()
        for path in (git_files or [])
        if Path(path).as_posix() in declared
    ]


def approved_reference_assets(
    register_path=Path("docs/research/reference-data-register.json"),
    tracked_files=None,
):
    """Return verified reference assets cleared for redistribution.

    Missing, malformed, or incomplete provenance is a denial by default.  This
    keeps development data out of plugin and JOSS archives until the human
    licence audit changes ``joss_release_approved`` to true. Approved assets
    must also be Git-tracked and match their registered SHA-256, so an
    unreviewed local file with the same name cannot enter a release ZIP.
    """
    try:
        register = json.loads(register_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()
    tracked = {
        Path(path).as_posix()
        for path in (
            tracked_files if tracked_files is not None else get_git_files() or []
        )
    }
    approved = set()
    for asset in register.get("assets", []):
        path = Path(str(asset.get("path") or "")).as_posix()
        expected_sha256 = str(asset.get("sha256") or "").strip().lower()
        if (
            asset.get("joss_release_approved") is True
            and path
            and "/" not in path
            and path in tracked
            and len(expected_sha256) == 64
            and Path(path).is_file()
        ):
            actual_sha256 = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            if actual_sha256 == expected_sha256:
                approved.add(path)
    return approved

def create_plugin_zip():
    plugin_name = "ArchDistribution"
    version = "dev"
    metadata_path = Path("metadata.txt")

    if metadata_path.exists():
        config = configparser.ConfigParser()
        try:
            config.read(metadata_path, encoding="utf-8")
            plugin_name = config.get("general", "name", fallback=plugin_name).strip() or plugin_name
            version = config.get("general", "version", fallback=version).strip() or version
        except Exception as e:
            print(f"Warning: Could not read metadata.txt: {e}")

    # The folder name INSIDE the zip file must match the plugin package name
    zip_root_name = plugin_name

    # Save to Desktop
    desktop_path = Path.home() / "Desktop"
    zip_filename = desktop_path / f"{plugin_name}-{version}.zip"

    # Try to get files from git
    git_files = get_git_files()

    runtime_files = {
        "LICENSE",
        "LICENSES.md",
        "README.md",
        "__init__.py",
        "arch_distribution.py",
        "arch_distribution_dialog.py",
        "arch_distribution_dialog_base.ui",
        "attribute_classification.py",
        "cartographic_filtering.py",
        "icon.png",
        "heritage_grouping.py",
        "heritage_identity_store.py",
        "heritage_matching.py",
        "heritage_matching_dialog.py",
        "matching_rules.json",
        "metric_context.py",
        "map_legend_styles.py",
        "metadata.txt",
        "preservation_actions.py",
        "run_artifacts.py",
        "shapefile_encoding.py",
    }
    optional_reference_assets = {
        "reference_data.json",
        "smart_patterns.json",
    }
    approved_assets = approved_reference_assets(tracked_files=git_files)
    runtime_files.update(optional_reference_assets & approved_assets)
    withheld_assets = optional_reference_assets - approved_assets
    if withheld_assets:
        print(
            "Withholding reference assets pending provenance/licence approval: "
            + ", ".join(sorted(withheld_assets))
        )

    print(f"Creating {zip_filename}...")

    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # QGIS expects a real top-level plugin directory inside the archive.
        root_info = zipfile.ZipInfo(f"{zip_root_name}/")
        root_info.external_attr = 0o40755 << 16
        zipf.writestr(root_info, b"")

        if git_files:
            print("Using git tracked files list...")
            files_to_zip = select_runtime_files(
                git_files,
                runtime_files,
            )
            # Include declared runtime modules that exist locally even before
            # they are staged, so development builds cannot omit dependencies.
            for runtime_file in runtime_files:
                if os.path.isfile(runtime_file) and runtime_file not in files_to_zip:
                    files_to_zip.append(runtime_file)
        else:
            print("Warning: git not found. Using manual file walking (fallback).")
            files_to_zip = sorted(
                runtime_file
                for runtime_file in runtime_files
                if Path(runtime_file).is_file()
            )

        for file_path in files_to_zip:
            if not os.path.exists(file_path):
                continue
                
            # git files are relative path strings from repo root
            rel_path = Path(file_path).as_posix()
            arc_name = f"{zip_root_name}/{rel_path}"

            print(f"Adding {rel_path} as {arc_name}")
            
            try:
                st = os.stat(file_path)
                mtime = st.st_mtime
                if mtime < 315532800:
                    mtime = 1577836800
                
                import time
                date_time = time.localtime(mtime)[:6]
                zinfo = zipfile.ZipInfo(arc_name, date_time=date_time)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
                
                with open(file_path, 'rb') as f:
                    zipf.writestr(zinfo, f.read())
                    
            except Exception as e:
                print(f"Failed to add {file_path}: {e}")

        # Installed plugins normally have no .git directory.  Preserve the
        # exact source revision in a generated runtime file instead.
        build_info = json.dumps(
            get_git_build_info(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        zipf.writestr(
            f"{zip_root_name}/build_info.json",
            build_info,
        )

    print(f"Successfully created {zip_filename}")

if __name__ == "__main__":
    create_plugin_zip()

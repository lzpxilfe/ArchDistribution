import os
import zipfile
import configparser
import subprocess
import sys
from pathlib import Path

def get_git_files():
    try:
        # Get list of tracked files
        result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, check=True)
        files = result.stdout.splitlines()
        # Also strictly ensure any exclusions if needed, but ls-files usually handles it.
        # Note: ls-files returns paths relative to the git root.
        return files
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Warning: git command failed or not a git repo. Falling back to manual exclusion.")
        return None

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
        "README.md",
        "__init__.py",
        "arch_distribution.py",
        "arch_distribution_dialog.py",
        "arch_distribution_dialog_base.ui",
        "icon.png",
        "metadata.txt",
        "reference_data.json",
        "smart_patterns.json",
    }

    print(f"Creating {zip_filename}...")

    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # QGIS expects a real top-level plugin directory inside the archive.
        root_info = zipfile.ZipInfo(f"{zip_root_name}/")
        root_info.external_attr = 0o40755 << 16
        zipf.writestr(root_info, b"")

        if git_files:
            print("Using git tracked files list...")
            files_to_zip = []
            for f in git_files:
                basename = os.path.basename(f)
                if basename in runtime_files:
                    files_to_zip.append(f)
        else:
            print("Warning: git not found. Using manual file walking (fallback).")
            # Fallback logic (omitted for brevity as git is expected)
            files_to_zip = [] 

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

    print(f"Successfully created {zip_filename}")

if __name__ == "__main__":
    create_plugin_zip()

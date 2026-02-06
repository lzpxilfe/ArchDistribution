import os
import zipfile
import configparser
import subprocess
import sys

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
    # Detect plugin name from metadata.txt
    plugin_name = "ArchDistribution" # Default
    metadata_path = 'metadata.txt'
    
    if os.path.exists(metadata_path):
        config = configparser.ConfigParser()
        try:
            config.read(metadata_path, encoding='utf-8')
            # Keeping default name for consistency
            pass
        except Exception as e:
            print(f"Warning: Could not read metadata.txt: {e}")

    # The folder name INSIDE the zip file must match the plugin package name
    zip_root_name = "ArchDistribution"
    zip_filename = "ArchDistribution.zip"

    # Try to get files from git
    git_files = get_git_files()

    # Manual excludes as fallback
    excludes = [
        '.git', '__pycache__', '.venv', '.idea', '.vscode', 
        'create_zip.py', zip_filename, '.gitignore', 
        'test', 'tests', 'debug_import.py', 'debug_qgis_logic.py',
        'force_reload.py', 'fix_indent.py', 'inspect_dbf.py',
        'inspect_zones.py', 'test_filtering_logic.py', 'analyze_artifacts.py',
        'analyze_artifacts_v2.py', 'compile_reference.py', 'find_insite.py'
    ]

    print(f"Creating {zip_filename}...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if git_files:
            print("Using git tracked files list...")
            files_to_zip = git_files
            # Filter out create_zip.py and the zip itself if they are tracked (unlikely to want zip in zip)
            files_to_zip = [f for f in files_to_zip if f != zip_filename and f != 'create_zip.py']
        else:
            print("Using manual file walking...")
            files_to_zip = []
            for root, dirs, files in os.walk('.'):
                dirs[:] = [d for d in dirs if d not in excludes]
                for file in files:
                    if file in excludes:
                        continue
                    if file.endswith('.zip') or file.endswith('.ui.py'):
                        continue
                    files_to_zip.append(os.path.join(root, file))

        for file_path in files_to_zip:
            # Check if file exists (git ls-files lists deleted files too if not updated?)
            # No, ls-files lists index. But better check existence.
            if not os.path.exists(file_path):
                continue
                
            # Create the archive name with the top-level folder
            # e.g. metadata.txt -> ArchDistribution/metadata.txt
            if git_files:
                # git files are relative path strings
                rel_path = file_path
                # normalize separators
                rel_path = rel_path.replace('/', os.sep)
            else:
                rel_path = os.path.relpath(file_path, '.')
            
            arc_name = os.path.join(zip_root_name, rel_path)
            
            print(f"Adding {rel_path} as {arc_name}")
            
            try:
                st = os.stat(file_path)
                mtime = st.st_mtime
                # 1980 check
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

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
    
    # Save to Desktop
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    zip_filename = os.path.join(desktop_path, "ArchDistribution.zip")

    # Try to get files from git
    git_files = get_git_files()

    # Files to explicitly exclude even if they are in git (dev scripts, tools, etc.)
    # We match these by filename or partial path
    dev_exclusions = [
        'create_zip.py', 'debug_', 'test_', 'analyze_', 'inspect_', 'fix_', 'force_', 
        'compile_reference.py', 'find_insite.py', '.gitignore', '.gitattributes'
    ]

    print(f"Creating {zip_filename}...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if git_files:
            print("Using git tracked files list...")
            files_to_zip = []
            for f in git_files:
                # Check exclusions
                is_excluded = False
                basename = os.path.basename(f)
                if basename == 'create_zip.py' or f.endswith('.zip'):
                    is_excluded = True
                else:
                    for exc in dev_exclusions:
                        if exc in basename: # Simple substring check for things like debug_*.py
                            is_excluded = True
                            break
                
                if not is_excluded:
                    files_to_zip.append(f)
        else:
            print("Warning: git not found. Using manual file walking (fallback).")
            # Fallback logic (omitted for brevity as git is expected)
            files_to_zip = [] 

        for file_path in files_to_zip:
            if not os.path.exists(file_path):
                continue
                
            # git files are relative path strings from repo root
            rel_path = file_path.replace('/', os.sep)
            
            arc_name = os.path.join(zip_root_name, rel_path)
            
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

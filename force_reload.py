import sys
import importlib
import os
import configparser

# 1. Check Metadata on Disk
plugin_dir = os.path.dirname(os.path.abspath(__file__))
metadata_path = os.path.join(plugin_dir, 'metadata.txt')

print(f"--- DIAGNOSING PLUGIN VERSION ---")
print(f"Plugin Dir: {plugin_dir}")

if os.path.exists(metadata_path):
    config = configparser.ConfigParser()
    config.read(metadata_path, encoding='utf-8')
    if 'general' in config and 'version' in config['general']:
        print(f"✅ Disk Metadata Version: {config['general']['version']}")
    else:
        print(f"❌ Version not found in metadata.txt")
else:
    print(f"❌ metadata.txt NOT FOUND at {metadata_path}")

# 2. Force Reload Modules
modules = [
    'ArchDistribution.arch_distribution',
    'ArchDistribution.arch_distribution_dialog',
]

print(f"--- RELOADING MODULES ---")
for mod_name in modules:
    if mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[mod_name])
            print(f"✅ Reloaded {mod_name}")
        except Exception as e:
            print(f"❌ Failed to reload {mod_name}: {e}")
    else:
        print(f"⚠️ Module {mod_name} not loaded in sys.modules (Not running?)")

print("--- DONE. PLEASE CHECK LOGS ---")

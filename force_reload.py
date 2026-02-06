import sys
import importlib
from qgis.utils import iface

# List of modules to reload in order
modules = [
    'ArchDistribution.arch_distribution',
    'ArchDistribution.arch_distribution_dialog',
    # Add other backend modules if any
]

for mod_name in modules:
    if mod_name in sys.modules:
        print(f"Reloading {mod_name}...")
        importlib.reload(sys.modules[mod_name])

print("Plugin modules reloaded. Please close and reopen the plugin dialog.")

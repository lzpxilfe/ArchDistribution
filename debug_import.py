
import sys
import os

# Add the source directory to path to simulate QGIS loading environment
sys.path.append(os.getcwd())

print("Attempting to import arch_distribution_dialog...")
try:
    import arch_distribution_dialog
    print("SUCCESS: arch_distribution_dialog imported.")
except Exception as e:
    print(f"FAIL: arch_distribution_dialog import failed: {e}")

print("Attempting to import arch_distribution...")
try:
    import arch_distribution
    print("SUCCESS: arch_distribution imported.")
except Exception as e:
    print(f"FAIL: arch_distribution import failed: {e}")

print("Attempting to import __init__...")
try:
    import __init__
    print("SUCCESS: __init__ imported.")
except Exception as e:
    print(f"FAIL: __init__ import failed: {e}")

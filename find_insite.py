import os

root = r"c:\Users\nuri9\.gemini\antigravity\scratch\ArchDistribution"
found = False
for dirpath, dirnames, filenames in os.walk(root):
    if 'insite' in os.path.basename(dirpath).lower():
        print(f"Found folder: {dirpath}")
        found = True
        for f in filenames:
            print(f" - {f}")

if not found:
    print("Folder 'insite' not found.")

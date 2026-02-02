import os
import pandas as pd
import glob

def find_name_column(df):
    keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
    for col in df.columns:
        for k in keywords:
            if k in str(col).upper():
                return col
    return None

xlsx_files = glob.glob('xlsx/*.xlsx')
print(f"Found {len(xlsx_files)} Excel files.")

all_names = set()
artifact_keywords = ['석불', '마애불', '광배', '석조', '석탑', '부도', '석등', '당간', '불상', '여래', '보살', '탑비', '비석']
noise_keywords = ['지표면', '단순', '수습', '조사구역', '현상변경', '배수로', '입회', '참관', '시굴', '표본']

artifacts = []
noise = []
temple_sites = [] # To see overlap

for f in xlsx_files:
    try:
        df = pd.read_excel(f)
        name_col = find_name_column(df)
        if name_col:
            names = df[name_col].dropna().astype(str).tolist()
            for n in names:
                all_names.add(n)
                
                # Check for artifacts (Potential false positive sites)
                if any(k in n for k in artifact_keywords):
                    artifacts.append(n)
                
                # Check for noise (Should be excluded)
                if any(k in n for k in noise_keywords):
                    noise.append(n)
                    
                # Check for Temple Sites (Comparison)
                if '사지' in n or '절터' in n:
                    temple_sites.append(n)

    except Exception as e:
        print(f"Error reading {f}: {e}")

print(f"Total unique names: {len(all_names)}")

print(f"\n[Potential Artifacts] (Keywords: {', '.join(artifact_keywords)})")
print(f"Count: {len(artifacts)}")
print("--- Sample (Top 30) ---")
for n in sorted(list(set(artifacts)))[:30]:
    print(n)

print(f"\n[Potential Noise] (Keywords: {', '.join(noise_keywords)})")
print(f"Count: {len(noise)}")
print("--- Sample (Top 30) ---")
for n in sorted(list(set(noise)))[:30]:
    print(n)

print(f"\n[Temple Sites] (Keywords: 사지, 절터)")
print(f"Count: {len(temple_sites)}")
print("--- Sample (Top 10) ---")
for n in sorted(list(set(temple_sites)))[:10]:
    print(n)

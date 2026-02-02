import os
import pandas as pd
import glob
from collections import Counter
import re

def find_name_column(df):
    keywords = ['유적명', '명칭', '명', '이름', 'NAME', 'SITE', 'TITLE']
    for col in df.columns:
        for k in keywords:
            if k in str(col).upper():
                return col
    return None

xlsx_files = glob.glob('xlsx/*.xlsx')
print(f"Found {len(xlsx_files)} Excel files.")

all_names = []
for f in xlsx_files:
    try:
        df = pd.read_excel(f)
        name_col = find_name_column(df)
        if name_col:
            names = df[name_col].dropna().astype(str).tolist()
            all_names.extend(names)
    except Exception as e:
        print(f"Error reading {f}: {e}")

print(f"Total entries: {len(all_names)}")

# 1. Tokenize and Count Suffixes/Keywords
# We split by spaces and look at the last word (often the type, e.g. "OOO Gobun", "OOO Saji")
suffixes = []
keywords = []

# Define simple stopwords or noise to ignore
ignore = ['및', '외', '내', '일원', '지구', '지역', '부지', '구역', '일대']

for n in all_names:
    parts = n.split()
    if not parts: continue
    
    # Last part is often the type
    last = parts[-1]
    # Remove numbering like "1", "NO.1", "A-1"
    last = re.sub(r'[0-9\-A-Za-z]+$', '', last) 
    if len(last) > 1 and last not in ignore: 
        suffixes.append(last)

    # Also look for specific contained keywords
    for k in ['고분', '분묘', '지석묘', '산성', '읍성', '토성', '요지', '가마', '야철지', '주거지', '취락', '유물산포지', '석불', '석탑', '비석', '부도', '건물지', '제사유적']:
        if k in n:
            keywords.append(k)

print("\n=== Top 50 Common Suffixes (Likely Types) ===")
for word, count in Counter(suffixes).most_common(50):
    print(f"{word}: {count}")

print("\n=== Keyword Occurrences (Known Types) ===")
for word, count in Counter(keywords).most_common(50):
    print(f"{word}: {count}")

print("\n=== Sample of 'Ambiguous' Items (Scatter/Finds) ===")
ambiguous = [n for n in all_names if '산포지' in n or '수습' in n or '발견' in n]
for n in sorted(list(set(ambiguous)))[:20]:
    print(n)

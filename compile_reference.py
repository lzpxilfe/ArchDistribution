import pandas as pd
import json
import os
import glob
import sys

def compile_reference_data():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    xlsx_dir = os.path.join(base_dir, 'xlsx')
    output_path = os.path.join(base_dir, 'reference_data.json')
    
    all_data = {}
    
    # Get all xlsx files
    xlsx_files = glob.glob(os.path.join(xlsx_dir, '*.xlsx'))
    
    print(f"Found {len(xlsx_files)} Excel files to process.")
    
    for file_path in xlsx_files:
        try:
            print(f"Processing {os.path.basename(file_path)}...")
            df = pd.read_excel(file_path)
            
            # Expected columns: '명칭' (Name), '시대' (Era), '유적소분류' or '유적중분류' (Type)
            # Based on previous inspection: '명칭', '시대', '유적소분류' are key
            
            if '명칭' not in df.columns:
                print(f"Skipping {os.path.basename(file_path)}: '명칭' column missing.")
                continue
                
            for _, row in df.iterrows():
                name = str(row['명칭']).strip()
                if not name or name == 'nan': continue
                
                # Era
                era = str(row['시대']).strip() if '시대' in df.columns and not pd.isna(row['시대']) else "시대미상"
                
                # Type - prioritize '유적소분류', fallback to '유적중분류'
                atype = "기타"
                if '유적소분류' in df.columns and not pd.isna(row['유적소분류']):
                    atype = str(row['유적소분류']).strip()
                elif '유적중분류' in df.columns and not pd.isna(row['유적중분류']):
                    atype = str(row['유적중분류']).strip()
                
                # Clean up Type string (remove codes like "0)고분")
                # Usually it might be "0)고분" or just "고분". 
                # Let's clean up leading digits/parens if present.
                if ')' in atype:
                    parts = atype.split(')')
                    if len(parts) > 1:
                        atype = parts[1].strip()
                        
                all_data[name] = {
                    "e": era,   # Short key for size
                    "t": atype
                }
                
        except Exception as e:
            print(f"Error processing {os.path.basename(file_path)}: {e}")

    print(f"Saving {len(all_data)} entries to {output_path}...")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, separators=(',', ':'))
        
    print("Compilation complete.")

if __name__ == "__main__":
    compile_reference_data()

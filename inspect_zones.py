import struct
import os
import argparse

DEFAULT_SHP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "insite",
    "현상변경허용기준.shp",
)

def list_unique_zones(dbf_path):
    print(f"Scanning values in: {dbf_path}")
    with open(dbf_path, 'rb') as f:
        header = f.read(32)
        num_records = struct.unpack('<I', header[4:8])[0]
        header_len = struct.unpack('<H', header[8:10])[0]
        record_len = struct.unpack('<H', header[10:12])[0]
        
        # Find '구역명' field offset
        fields = []
        zone_field_offset = 0
        zone_field_len = 0
        found_zone = False
        
        current_offset = 1 # Deletion flag
        
        while f.tell() < header_len - 1:
            field_data = f.read(32)
            if field_data[0] == 0x0D: break
            
            name = field_data[:11].rstrip(b'\x00').decode('cp949', errors='ignore')
            f_len = field_data[16]
            
            if name == '구역명':
                zone_field_offset = current_offset
                zone_field_len = f_len
                found_zone = True
                print(f"Found '구역명' at offset {zone_field_offset}, len {zone_field_len}")
            
            current_offset += f_len
            
        if not found_zone:
            print("'구역명' field not found.")
            return

        f.seek(header_len)
        unique_values = set()
        
        for i in range(num_records):
            record = f.read(record_len)
            if not record: break
            if record[0] == 0x2A: continue # Deleted
            
            val_bytes = record[zone_field_offset : zone_field_offset + zone_field_len]
            try:
                val = val_bytes.decode('cp949').strip()
                unique_values.add(val)
            except UnicodeDecodeError:
                pass
                
        print("Unique Zone Values:")
        for v in sorted(list(unique_values)):
            print(f"- {v}")

def main():
    parser = argparse.ArgumentParser(description="List unique zone values from DBF.")
    parser.add_argument(
        "--shp",
        default=DEFAULT_SHP_PATH,
        help=f"Path to source SHP file (default: {DEFAULT_SHP_PATH})",
    )
    args = parser.parse_args()

    dbf_path = os.path.splitext(args.shp)[0] + ".dbf"
    if os.path.exists(dbf_path):
        list_unique_zones(dbf_path)
    else:
        print(f"DBF not found: {dbf_path}")


if __name__ == "__main__":
    main()

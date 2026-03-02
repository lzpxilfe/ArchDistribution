import struct
import os
import argparse

DEFAULT_SHP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "insite",
    "현상변경허용기준.shp",
)

def read_dbf_header(dbf_path):
    print(f"Inspecting parsed DBF: {dbf_path}")
    with open(dbf_path, 'rb') as f:
        # Read header
        # 0-31 byte: Header info
        header = f.read(32)
        num_records = struct.unpack('<I', header[4:8])[0]
        header_len = struct.unpack('<H', header[8:10])[0]
        record_len = struct.unpack('<H', header[10:12])[0]
        
        print(f"Num Records: {num_records}")
        
        # Field descriptors start at 32
        # Each is 32 bytes
        fields = []
        while f.tell() < header_len - 1:
            field_data = f.read(32)
            if len(field_data) < 32: break
            if field_data[0] == 0x0D: break # terminator
            
            name_bytes = field_data[:11]
            # Try decoding name with CP949 and EUC-KR
            try:
                name = name_bytes.rstrip(b'\x00').decode('cp949')
                print(f"Field: {name} (Raw: {name_bytes})")
            except UnicodeDecodeError:
                print(f"Field: (Decdoding Failed) {name_bytes}")
                
            fields.append(field_data)
            
        # Preview first record to check values
        # Header ends at header_len
        f.seek(header_len)
        if num_records > 0:
            data = f.read(record_len)
            # Just print raw bytes of first record to check encoding
            print(f"First Record Raw: {data}")
            try:
                decoded = data.decode('cp949', errors='ignore')
                print(f"First Record CP949: {decoded}")
            except UnicodeDecodeError:
                pass
            try:
                decoded_utf8 = data.decode('utf-8', errors='ignore')
                print(f"First Record UTF-8: {decoded_utf8}")
            except UnicodeDecodeError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Inspect DBF header/encoding details.")
    parser.add_argument(
        "--shp",
        default=DEFAULT_SHP_PATH,
        help=f"Path to source SHP file (default: {DEFAULT_SHP_PATH})",
    )
    args = parser.parse_args()

    dbf_path = os.path.splitext(args.shp)[0] + ".dbf"
    if os.path.exists(dbf_path):
        read_dbf_header(dbf_path)
    else:
        print(f"DBF not found: {dbf_path}")


if __name__ == "__main__":
    main()

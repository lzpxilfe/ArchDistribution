import os
from qgis.core import QgsVectorLayer, QgsProject

DEFAULT_SOURCE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "insite",
    "현상변경허용기준.shp",
)


def debug_zone_layer(source_path=None):
    print("--- DEBUG ZONE LAYER START ---")
    
    if not source_path:
        source_path = DEFAULT_SOURCE_PATH
    
    if not os.path.exists(source_path):
        print(f"❌ FAIL: Source file not found at {source_path}")
        return

    print(f"✅ Source file found: {source_path}")

    # 2. LOAD LAYER (Robust Mode)
    layer_uri = f"{source_path}|encoding=CP949"
    layer = QgsVectorLayer(layer_uri, "DebugLayer", "ogr")
    
    if not layer.isValid():
        print("❌ FAIL: Layer load failed (isValid=False). Check drivers/locks.")
        return
        
    print(f"✅ Layer loaded valid.")
    print(f"   - Feature Count: {layer.featureCount()}")
    print(f"   - CRS: {layer.crs().authid()}")
    print(f"   - Encoding: {layer.dataProvider().encoding()}")
    
    # 3. CHECK FIELDS
    fields = [f.name() for f in layer.fields()]
    print(f"   - Fields: {fields}")
    
    target_field = None
    for cand in ['구역명', '구역', 'NAME']:
        if cand in fields:
            target_field = cand
            break
            
    if not target_field:
        print(f"❌ FAIL: Target field (구역명) not found in {fields}")
        return
        
    print(f"✅ Target Field Found: {target_field}")

    # 4. CHECK VALUES
    idx = layer.fields().lookupField(target_field)
    unique_vals = layer.uniqueValues(idx)
    print(f"✅ Unique Values: {sorted(list(unique_vals))}")
    
    # 5. SIMULATE SPLIT
    if len(unique_vals) == 0:
        print("❌ FAIL: No unique values found (Empty?)")
    else:
        print("✅ READY to split. Logic seems OK.")
        
    print("--- DEBUG DONE ---")

debug_zone_layer()

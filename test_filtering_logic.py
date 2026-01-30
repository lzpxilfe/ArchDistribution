
# Validates the filtering logic extracted from ArchDistribution

EXCLUDED_CATEGORIES = {
    # Natural Heritage (Nature)
    "동물", "식물", "광물", "지질", "도래지", "번식지", "서식지", "자생지", "수림지", "거석기념물", "노거수", "조류", "포유류",
    
    # Intangible / Mobile Heritage
    "공예기술", "동산문화유산", "음악", "의식", "음식", "무형유산", "연극", "무용",
    "공예", "서적", "전적", "조각", "회화", "예술", "동산",
    
    # Steles / Monuments (Non-building)
    "비갈", "묘비", "선정비", "신도비", "충효비", "공덕비", "순수비"
}

MODERN_ERA_KEYWORDS = {"근대", "일제강점기", "대한제국", "현대"}

def test_filtering(feat_data, settings):
    # Mocking the logic structure
    name = feat_data.get('name', '')
    era = feat_data.get('era', '')
    classification = feat_data.get('classification', [])
    is_vip = feat_data.get('is_vip', False)
    
    logs = []
    should_exclude = False
    
    # 1. Non-Site Filtering
    if settings.get('exclude_non_sites', True):
        for val in classification:
            val = str(val)
            for exc in EXCLUDED_CATEGORIES:
                if exc == val or exc in val:
                    should_exclude = True
                    logs.append(f"[Exclude Non-Site] {name} (Reason: {exc} in {val})")
                    break
            if should_exclude: break
    
    # VIP Override for Non-Site
    if is_vip:
        if should_exclude:
             logs.append(f"[VIP Preserve] {name}")
             should_exclude = False
             
    if should_exclude: return False, logs

    # 2. Era Filtering
    if settings.get('exclude_modern', False):
        if era:
            for mod in MODERN_ERA_KEYWORDS:
                if mod in era:
                    should_exclude = True
                    logs.append(f"[Exclude Era] {name} (Era: {era})")
                    break
    
    if is_vip and should_exclude:
         logs.append(f"[VIP Preserve] {name}")
         should_exclude = False

    if should_exclude: return False, logs
    
    return True, logs

# Test Cases
cases = [
    {
        "data": {"name": "Test Site 1", "era": "청동기", "classification": ["성곽"]},
        "setting": {"exclude_non_sites": True, "exclude_modern": False},
        "expected": True
    },
    {
        "data": {"name": "Modern Factory", "era": "음... 근대", "classification": ["공장"]},
        "setting": {"exclude_non_sites": True, "exclude_modern": True},
        "expected": False
    },
    {
        "data": {"name": "Goryeo Celadon", "era": "고려", "classification": ["공예품", "도자기"]},
        "setting": {"exclude_non_sites": True, "exclude_modern": False},
        "expected": False
    },
    {
        "data": {"name": "VIP Modern Building", "era": "근대", "classification": ["건축"], "is_vip": True},
        "setting": {"exclude_non_sites": True, "exclude_modern": True},
        "expected": True
    }
]

print("Running Tests...\n")
all_passed = True
for i, c in enumerate(cases):
    passed, logs = test_filtering(c['data'], c['setting'])
    result_str = "PASS" if passed == c['expected'] else "FAIL"
    if result_str == "FAIL": all_passed = False
    print(f"Case {i+1}: {result_str}")
    print(f"  Input: {c['data']}")
    print(f"  Settings: {c['setting']}")
    print(f"  Result: {passed} (Expected: {c['expected']})")
    print(f"  Logs: {logs}\n")

if all_passed:
    print("All logic tests passed.")
else:
    print("Some tests failed.")

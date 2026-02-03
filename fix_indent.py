
lines = []
with open('arch_distribution.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation for lines 276-280 (0-indexed 275-279)
# Note: view_file showed lines 270-285.
# Line 276: blank line with spaces?
# Line 277: self.apply_zone_categorical_style(z_clone)
# Line 279: else:
# Line 280: self.log...

# Let's clean up specifically
# Line 277 (idx 276): Should be 28 spaces
lines[276] = " " * 28 + "self.apply_zone_categorical_style(z_clone)\n"

# Line 279 (idx 278): Should be 16 spaces 'else:'
lines[278] = " " * 16 + "else:\n"

# Line 280 (idx 279): Should be 20 spaces 'self.log...'
lines[279] = " " * 20 + 'self.log("알림: 영역 내에 수집된 유적이 없습니다.")\n'

with open('arch_distribution.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Fixed indentation.")

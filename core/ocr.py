import re

# Vietnamese plate regex patterns:
# 2 digits + 1-2 letters (can include digits like F1) + 3-5 digits
# Supports 1-line and 2-line formats
_PLATE_RE = re.compile(
    r'^\d{2}-[A-Z0-9]{1,2}\s+\d{3,5}$'        # 51-F1 12345
    r'|^\d{2}-[A-Z0-9]{1,2}\s+\d{3}\.\d{2}$'  # 51-F1 123.45
    r'|^\d{2}[A-Z0-9]{1,2}-\d{4,5}$'          # 51F1-12345
    r'|^\d{2}[A-Z0-9]{1,2}-\d{3}\.\d{2}$'      # 51F1-123.45
)

def fix_chars(text, is_letters=False, is_digits=False):
    dict_char_to_int = {'O': '0', 'I': '1', 'J': '3', 'A': '4', 'G': '6', 'S': '5', 'B': '8', 'Z': '2', 'Q': '0', 'T': '7'}
    dict_int_to_char = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S', '8': 'B', '2': 'Z', '7': 'T'}
    res = ""
    for char in text:
        if is_digits and char.upper() in dict_char_to_int:
            res += dict_char_to_int[char.upper()]
        elif is_letters and char.upper() in dict_int_to_char:
            res += dict_int_to_char[char.upper()]
        else:
            res += char.upper()
    return res

def is_valid_plate(text):
    """Return True only if text matches a known Vietnamese plate pattern."""
    if not text:
        return False
    # Normalise spaces
    t = re.sub(r'\s+', ' ', text.strip())
    return bool(_PLATE_RE.match(t))

def process_plate(res):
    if not res:
        return None
    res = sorted(res, key=lambda r: r[0][0][1])
    formatted_text = ""

    if len(res) >= 2:
        line1 = re.sub(r'[^a-zA-Z0-9]', '', res[0][1])
        line2 = re.sub(r'[^a-zA-Z0-9]', '', res[1][1])
        prov_code = fix_chars(line1[:2], is_digits=True)
        series = line1[2:]
        if len(series) == 2:
            dict_int_to_char_local = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S', '8': 'B', '2': 'Z'}
            if series[1].isalpha() or series[1] in list(dict_int_to_char_local.values()):
                if series[1] in '0123456789' and series[1] not in dict_int_to_char_local:
                    series = fix_chars(series[0], is_letters=True) + fix_chars(series[1], is_digits=True)
                else:
                    c0 = fix_chars(series[0], is_letters=True)
                    c1 = fix_chars(series[1], is_letters=True) if series[1].isalpha() else fix_chars(series[1], is_digits=True)
                    series = c0 + c1
        elif len(series) == 1:
            series = fix_chars(series[0], is_letters=True)
        line1_fixed = f"{prov_code}-{series}" if series else prov_code
        line2_fixed = fix_chars(line2, is_digits=True)[:5]
        if len(line2_fixed) == 5:
            line2_fixed = f"{line2_fixed[:3]}.{line2_fixed[3:]}"
        elif len(line2_fixed) == 4:
            line2_fixed = f"{line2_fixed[:2]}.{line2_fixed[2:]}"
        formatted_text = f"{line1_fixed} {line2_fixed}"

    elif len(res) == 1:
        text = re.sub(r'[^a-zA-Z0-9]', '', res[0][1])
        if len(text) >= 5:
            prov_code = fix_chars(text[:2], is_digits=True)
            first_letter_idx = -1
            for i, c in enumerate(text[2:]):
                if c.isalpha():
                    first_letter_idx = i + 2
                    break
            if first_letter_idx != -1:
                series = fix_chars(text[first_letter_idx:first_letter_idx+1], is_letters=True)
                rest = fix_chars(text[first_letter_idx+1:], is_digits=True)
                if len(rest) == 5:
                    rest = f"{rest[:3]}.{rest[3:]}"
                formatted_text = f"{prov_code}{series}-{rest}"
            else:
                formatted_text = fix_chars(text, is_digits=True)
        else:
            formatted_text = text

    return formatted_text

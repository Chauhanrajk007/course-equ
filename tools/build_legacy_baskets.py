"""Extract the basket-wise course catalogue from the legacy .docx PRCs.

The 2022 and 2023 PRCs label the semester grid only as "School Core" /
"Program Core" / "Discipline Elective" / "Open Elective". The catalogue tables
3.1 - 3.6 say which section a code belongs to, which is the best available
evidence for a legacy course's basket.

Run once; the result is committed as data/legacy_baskets.json so that the
database can be rebuilt from the consolidated grid alone.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_prc_db import cells, docx_lines, parse_course_row, split_codes  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'data', 'legacy_baskets.json')

SRC = r'C:\Users\Chauhan Raj K\Downloads'
FILES = {
    '2022-2026': '16thSept CBC 2022-2026_PRC.docx',
    '2023-2027': '16THSEPT-CBC 2023-2027_PRC.docx',
}

# catalogue table -> the basket wording used by the legacy PRC
SECTIONS = [
    (r'3\.1\b.*School Core', 'SCHOOL CORE'),
    (r'3\.2\b.*Program Core', 'PROGRAM CORE'),
    (r'3\.3\b.*Discipline Elective', 'DISCIPLINE ELECTIVE'),
    (r'3\.4\b.*Open Elective', 'OPEN ELECTIVE'),
    (r'3\.5\b.*Discipline Elective', 'DISCIPLINE ELECTIVE'),
    (r'3\.6\b.*Open Elective', 'OPEN ELECTIVE'),
]


def catalogue_baskets(filename):
    lines = docx_lines(os.path.join(SRC, filename))
    lo = 0
    for i, ln in enumerate(lines):
        if 'Credit Contribution' in ln:
            lo = i
            break
    hi = len(lines)
    for i in range(lo, len(lines)):
        if re.match(r'^\s*Course Catalogues?:', lines[i], re.I) or \
           re.search(r'(Recommended )?Semester [Ww]ise Course (Grid|Structure|Grid for)',
                     lines[i]):
            hi = i
            break

    out, cur = {}, None
    for i in range(lo, hi):
        ln = lines[i]
        cs = cells(ln)
        joined = ' | '.join(cs) if cs else ln
        if re.search(r'Table\s*3\.\d', joined):
            cur = next((b for pat, b in SECTIONS
                        if re.search(pat, joined, re.I)), None)
            continue
        if re.match(r'^\s*\d+\.\s*List of MOOC', joined, re.I):
            cur = None
            continue
        if not cs or len(cs) < 6 or cur is None:
            continue
        parsed = parse_course_row(cs)
        if not parsed:
            continue
        code = parsed[0]
        for cd in split_codes(code):
            out.setdefault(cd, cur)
    return out


def main():
    data = {}
    for batch, fn in FILES.items():
        data[batch] = catalogue_baskets(fn)
        print('%-9s %d codes' % (batch, len(data[batch])))
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
    print('wrote', OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    main()

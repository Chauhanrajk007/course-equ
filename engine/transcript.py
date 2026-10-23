"""Report-card / transcript parsing.

Accepts .docx, .xlsx, .csv and .pdf and extracts a list of
    (course_code, course_name, credits, grade, semester, month_year, term)
records, plus any student identity fields it can find.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile

from .mapping import Course

CODE_RE = re.compile(r'\b([A-Z]{3,4})\s?-?\s?(\d{3,4}[A-Z]?)\b')
SEM_RE = re.compile(r'\bsem(?:ester)?\.?\s*([1-8]|I{1,3}V?|IV|V)\b', re.I)
DATE_RE = re.compile(
    r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*[-/]?\s*'
    r'(?:\d{4}|20\d{2}))', re.I)
GRADE_RE = re.compile(r'^\s*([A-F]{1,2}[+-]?|NP|ABS|S|E|O|A\+|I|W)\s*$', re.I)
TERM_RE = re.compile(r'\b(ET|ST|MU|End\s*Term|Summer\s*Term|Make\s*-?\s*Up)\b', re.I)
ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8}

IDENTITY_KEYS = {
    'name': ('name of the student', 'student name', 'name'),
    'roll_no': ('roll number', 'roll no', 'rollno', 'usn', 'sid'),
    'program': ('program', 'programme', 'degree'),
    'previous_institution': ('name of the previous institution', 'previous institution',
                             'institution'),
    'admission_batch': ('admission batch', 'batch and semester of admission',
                        'admission batch and last semester'),
    'readmission': ('batch and semester of admission at presidency university',
                    'semester of admission at presidency university', 'readmission batch'),
    'semester': ('semester', 'last semester attended', 'current semester'),
}


class ParseError(Exception):
    pass


# --------------------------------------------------------------- cell readers
def _docx_rows(data: bytes) -> list[list[str]]:
    from lxml import etree
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = etree.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    rows = []
    for child in body:
        if child.tag == W + 'p':
            t = ' '.join(''.join(n.text or '' for n in child.iter()
                                 if n.tag == W + 't').split())
            if t:
                rows.append([t])
        elif child.tag == W + 'tbl':
            for tr in child.findall(W + 'tr'):
                seen, cells = set(), []
                for tc in tr.findall(W + 'tc'):
                    if id(tc) in seen:
                        continue
                    seen.add(id(tc))
                    cells.append(' '.join(
                        ''.join(n.text or '' for n in tc.iter()
                                if n.tag == W + 't').split()))
                rows.append(cells)
    return rows


def _xlsx_rows(data: bytes) -> list[list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    rows = []
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            rows.append(['' if v is None else str(v).strip() for v in r])
    return rows


def _pdf_rows(data: bytes) -> list[list[str]]:
    import pdfplumber
    rows = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                rows.extend([[('' if c is None else str(c).strip()) for c in r]
                             for r in table])
            for line in (page.extract_text() or '').splitlines():
                rows.append([line.strip()])
    return rows


def _csv_rows(data: bytes) -> list[list[str]]:
    text = data.decode('utf-8-sig', errors='replace')
    return [r for r in csv.reader(io.StringIO(text))]


def read_rows(filename: str, data: bytes) -> list[list[str]]:
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext == '.docx':
            return _docx_rows(data)
        if ext in ('.xlsx', '.xlsm'):
            return _xlsx_rows(data)
        if ext == '.pdf':
            return _pdf_rows(data)
        if ext in ('.csv', '.txt'):
            return _csv_rows(data)
    except Exception as e:                                  # noqa: BLE001
        raise ParseError('Could not read %s: %s' % (filename, e)) from e
    raise ParseError('Unsupported file type "%s". Use .docx, .xlsx, .csv or .pdf.'
                     % ext)


# ------------------------------------------------------------------- helpers
def clean(v) -> str:
    return ' '.join(str(v or '').replace('\u00a0', ' ').split())


def find_code(cell: str):
    m = CODE_RE.search(clean(cell).upper().replace(' ', ' '))
    if not m:
        m = CODE_RE.search(clean(cell).upper())
    if not m:
        return None
    return (m.group(1) + m.group(2)).upper()


def parse_sem(text: str):
    m = SEM_RE.search(clean(text))
    if not m:
        return None
    g = m.group(1).upper()
    return int(g) if g.isdigit() else ROMAN.get(g)


def parse_num(v):
    if v is None:
        return None
    s = clean(v)
    m = re.match(r'^-?\d+(?:\.\d+)?$', s)
    return float(s) if m else None


def parse_grade(v):
    s = clean(v)
    if not s or len(s) > 4:
        return None
    return s if GRADE_RE.match(s) else None


# --------------------------------------------------------------- main parser
def parse_transcript(filename: str, data: bytes) -> dict:
    rows = read_rows(filename, data)
    identity, records, headers = {}, [], None

    for row in rows:
        cells = [clean(c) for c in row]
        joined = ' | '.join(c for c in cells if c)

        # ---- identity rows: "Label" in one cell, value in the next ----
        low = joined.lower()
        for key, needles in IDENTITY_KEYS.items():
            if key in identity:
                continue
            for n in needles:
                if low.startswith(n) or ('| ' + n) in low:
                    vals = [c for c in cells if c and c.lower() != n]
                    vals = [v for v in vals
                            if not any(v.lower().startswith(o) for o in
                                       sum((IDENTITY_KEYS[k] for k in
                                            IDENTITY_KEYS if k != key), ()))]
                    if vals:
                        v = vals[-1]
                        # "Name of the Student: TEST STUDENT" -> "TEST STUDENT"
                        m = re.match(r'^[^:]{0,40}:\s*(.+)$', v)
                        if m and m.group(1).strip():
                            v = m.group(1).strip()
                        identity[key] = v
                    break

        # ---- header row? ----
        low_cells = [c.lower() for c in cells]
        if sum(1 for c in low_cells if 'course' in c) >= 1 and \
           any('code' in c for c in low_cells):
            headers = {'code': _find_col(low_cells, ('course code', 'code', 'subject code')),
                       'name': _find_col(low_cells, ('course name', 'subject',
                                                      'course title', 'title', 'name')),
                       'credits': _find_col(low_cells, ('credit', 'credits', 'c')),
                       'grade': _find_col(low_cells, ('grade', 'letter grade', 'result')),
                       'sem': _find_col(low_cells, ('semester', 'sem')),
                       'month': _find_col(low_cells, ('month', 'date', 'session'))}
            continue

        code = None
        for c in cells:
            code = find_code(c)
            if code:
                break
        if not code:
            continue
        if re.search(r'total|credits earned|cgpa|sgpa', low) and len(cells) < 4:
            continue

        name = _pick(cells, headers, 'name') if headers else None
        credits = _pick(cells, headers, 'credits') if headers else None
        grade = _pick(cells, headers, 'grade') if headers else None
        sem = (_pick(cells, headers, 'sem') if headers else None)
        month = (_pick(cells, headers, 'month') if headers else None)

        rec = {'code': code}
        # grade wins over credit column when they look swapped
        gc, gg = parse_num(credits), parse_grade(credits)
        if gg and gc is None:
            grade, credits = credits, None
        rec['credits'] = parse_num(credits)
        rec['grade'] = (parse_grade(grade) or clean(grade) or None)
        rec['name'] = None
        for c in cells:
            if find_code(c) != code and c and not SEM_RE.fullmatch(c) \
                    and not DATE_RE.fullmatch(c) and not GRADE_RE.match(c) \
                    and parse_num(c) is None:
                rec['name'] = c
                break
        rec['semester'] = parse_sem(sem) if sem else parse_sem(joined)
        m = DATE_RE.search(joined)
        rec['month_year'] = clean(m.group(1)) if m else (clean(month) if month else '')
        mt = TERM_RE.search(joined)
        rec['term'] = _canon_term(mt.group(1)) if mt else ''
        records.append(rec)

    return {'identity': identity, 'records': records, 'headers': headers,
            'row_count': len(rows)}


def _canon_term(t):
    t = t.upper()
    return {'END TERM': 'ET', 'SUMMER TERM': 'ST', 'MAKE-UP': 'MU',
            'MAKE UP': 'MU'}.get(t, t)


def _find_col(low_cells, names):
    for i, c in enumerate(low_cells):
        if c in names:
            return i
    for i, c in enumerate(low_cells):
        for n in names:
            if c.startswith(n):
                return i
    return None


def _pick(cells, headers, key):
    i = headers.get(key) if headers else None
    if i is not None and i < len(cells) and clean(cells[i]):
        return clean(cells[i])
    return None


def to_courses(records: list[dict], batch: str) -> list[Course]:
    out, seen = [], set()
    for r in records:
        code = prc_norm(r.get('code'))
        if not code or code in seen:
            continue
        seen.add(code)
        cr = r.get('credits')
        cr = int(cr) if cr is not None and float(cr) == int(cr) else cr
        out.append(Course(batch, code, r.get('name') or None, cr, r.get('grade'),
                          r.get('semester'), r.get('month_year'), r.get('term')))
    return out


def prc_norm(code):
    import re as _re
    return _re.sub(r'\s+', '', str(code or '')).upper()
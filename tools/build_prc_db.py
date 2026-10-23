"""
PRC extractor  --  builds prc_db.json from the official .docx PRC files.
"""
import json
import os
import re
import zipfile
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = r'C:\Users\Chauhan Raj K\Downloads'
OUT = os.path.join(os.path.dirname(HERE), 'data', 'prc_db.json')

FILES = {
    '2022-2026': '16thSept CBC 2022-2026_PRC.docx',
    '2023-2027': '16THSEPT-CBC 2023-2027_PRC.docx',
    '2024-2028': '16th_SEPTEMCBC 2024-2028_PRC_FORMATTED.docx',
    '2025-2029': '16thSEPT-CBC-2025-2029-PRC.docx',
    '2026-2030': '16thSEP-UPDATED-CBC-2026-2030.docx',
}

CANON_ORDER = ['HSMC', 'BSC', 'ESC', 'PCC', 'PEC', 'OEC', 'PRW', 'MAC']
CANON_LABEL = {
    'HSMC': 'Humanities and Social Sciences including Management Courses (HSMC)',
    'BSC':  'Basic Science Courses (BSC)',
    'ESC':  'Engineering Science Courses (ESC)',
    'PCC':  'Professional Core Courses (PCC)',
    'PEC':  'Professional Elective Courses (PEC)',
    'OEC':  'Open Elective Courses (OEC)',
    'PRW':  'Project Work (PRW)',
    'MAC':  'Mandatory Courses (MAC)',
}
BASKET_ALIASES = [
    ('humanities', 'HSMC'), ('basic science', 'BSC'),
    ('engineering science', 'ESC'), ('professional core', 'PCC'),
    ('program core', 'PCC'), ('professional elective', 'PEC'),
    ('discipline elective', 'PEC'), ('open elective', 'OEC'),
    ('project work', 'PRW'), ('mandatory', 'MAC'),
    ('school core', 'ESC'),
]
RAW_TO_CANON = {
    'SCHOOL CORE': 'ESC', 'PROGRAM CORE': 'PCC', 'DISCIPLINE ELECTIVE': 'PEC',
    'OPEN ELECTIVE': 'OEC', 'PROFESSIONAL CORE': 'PCC',
    'PROFESSIONAL ELECTIVE': 'PEC', 'BASIC SCIENCE': 'BSC',
    'ENGINEERING SCIENCE': 'ESC', 'HUMANITIES': 'HSMC', 'HSMC': 'HSMC',
    'BSC': 'BSC', 'ESC': 'ESC', 'PCC': 'PCC', 'PEC': 'PEC', 'OEC': 'OEC',
    'PRW': 'PRW', 'MAC': 'MAC',
}
# Course-code department prefix -> canonical basket (fallback / cross-check)
DEPT_BASKET = [
    ('CBC3', 'PEC'), ('CBC4', 'PEC'), ('CSE3', 'PEC'), ('CSE4', 'PEC'),
    ('CSS3', 'PEC'), ('CSS4', 'PEC'),
    ('CSS7', 'PRW'), ('CSE7', 'PRW'), ('CBC7', 'PRW'), ('CBC5', 'PRW'),
    ('CSS5', 'PCC'), ('CBC2', 'PCC'), ('CSS2', 'PCC'), ('CSE2', 'PCC'),
    ('CBC1', 'PCC'), ('CBC0', 'PCC'),
    ('MAT', 'BSC'), ('PHY', 'BSC'), ('CHE', 'BSC'), ('BIO', 'BSC'),
    ('MEC', 'ESC'), ('CIV', 'ESC'), ('EEE', 'ESC'), ('ECE', 'ESC'), ('CIE', 'ESC'),
    ('ENG', 'HSMC'), ('DES', 'HSMC'), ('FIN', 'HSMC'), ('KAN', 'HSMC'),
    ('HUM', 'HSMC'), ('SOC', 'HSMC'), ('MGMT', 'HSMC'),
    ('PPS', 'MAC'), ('LAW', 'MAC'), ('APT', 'MAC'), ('IRC', 'MAC'),
]
BASKET_TOKEN = re.compile(
    r'^(BSC|ESC|HSMC|PCC|PEC|PRW|MAC|OEC|Program Core|Discipline Elective|'
    r'Open Elective|School Core|Professional Core|Humanities.*|Basic Science.*)$', re.I)
CODE_RE = re.compile(r'^[A-Z]{3,4}\s?\d{3,4}[A-Z]?$')


def dept_basket(code):
    up = re.sub(r'\s+', '', code).upper()
    for pre, b in DEPT_BASKET:
        if up.startswith(pre):
            return b
    if up[:3] in ('CSE', 'CSS', 'CBC'):
        return 'PCC'
    return None


def norm_basket(tok):
    if not tok:
        return None
    return RAW_TO_CANON.get(re.sub(r'\s+', ' ', tok.strip()).upper())


# ---------------------------------------------------------------- docx -> text
def docx_lines(path):
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    lines = []
    for child in body:
        if child.tag == W + 'p':
            t = ' '.join(''.join(n.text or '' for n in child.iter()
                                 if n.tag == W + 't').split())
            if t:
                lines.append(t)
        elif child.tag == W + 'tbl':
            for tr in child.findall(W + 'tr'):
                cells_, seen = [], set()
                for tc in tr.findall(W + 'tc'):
                    if id(tc) in seen:
                        continue
                    seen.add(id(tc))
                    cells_.append(' '.join(
                        ''.join(n.text or '' for n in tc.iter()
                                if n.tag == W + 't').split()))
                lines.append('| ' + ' | '.join(cells_))
    return lines


def cells(line):
    return [c.strip() for c in line[1:].split('|')] if line.startswith('|') else []


def num(x):
    if x is None:
        return None
    x = str(x).strip().replace('\u2013', '-').replace('\u2014', '-')
    if not re.match(r'^-?\d+(\.\d+)?$', x):
        return None
    return int(float(x))


def split_codes(raw):
    """'ENG1001/ENG1002' -> ['ENG1001','ENG1002']  (drops CIVXXXX placeholders)."""
    out = []
    for part in re.split(r'\s*/\s*|\s*,\s*', raw or ''):
        c = re.sub(r'\s+', '', part).upper()
        if CODE_RE.match(c):
            out.append(c)
    return out


def split_ltpc(cs, start=2):
    """Locate the L,T,P,C numeric run after the name column.

    Handles separate columns and a combined '3-0-0-3' cell.
    """
    for i in range(start, len(cs) - 3):
        vals = [num(cs[i]), num(cs[i + 1]), num(cs[i + 2]), num(cs[i + 3])]
        if None not in vals:
            return tuple(vals)
    for i in range(start, len(cs)):
        m = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*$', cs[i])
        if m:
            return tuple(int(g) for g in m.groups())
    return None, None, None, None


ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8}
SEM_CELL = re.compile(r'^\s*Sem(?:ester)?\s*([1-8]|IV|VI|III|VII|VIII|II|I)\s*$', re.I)


def find_code_idx(cs):
    """Course-code column is not fixed across PRCs - locate it.

    A cell may list alternative codes for the same slot, e.g.
    'ENG1001/ENG1002' or 'CSE 1004'."""
    for i, c in enumerate(cs):
        if i == 0:
            continue
        if 'X' in c.upper():
            continue
        if split_codes(c):
            return i
    return -1


def parse_course_row(cs):
    """Return (code, name, L, T, P, C, sem_hint) or None."""
    ci = find_code_idx(cs)
    if ci < 0:
        return None
    code = cs[ci].strip()
    name_idx = -1
    for j in range(ci + 1, len(cs)):
        v = cs[j].strip()
        if v and num(v) is None and not SEM_CELL.match(v) and len(v) > 1:
            name_idx = j
            break
    name = cs[name_idx].strip() if name_idx > 0 else ''
    L = T = P = C = None
    for i in range(max(name_idx, ci) + 1, len(cs) - 3):
        vals = [num(cs[i]), num(cs[i + 1]), num(cs[i + 2]), num(cs[i + 3])]
        if None not in vals:
            L, T, P, C = vals
            break
    else:
        for i in range(max(name_idx, ci) + 1, len(cs)):
            m = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*$', cs[i])
            if m:
                L, T, P, C = (int(g) for g in m.groups())
                break
    sem = None
    for j in range(ci):
        m = SEM_CELL.match(cs[j])
        if m:
            g = m.group(1).upper()
            sem = str(int(g)) if g.isdigit() else str(ROMAN[g])
            break
    return code, name, L, T, P, C, sem


CORE_BASKETS = {'HSMC', 'BSC', 'ESC', 'PCC', 'PRW', 'MAC'}


def add(prog, code, name, L, T, P, C, basket, sem, cyc, tier=1):
    """tier 2 = core basket catalogue, 1 = elective/open list, 0 = semester grid."""
    c = prog['courses'].get(code)
    if c is None:
        prog['courses'][code] = {
            'code': code, 'name': (name or '').strip(), 'L': L, 'T': T, 'P': P, 'C': C,
            'basket': None, 'basket_grid': None, 'basket_tier': -1, 'sem': None,
            'cycles': [], 'sem_cycle': {}}
        c = prog['courses'][code]
    else:
        if c.get('L') is None and L is not None:
            c.update(L=L, T=T, P=P)
        if c.get('C') is None and C is not None:
            c['C'] = C
        if not c.get('name') and name:
            c['name'] = name.strip()
    if not basket:
        return c
    if tier == 0:                       # semester-grid Basket column
        c['basket_grid'] = basket
    # The elective / open-elective lists also quote mandatory courses; the core
    # basket catalogue is the authoritative statement, so never downgrade it.
    if tier > c.get('basket_tier', -1):
        c['basket'] = basket
        c['basket_tier'] = tier
    if sem and not c.get('sem'):
        c['sem'] = sem
    if cyc:
        if cyc not in c['cycles']:
            c['cycles'].append(cyc)
        if sem:
            c['sem_cycle'][cyc] = sem
    elif sem:
        c['sem_cycle'].setdefault('', sem)
    return c


def parse_batch(batch, filename):
    lines = docx_lines(os.path.join(SRC, filename))
    prog = {'batch': batch,
            'start_year': int(batch[:4]),
            'end_year': int(batch[-4:]),
            'program': 'B.Tech. Computer Science and Engineering (Block Chain)',
            'school': 'Presidency School of Artificial Intelligence & Advanced Computing',
            'total_credits': 160,
            'baskets': [], 'courses': {}, 'semesters': {}, 'source_file': filename}

    # ---------------- (a) basket minimums -------------------------------
    for i, ln in enumerate(lines):
        cs = cells(ln)
        if len(cs) >= 3 and cs[0].strip() in ('Sl. No.', 'S.No', 'Sl.No') \
                and re.search(r'basket', cs[1], re.I):
            j = i + 1
            while j < len(lines):
                r = cells(lines[j])
                if len(r) >= 3 and re.match(r'^\d+$', r[0]) and num(r[2]) is not None:
                    nm = r[1].strip()
                    if nm and not nm.lower().startswith('total'):
                        prog['baskets'].append({'name': nm, 'min_credits': num(r[2])})
                elif r and 'total' in r[-1].lower():
                    break
                elif not r:
                    break
                j += 1
            if prog['baskets']:
                break

    # 2022 / 2023 PRCs use the pre-2024 basket names ("School Core",
    # "Program Core", ...). For those the basket is derived from the course-code
    # department, which is the only reliable way to split School Core into
    # BSC / ESC / HSMC / MAC / PRW.
    legacy = any(b['name'].strip().upper() in ('SCHOOL CORE', 'PROGRAM CORE',
                                                'DISCIPLINE ELECTIVE', 'OPEN ELECTIVE')
                 for b in prog['baskets'])
    prog['legacy_baskets'] = legacy

    # ---------------- (b) basket course catalogues ----------------------
    # bounded to the Part-C curriculum region: from the basket summary table
    # up to the per-course narrative catalogues / the semester-wise grids.
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
    cur = tier = None
    for i in range(lo, hi):
        ln = lines[i]
        cs = cells(ln)
        joined = ' | '.join(cs) if cs else ln
        # ---- section headings may be paragraphs OR table rows ----
        m = re.search(r'List of\s+(Humanities|Basic Science|Engineering Science|'
                      r'Professional Core|course in Project Work|Mandatory|School Core)',
                      joined, re.I)
        if m:
            cur = next((b for k, b in BASKET_ALIASES if k in m.group(1).lower()), None)
            tier = 2 if cur in CORE_BASKETS else 1
            continue
        if re.search(r'List of', joined, re.I) and re.search(r'Elective', joined, re.I):
            cur = 'OEC' if re.search(r'Open\s+Elective', joined, re.I) else 'PEC'
            tier = 1
            continue
        if re.search(r'MOOC', joined, re.I) and re.search(r'Elective', joined, re.I):
            cur = 'OEC' if re.search(r'Open', joined, re.I) else 'PEC'
            tier = 1
            continue
        if re.match(r'^\s*\|?\s*Track\s*\d+', joined, re.I):
            cur, tier = 'PEC', 1
            continue
        if not cs:
            if re.match(r'^\s*(Total (No\.? of )?Credits?|TOTAL)\b', ln, re.I):
                cur = None
            continue
        if len(cs) < 6:
            continue
        parsed = parse_course_row(cs)
        if not parsed:
            continue
        code, name, L, T, P, C, _semh = parsed
        bk = None
        for c in reversed(cs):
            if BASKET_TOKEN.match(c.strip()):
                bk = c.strip()
                break
        for cd in split_codes(code):
            add(prog, cd, name, L, T, P, C, norm_basket(bk) or cur, None, None, tier)

    # ---------------- (d) semester-wise grids ---------------------------
    start = None
    for i, ln in enumerate(lines):
        if re.search(r'(Recommended )?Semester [Ww]ise Course (Grid|Structure|Grid for)', ln):
            start = i
    if start is None:
        start = 0

    sem = cyc = None
    for ln in lines[start:]:
        if re.match(r'^\s*Course Catalogues?:', ln, re.I):
            break
        cs = cells(ln)
        joined = ' | '.join(cs)
        m = re.match(r'^\s*(?:\|\s*)?Semester\s*([1-8])\s*[-\u2013\u2014]?\s*'
                     r'(?:([A-Za-z]+)\s*Cycle)?\s*(?:\|\s*Cycle\s*Cycle)?', joined, re.I)
        if m and find_code_idx(cs) < 0:
            sem = m.group(1)
            cyc = (m.group(2).title() + ' Cycle') if m.group(2) else None
            prog['semesters'].setdefault(sem, {'sem': sem, 'cycle': cyc, 'courses': []})
            prog['semesters'][sem]['cycle'] = cyc
            continue
        parsed = parse_course_row(cs) if sem is not None else None
        if not parsed:
            # grand-total row (blank sl.no + blank code, all numeric) ends the grid
            if len(cs) >= 2 and not cs[0].strip() and not cs[1].strip() \
                    and sum(1 for c in cs if num(c) is not None) >= 4:
                break
            continue
        code, name, L, T, P, C, _h = parsed
        bk = None
        for c in reversed(cs):
            if BASKET_TOKEN.match(c.strip()):
                bk = c.strip()
                break
        for cd in split_codes(code):
            prog['semesters'][sem]['courses'].append(
                {'code': cd, 'name': name, 'L': L, 'T': T, 'P': P, 'C': C, 'basket': bk})
            add(prog, cd, name, L, T, P, C, norm_basket(bk), sem, cyc, tier=0)

    # the semester grid is authoritative for LTPC and semester
    for sem, sd in prog['semesters'].items():
        for sc in sd['courses']:
            c = prog['courses'].get(sc['code'])
            if not c:
                continue
            c.setdefault('sem_cycle', {}).setdefault(sd.get('cycle') or '', sem)
            if not c.get('sem'):
                c['sem'] = sem
            if c.get('L') is None and sc['L'] is not None:
                c.update(L=sc['L'], T=sc['T'], P=sc['P'])
            if c.get('C') is None and sc['C'] is not None:
                c['C'] = sc['C']

    # final basket pass: catalogue section > department prefix > grid column
    for code, c in prog['courses'].items():
        c.pop('raw_basket', None)
        if legacy:
            c['basket'] = dept_basket(code) or c.get('basket') or 'PCC'
        else:
            c['basket'] = c.get('basket') or dept_basket(code) \
                or c.get('basket_grid') or 'PCC'
    return prog


def main():
    db = {'canonical_order': CANON_ORDER, 'canonical_label': CANON_LABEL, 'batches': {}}
    for batch, fn in FILES.items():
        p = parse_batch(batch, fn)
        db['batches'][batch] = p
        sems = sorted((k for k in p['semesters'] if k.isdigit()), key=int)
        nosem = [c for c, v in p['courses'].items() if not v.get('sem')]
        noc = [c for c, v in p['courses'].items() if v.get('C') is None]
        print('%-9s courses=%-4d sems=%-30s baskets=%s'
              % (batch, len(p['courses']), ','.join(sems),
                 [b['min_credits'] for b in p['baskets']]))
        print('          sem-counts=%s  no-sem=%d  no-credits=%d'
              % ({k: len(p['semesters'][k]['courses']) for k in sems}, len(nosem), len(noc)))
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=1, ensure_ascii=False)
    print('\nwrote', OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    main()
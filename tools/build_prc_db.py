"""PRC extractor  --  builds data/prc_db.json from the consolidated PRC grid.

Source: data/prc_grid.xlsx, the PSAIAC-consolidated programme and credit grid
(one row per course, per programme, per batch).  It carries the course code,
name, L-T-P-C, semester and basket explicitly, so no table-shape guessing is
needed the way the old .docx extractor had to do it.

Two things the grid does not carry are supplied here:

  * basket minimum credits, transcribed from the "Summary of Mandatory Courses
    and Minimum Credit Contribution from various Baskets" table of each PRC
    (see MINIMA below);
  * the real basket of a legacy (2022 / 2023) "School Core" course.  Those PRCs
    label the whole foundation block as one basket.  The basket is recovered
    from the same course in a later, basket-explicit PRC of any programme, and
    failing that from the legacy PRC's own basket-wise catalogue
    (data/legacy_baskets.json, produced by tools/build_legacy_baskets.py).

Elective slots are printed as placeholders (CSSXXXX, XXXXXXX).  Several slots
share one printed code, so every course is stored under a unique uid and keeps
the printed code in its "code" field; the report prints "code".
"""
from __future__ import annotations

import json
import os
import re

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GRID = os.path.join(ROOT, 'data', 'prc_grid.xlsx')
LEGACY_MAP = os.path.join(ROOT, 'data', 'legacy_baskets.json')
OUT = os.path.join(ROOT, 'data', 'prc_db.json')

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

SCHOOL_NAME = 'Presidency School of Artificial Intelligence & Advanced Computing'

# Batches whose PRC names the foundation block only as "School Core".
LEGACY = ('2022-2026', '2023-2027')

# Minimum credits per basket, from each PRC's own basket summary table.
MINIMA = {
    '2022-2026': {'LEGACY_SCHOOL_CORE': 61, 'LEGACY_PROGRAM_CORE': 60,
                  'LEGACY_DISCIPLINE_ELECTIVE': 30, 'LEGACY_OPEN_ELECTIVE': 9},
    '2023-2027': {'LEGACY_SCHOOL_CORE': 68, 'LEGACY_PROGRAM_CORE': 65,
                  'LEGACY_DISCIPLINE_ELECTIVE': 18, 'LEGACY_OPEN_ELECTIVE': 9},
    '2024-2028': {'HSMC': 10, 'BSC': 17, 'ESC': 23, 'PCC': 70, 'PEC': 18,
                  'OEC': 6, 'PRW': 16, 'MAC': 0},
    '2025-2029': {'HSMC': 10, 'BSC': 24, 'ESC': 22, 'PCC': 64, 'PEC': 18,
                  'OEC': 6, 'PRW': 16, 'MAC': 0},
    '2026-2030': {'HSMC': 12, 'BSC': 24, 'ESC': 20, 'PCC': 64, 'PEC': 18,
                  'OEC': 6, 'PRW': 16, 'MAC': 0},
}
TOTAL_CREDITS = 160

# grid basket wording -> canonical basket
RAW_TO_CANON = {
    'PCC': 'PCC', 'PROGRAM CORE': 'PCC', 'PROFESSIONAL CORE': 'PCC',
    'ESC': 'ESC', 'ENGINEERING SCIENCE': 'ESC',
    'BSC': 'BSC', 'BASIC SCIENCE': 'BSC',
    'HSMC': 'HSMC', 'HUMANITIES': 'HSMC',
    'PEC': 'PEC', 'DISCIPLINE ELECTIVE': 'PEC', 'PROFESSIONAL ELECTIVE': 'PEC',
    'OEC': 'OEC', 'OPEN ELECTIVE': 'OEC', 'OE': 'OEC',
    'PRW': 'PRW', 'PROJECT WORK': 'PRW',
    'MAC': 'MAC', 'MANDATORY': 'MAC',
}
# legacy catalogue section -> basket (SCHOOL CORE is split further below)
LEGACY_SECTION = {
    'PROGRAM CORE': 'PCC', 'DISCIPLINE ELECTIVE': 'PEC', 'OPEN ELECTIVE': 'OEC',
    'HUMANITIES': 'HSMC', 'BASIC SCIENCE': 'BSC', 'ENGINEERING SCIENCE': 'ESC',
    'MANDATORY': 'MAC', 'PROJECT WORK': 'PRW',
}
# Course-code department prefix -> canonical basket (last resort)
DEPT_BASKET = [
    ('CSE', 'PCC'), ('CSS', 'PCC'), ('CBC', 'PCC'), ('CBD', 'PCC'),
    ('CCS', 'PCC'), ('CDV', 'PCC'), ('CIT', 'PCC'), ('CSD', 'PCC'),
    ('CAI', 'PCC'), ('ADS', 'PCC'), ('RAI', 'PCC'),
    ('MAT', 'BSC'), ('PHY', 'BSC'), ('CHE', 'BSC'), ('BIO', 'BSC'),
    ('MEC', 'ESC'), ('CIV', 'ESC'), ('EEE', 'ESC'), ('ECE', 'ESC'),
    ('CIE', 'ESC'), ('ISE', 'ESC'),
    ('ENG', 'HSMC'), ('DES', 'HSMC'), ('FIN', 'HSMC'), ('KAN', 'HSMC'),
    ('HUM', 'HSMC'), ('SOC', 'HSMC'), ('MGMT', 'HSMC'), ('MGT', 'HSMC'),
    ('PPS', 'MAC'), ('LAW', 'MAC'), ('APT', 'MAC'), ('IRC', 'MAC'),
]
CODE_RE = re.compile(r'^[A-Z]{3,4}\d{3,4}[A-Z]?$')


def norm_code(v) -> str:
    return re.sub(r'\s+', '', str(v or '')).replace('\u00a0', '').upper()


def norm_basket(v):
    if v is None:
        return None
    key = re.sub(r'\s+', ' ', str(v)).replace('\u00a0', ' ').strip().upper()
    return RAW_TO_CANON.get(key)


def dept_basket(code) -> str | None:
    up = norm_code(code)
    for pre, b in DEPT_BASKET:
        if up.startswith(pre):
            return b
    return None


def split_codes(raw):
    """'ENG1001/ENG1002' -> ['ENG1001', 'ENG1002']; drops nothing but junk."""
    out = []
    for part in re.split(r'\s*/\s*|\s*,\s*', str(raw or '')):
        c = norm_code(part)
        if CODE_RE.match(c):
            out.append(c)
    return out


def num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return int(x)
    s = str(x).strip().replace('\u2013', '-').replace('\u2014', '-')
    if re.match(r'^-?\d+(\.\d+)?$', s):
        return int(float(s))
    return None


def read_grid(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hdr = ['' if h is None else str(h).strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rows[1:]:
        g = lambda k: r[idx[k]] if k in idx else None      # noqa: E731
        code_raw = str(g('Course Code') or '').strip()
        codes = split_codes(code_raw)
        if not codes:
            continue
        out.append({
            'school': str(g('School') or '').strip(),
            'department': ' '.join(str(g('Department') or '').split()),
            'program': ' '.join(str(g('Program') or '').split()),
            'prog_code': norm_code(g('Program Code')),
            'batch': str(g('Batch') or '').strip(),
            'sem': num(g('Semester')),
            'codes': codes,
            'code': norm_code(codes[0]),
            'name': ' '.join(str(g('Course Name') or '').split()),
            'L': num(g('L')), 'T': num(g('T')),
            'P': num(g('P')), 'C': num(g('C')),
            'basket_raw': g('Basket'),
        })
    return out


def main():
    rows = read_grid(GRID)
    legacy_map = {}
    if os.path.exists(LEGACY_MAP):
        with open(LEGACY_MAP, encoding='utf-8') as f:
            legacy_map = json.load(f)

    # basket of a code as stated by any basket-explicit (post-legacy) PRC
    modern_basket = {}
    for r in rows:
        if r['batch'] in LEGACY:
            continue
        b = norm_basket(r['basket_raw'])
        if b:
            modern_basket.setdefault(r['code'], b)

    batches = {}
    programs = {}
    for r in rows:
        batch, prog = r['batch'], r['prog_code']
        if not batch or not prog:
            continue
        b = batches.setdefault(batch, {
            'batch': batch, 'start_year': int(batch[:4]), 'end_year': int(batch[-4:]),
            'programs': {}})
        if batch in LEGACY:
            section = (legacy_map.get(batch) or {}).get(r['code'])
            if section and section != 'SCHOOL CORE':
                basket = LEGACY_SECTION.get(section)
            else:
                basket = None
            basket = basket or modern_basket.get(r['code']) \
                or dept_basket(r['code']) or norm_basket(r['basket_raw']) or 'PCC'
        else:
            basket = norm_basket(r['basket_raw']) or dept_basket(r['code']) or 'PCC'

        p = b['programs'].get(prog)
        if p is None:
            p = b['programs'][prog] = {
                'batch': batch, 'start_year': int(batch[:4]),
                'end_year': int(batch[-4:]), 'program_code': prog,
                'program': r['department'] or r['program'],
                'program_short': r['program'],
                'school_code': r['school'],
                'school': SCHOOL_NAME,
                'total_credits': TOTAL_CREDITS,
                'legacy_baskets': batch in LEGACY,
                'baskets': [], 'courses': {}, 'semesters': {},
                'source_file': os.path.basename(GRID),
            }
            programs.setdefault(prog, {
                'code': prog, 'name': r['program'],
                'department': r['department'], 'school_code': r['school'],
                'school': SCHOOL_NAME})

        for code in r['codes']:
            uid = code
            n = 1
            while uid in p['courses']:
                n += 1
                uid = '%s#%d' % (code, n)
            rec = {'code': code, 'uid': uid, 'name': r['name'],
                   'L': r['L'], 'T': r['T'], 'P': r['P'], 'C': r['C'],
                   'basket': basket, 'basket_grid': norm_basket(r['basket_raw']),
                   'sem': str(r['sem']) if r['sem'] else None,
                   'cycles': [], 'sem_cycle': {}}
            p['courses'][uid] = rec
            if r['sem']:
                sd = p['semesters'].setdefault(str(r['sem']),
                                               {'sem': str(r['sem']),
                                                'cycle': None, 'courses': []})
                sd['courses'].append({'uid': uid, 'code': code, 'name': r['name'],
                                      'L': r['L'], 'T': r['T'], 'P': r['P'],
                                      'C': r['C'], 'basket': basket})

    # basket minima + totals
    for batch, b in batches.items():
        mins = MINIMA.get(batch)
        for prog, p in b['programs'].items():
            if mins:
                p['baskets'] = [{'code': k, 'name': CANON_LABEL.get(k, k),
                                 'min_credits': v} for k, v in mins.items()]
                p['total_credits'] = sum(mins.values())
            else:
                tot = {}
                for c in p['courses'].values():
                    tot[c['basket']] = tot.get(c['basket'], 0) + (c['C'] or 0)
                p['baskets'] = [{'code': k, 'name': CANON_LABEL.get(k, k),
                                 'min_credits': v}
                                for k, v in tot.items() if k in CANON_ORDER]
                p['total_credits'] = sum(tot.values())

    db = {'schema': 2, 'canonical_order': CANON_ORDER,
          'canonical_label': CANON_LABEL, 'programs': programs,
          'batches': batches}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=1, ensure_ascii=False)

    for batch in sorted(batches):
        progs = sorted(batches[batch]['programs'])
        print('%-10s %2d programmes: %s' % (batch, len(progs), ' '.join(progs)))
    for prog in sorted(programs):
        bs = [b for b in sorted(batches) if prog in batches[b]['programs']]
        print('  %-5s %-45s %s' % (prog, programs[prog]['name'][:45],
                                   ' '.join(bs)))
    print('\nwrote %s  %d bytes' % (OUT, os.path.getsize(OUT)))


if __name__ == '__main__':
    main()

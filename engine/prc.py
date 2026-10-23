"""Access layer over the extracted PRC database (data/prc_db.json)."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'data', 'prc_db.json')

FAILING_GRADES = {'F', 'NP', 'FAIL', 'ABS', 'ABSENT', 'W', 'WITHHELD', 'I', 'INCOMPLETE'}


@lru_cache(maxsize=1)
def load_db() -> dict:
    with open(DATA_PATH, encoding='utf-8') as f:
        return json.load(f)


def batches() -> list[str]:
    return sorted(load_db()['batches'])


def batch_year(batch: str) -> int:
    """Admission year of a batch label such as '2024-2028' or just '2024'."""
    b = load_db()['batches'].get(batch)
    if b:
        return b['start_year']
    m = re.match(r'(\d{4})', str(batch))
    return int(m.group(1)) if m else 0


def resolve_batch(label) -> str | None:
    """Accept '2024', '2024-2028', '24' and return the canonical batch key."""
    db = load_db()
    if label in db['batches']:
        return label
    s = str(label).strip()
    if '-' in s:
        return s if s in db['batches'] else None
    if re.fullmatch(r'\d{4}', s):
        for k in db['batches']:
            if k.startswith(s):
                return k
    if re.fullmatch(r'\d{2}', s):
        for k in db['batches']:
            if k.startswith('20' + s):
                return k
    return None


def program(batch: str) -> dict:
    return load_db()['batches'][batch]


def courses(batch: str) -> dict:
    return program(batch)['courses']


def course(batch: str, code: str) -> dict | None:
    return courses(batch).get(norm(code))


def norm(code) -> str:
    return re.sub(r'\s+', '', str(code or '')).upper()


def basket_label(batch: str) -> dict:
    """canonical basket code -> the label wording used by that PRC."""
    p = program(batch)
    label = {}
    for b in p['baskets']:
        m = re.findall(r'\(([A-Z]{3,4})\)', b['name'])
        code = m[-1].upper() if m else None
        if code is None:
            low = b['name'].lower()
            code = next((c for c in load_db()['canonical_order']
                         if c.lower() in low or low.split()[0] == c.lower()), None)
        if code:
            label[code] = b['name']
    return label


def basket_minimums(batch: str) -> dict:
    """canonical basket code -> minimum credits (mapped from the PRC's own table)."""
    p = program(batch)
    out, unmapped = {}, []
    for b in p['baskets']:
        m = re.findall(r'\(([A-Z]{3,4})\)', b['name'])
        code = m[-1].upper() if m else None
        if code is None:
            low = b['name'].lower()
            for c in load_db()['canonical_order']:
                if low.startswith(c.lower()) or low.split()[0] == c.lower():
                    code = c
                    break
        if code:
            out[code] = b['min_credits']
        else:
            unmapped.append(b)
    for b in unmapped:                      # legacy PRCs: 4 buckets -> 8 canonical
        low = b['name'].lower()
        key = None
        if 'school core' in low:
            key = 'LEGACY_SCHOOL_CORE'
        elif 'program core' in low:
            key = 'LEGACY_PROGRAM_CORE'
        elif 'discipline elective' in low:
            key = 'LEGACY_DISCIPLINE_ELECTIVE'
        elif 'open elective' in low:
            key = 'LEGACY_OPEN_ELECTIVE'
        if key:
            out[key] = b['min_credits']
    return out


def semester_courses(batch: str) -> dict:
    """semester number (str) -> list of course records, ordered as in the PRC."""
    p = program(batch)
    out = {}
    for s, sd in p['semesters'].items():
        if not s.isdigit():
            continue
        out[int(s)] = sd['courses']
    return dict(sorted(out.items()))


def semester_of(batch: str, code: str) -> int | None:
    c = course(batch, code)
    if not c:
        return None
    s = c.get('sem')
    return int(s) if s and str(s).isdigit() else None


def cycles_of(batch: str, code: str) -> list:
    c = course(batch, code)
    return list(c.get('cycles') or []) if c else []


DEPT_BASKET = [
    ('CBC3', 'PEC'), ('CBC4', 'PEC'), ('CSE3', 'PEC'), ('CSE4', 'PEC'),
    ('CSS3', 'PEC'), ('CSS4', 'PEC'),
    ('CSS7', 'PRW'), ('CSE7', 'PRW'), ('CBC7', 'PRW'), ('CBC5', 'PRW'),
    ('CSS5', 'PCC'), ('CBC2', 'PCC'), ('CSS2', 'PCC'), ('CSE2', 'PCC'),
    ('CBC1', 'PCC'), ('CBC0', 'PCC'),
    ('MAT', 'BSC'), ('PHY', 'BSC'), ('CHE', 'BSC'), ('BIO', 'BSC'),
    ('MEC', 'ESC'), ('CIV', 'ESC'), ('EEE', 'ESC'), ('ECE', 'ESC'),
    ('CIE', 'ESC'),
    ('ENG', 'HSMC'), ('DES', 'HSMC'), ('FIN', 'HSMC'), ('KAN', 'HSMC'),
    ('HUM', 'HSMC'), ('SOC', 'HSMC'), ('MGMT', 'HSMC'),
    ('PPS', 'MAC'), ('LAW', 'MAC'), ('APT', 'MAC'), ('IRC', 'MAC'),
]


def dept_basket(code) -> str | None:
    """Infer a basket from the course-code department.

    Needed for report-card codes that are absent from the admission-batch PRC,
    which happens when a PRC is re-issued or the syllabus changed mid-cohort.
    """
    up = norm(code)
    for pre, b in DEPT_BASKET:
        if up.startswith(pre):
            return b
    if up[:3] in ('CSE', 'CSS', 'CBC'):
        return 'PCC'
    return None


def is_passed(grade) -> bool:
    if grade is None:
        return True
    g = str(grade).strip().upper()
    if not g:
        return True
    return g not in FAILING_GRADES


def basket_totals(batch: str, codes) -> dict:
    """Sum credits per canonical basket for a list of course codes."""
    tot = {}
    for code in codes:
        c = course(batch, code)
        if not c:
            continue
        b = c.get('basket') or 'PCC'
        tot[b] = tot.get(b, 0) + (c.get('C') or 0)
    return tot
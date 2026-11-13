"""Access layer over the extracted PRC database (data/prc_db.json).

A PRC is identified by (batch, programme).  A batch such as "2024-2028" is
shared by every B.Tech. programme of the school (Cyber Security, AI & ML, Block
Chain, ...), and each programme has its own course grid, so every accessor
takes an optional programme code and falls back to the batch's first
programme.  Passing the right programme matters: a CAI student's "Essentials of
AI" is not the same course as a CBC student's "Smart Contract and Solidity".

Courses are keyed by a unique id, not by the printed code: elective slots are
printed as placeholders (CSSXXXX, XXXXXXX) and several slots share one printed
code.  rec["code"] is what the report prints.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'data', 'prc_db.json')

FAILING_GRADES = {'F', 'NP', 'FAIL', 'ABS', 'ABSENT', 'W', 'WITHHELD', 'I', 'INCOMPLETE'}

ROLL_PROGRAM = re.compile(r'^\s*\d{4,5}\s*([A-Z]{2,4})', re.I)


@lru_cache(maxsize=1)
def load_db() -> dict:
    with open(DATA_PATH, encoding='utf-8') as f:
        return json.load(f)


def norm(code) -> str:
    return re.sub(r'\s+', '', str(code or '')).replace('\u00a0', '').upper()


# ------------------------------------------------------------------ batches
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


# --------------------------------------------------------------- programmes
def programs() -> dict:
    return load_db()['programs']


def programs_of(batch: str) -> list[str]:
    b = load_db()['batches'].get(batch)
    return sorted(b['programs']) if b else []


def program_for_roll(roll) -> str | None:
    """'20231CAI0033' -> 'CAI'.  Only returns codes the database knows."""
    m = ROLL_PROGRAM.match(str(roll or ''))
    if not m:
        return None
    code = m.group(1).upper()
    return code if code in programs() else None


def resolve_program(batch: str, prog=None) -> str | None:
    """Return a programme code valid for the batch, or the batch's first."""
    avail = programs_of(batch)
    if not avail:
        return None
    if prog:
        p = str(prog).strip().upper()
        if p in avail:
            return p
        for k, v in programs().items():
            if p and (p == k or p in v['name'].upper()
                      or v['name'].upper() in p) and k in avail:
                return k
    return avail[0]


# ------------------------------------------------------------------- lookup
def program(batch: str, prog=None) -> dict:
    b = load_db()['batches'][batch]
    code = resolve_program(batch, prog)
    return b['programs'][code]


def courses(batch: str, prog=None) -> dict:
    return program(batch, prog)['courses']


@lru_cache(maxsize=256)
def _code_index(batch: str, prog: str) -> dict:
    out = {}
    for uid, rec in load_db()['batches'][batch]['programs'][prog]['courses'].items():
        out.setdefault(rec.get('code') or uid, uid)
    return out


def course(batch: str, code, prog=None) -> dict | None:
    p = resolve_program(batch, prog)
    if not p:
        return None
    uid = _code_index(batch, p).get(norm(code))
    if not uid:
        return None
    return load_db()['batches'][batch]['programs'][p]['courses'][uid]


def semester_courses(batch: str, prog=None) -> dict:
    """semester number (int) -> list of course records, ordered as in the PRC."""
    p = program(batch, prog)
    out = {}
    for s, sd in p['semesters'].items():
        if not s.isdigit():
            continue
        out[int(s)] = sd['courses']
    return dict(sorted(out.items()))


def semester_of(batch: str, code, prog=None) -> int | None:
    c = course(batch, code, prog)
    if not c:
        return None
    s = c.get('sem')
    return int(s) if s and str(s).isdigit() else None


def cycles_of(batch: str, code, prog=None) -> list:
    c = course(batch, code, prog)
    return list(c.get('cycles') or []) if c else []


# --------------------------------------------------------------- baskets
def basket_label(batch: str, prog=None) -> dict:
    """canonical basket code -> the label wording used by that PRC."""
    p = program(batch, prog)
    label = {}
    for b in p['baskets']:
        code = b.get('code')
        if code and code in load_db()['canonical_order']:
            label[code] = b['name']
    return label


def basket_minimums(batch: str, prog=None) -> dict:
    """canonical basket code -> minimum credits (from the PRC's own table)."""
    p = program(batch, prog)
    out = {}
    for b in p['baskets']:
        code = b.get('code')
        if code:
            out[code] = b['min_credits']
    return out


def basket_totals(batch: str, codes, prog=None) -> dict:
    """Sum credits per canonical basket for a list of course codes."""
    tot = {}
    for code in codes:
        c = course(batch, code, prog)
        if not c:
            continue
        b = c.get('basket') or 'PCC'
        tot[b] = tot.get(b, 0) + (c.get('C') or 0)
    return tot


DEPT_BASKET = [
    ('CBC3', 'PEC'), ('CBC4', 'PEC'), ('CSE3', 'PEC'), ('CSE4', 'PEC'),
    ('CSS3', 'PEC'), ('CSS4', 'PEC'),
    ('CSS7', 'PRW'), ('CSE7', 'PRW'), ('CBC7', 'PRW'), ('CBC5', 'PRW'),
    ('CSS5', 'PCC'), ('CBC2', 'PCC'), ('CSS2', 'PCC'), ('CSE2', 'PCC'),
    ('CBC1', 'PCC'), ('CBC0', 'PCC'),
    ('MAT', 'BSC'), ('PHY', 'BSC'), ('CHE', 'BSC'), ('BIO', 'BSC'),
    ('MEC', 'ESC'), ('CIV', 'ESC'), ('EEE', 'ESC'), ('ECE', 'ESC'),
    ('CIE', 'ESC'), ('ISE', 'ESC'),
    ('ENG', 'HSMC'), ('DES', 'HSMC'), ('FIN', 'HSMC'), ('KAN', 'HSMC'),
    ('HUM', 'HSMC'), ('SOC', 'HSMC'), ('MGMT', 'HSMC'), ('MGT', 'HSMC'),
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
    if up[:3] in ('CSE', 'CSS', 'CBC', 'CBD', 'CCS', 'CDV', 'CIT', 'CSD',
                   'CAI', 'ADS', 'RAI'):
        return 'PCC'
    return None


def is_passed(grade) -> bool:
    if grade is None:
        return True
    g = str(grade).strip().upper()
    if not g:
        return True
    return g not in FAILING_GRADES

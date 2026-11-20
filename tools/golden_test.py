"""Golden test: reproduce the university's own Annexure-A mapping.

The five report cards are scans, so the Annexure-A documents shipped alongside
them are the only machine-readable record of what the mapping *should* be.  This
script parses each Annexure, rebuilds the student's old-PRC course list from it,
runs the real engine, and compares the engine's Table I against the document.

Run:  .venv\\Scripts\\python.exe tools\\golden_test.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import prc                                          # noqa: E402
from engine.mapping import build_mapping                        # noqa: E402
from engine.transcript import to_courses                        # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _inspect_docx import docx_lines                            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'new data to train')

GRADE_RE = re.compile(r'\b(A\+|A|B\+|B|C\+|C|D|E|F|S|O|NP)\b')


def cells(line: str) -> list[str]:
    if not line.startswith('|'):
        return []
    return [c.strip() for c in line.strip().strip('|').split('|')]


def grade_of(text: str) -> str | None:
    hits = GRADE_RE.findall(text or '')
    return hits[-1] if hits else None


def parse_annexure(path: str) -> dict:
    """-> {old_batch, new_batch, pairs{old->new}, failed[], exempt[], remove[],
           last_sem, name, roll, baskets, summary}"""
    lines = docx_lines(path)
    out = {'pairs': {}, 'failed': [], 'exempt': [], 'remove': [],
           'baskets': {}, 'summary': {}, 'last_sem': 4, 'name': '', 'roll': ''}
    section = None
    for ln in lines:
        low = ln.lower()
        if 'admission batch' in low and 'batch' in low:
            m = re.search(r'batch[:\s]*(\d{4})', low)
            if m:
                out['old_batch'] = m.group(1)
            m = (re.search(r'semester[:\s]*([ivx]+|\d+)', low)
                 or re.search(r'(\d)\s*(?:st|nd|rd|th)\s*sem', low))
            if m:
                out['last_sem'] = _roman(m.group(1))
            continue
        if 'rejoining' in low and 'batch' in low or 'readmission' in low and 'batch' in low:
            m = re.search(r'batch[:\s]*(\d{4})', low)
            if m:
                out['new_batch'] = m.group(1)
            continue

        if 'failed/np graded courses' in low:
            section = 'II'
            continue
        if 'exemption of course' in low:
            section = 'III'
            continue
        if 'additional course' in low:
            section = 'IV'
            continue
        if 'for removal from the transcript' in low:
            section = 'V'
            continue
        if low.startswith('basket wise mapping'):
            section = 'BASKET'
            continue
        if low.strip().startswith('summary'):
            section = 'SUMMARY'
            continue

        cs = cells(ln)
        if not cs:
            continue

        if low.startswith('|') and 'name of the student' in low:
            out['name'] = cs[-1]
            continue
        if low.startswith('|') and 'roll number' in low:
            out['roll'] = cs[-1]
            continue

        if section is None and len(cs) == 15 and _code(cs[0]):
            old = _code(cs[7])
            if old:
                out['pairs'][old] = {'new': _code(cs[0]), 'new_name': cs[1],
                                     'old_C': _int(cs[12]),
                                     'grade': grade_of(cs[14]),
                                     'sem': _sem_of(cs[14]),
                                     'basket': cs[13] or cs[6]}
            continue
        if section == 'II' and len(cs) >= 8 and _code(cs[1]):
            out['failed'].append({'code': _code(cs[1]), 'C': _int(cs[6]),
                                  'basket': cs[7]})
            continue
        if section == 'III' and len(cs) >= 13 and _code(cs[0]):
            out['exempt'].append({'old': _code(cs[0]), 'old_C': _int(cs[5]),
                                  'new': _code(cs[6]), 'new_C': _int(cs[11])})
            continue
        if section == 'V' and len(cs) >= 8 and _code(cs[1]) and _code(cs[1]) != 'NIL':
            out['remove'].append({'code': _code(cs[1]), 'C': _int(cs[6])})
            continue
        if section == 'BASKET' and len(cs) >= 4 and re.match(r'^[A-Z]+$', cs[0]):
            out['baskets'][cs[0]] = (_int(cs[1]), _int(cs[2]), _int(cs[3]))
            continue
        if section == 'SUMMARY' and len(cs) >= 3 and _int(cs[2]) is not None:
            out['summary'].setdefault('vals', []).append(_int(cs[2]))
            continue
    return out


def _roman(s: str) -> int:
    m = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8}
    s = str(s).strip().lower().rstrip('.')
    return m.get(s, int(s) if s.isdigit() else 0)


def _code(v: str) -> str:
    return prc.norm(v) if v and re.match(r'^[A-Z]{3,4}\d{3,4}[A-Z]?$',
                                         prc.norm(v)) else ''


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _sem_of(text: str):
    m = re.search(r'(\d)\s*(?:st|nd|rd|th)?\s*(?:sem|semester)', text or '', re.I)
    if not m:
        m = re.search(r'(?:sem|semester)\s*(\d)', text or '', re.I)
    return int(m.group(1)) if m else None


def transcript_from(annex: dict) -> list[dict]:
    """The student's old-PRC record, rebuilt from the Annexure itself."""
    recs = []
    for old, info in annex['pairs'].items():
        recs.append({'code': old, 'name': '', 'credits': info.get('old_C'),
                     'grade': info['grade'], 'semester': info['sem'],
                     'month_year': '', 'term': ''})
    for f in annex['failed']:
        recs.append({'code': f['code'], 'name': '', 'credits': f.get('C'),
                     'grade': 'F', 'semester': None, 'month_year': '', 'term': ''})
    for x in annex['exempt']:
        recs.append({'code': x['old'], 'name': '', 'credits': x.get('old_C'),
                     'grade': 'B', 'semester': None, 'month_year': '', 'term': ''})
    for r in annex['remove']:
        recs.append({'code': r['code'], 'name': '', 'credits': r.get('C'),
                     'grade': 'F', 'semester': None, 'month_year': '', 'term': ''})
    return recs


def check(filename: str) -> bool:
    annex = parse_annexure(os.path.join(DATA, filename))
    old = prc.resolve_batch(annex.get('old_batch', ''))
    new = prc.resolve_batch(annex.get('new_batch', ''))
    prog = prc.program_for_roll(annex.get('roll'))
    print('=' * 92)
    print('%s  (%s -> %s, %s, last sem %s)'
          % (annex.get('name'), old, new, prog, annex['last_sem']))
    if not (old and new and prog):
        print('  could not resolve batch/programme from the Annexure')
        return False

    records = transcript_from(annex)
    courses = to_courses(records, old, prog)
    res = build_mapping(old, new, courses, last_completed_sem=annex['last_sem'],
                        use_llm=False, program=prog)

    got = {}
    for p in res['pairs']:
        for uid in p['new_codes']:
            rec = prc.courses(new, prog).get(uid, {})
            got.setdefault(p['old']['code'], []).append(rec.get('code') or uid)

    ok = 0
    bad = []
    for old_code, info in annex['pairs'].items():
        want = info['new']
        have = got.get(old_code, [])
        if not want:
            if not have:
                ok += 1
            else:
                bad.append('%s -> %s (expected: not mapped)' % (old_code, have))
        elif want in have:
            ok += 1
        else:
            bad.append('%s -> %s (expected %s)' % (old_code, have or '-', want))
    print('  Table I pairs reproduced: %d/%d' % (ok, len(annex['pairs'])))
    for b in bad[:20]:
        print('    x', b)

    # summary block
    s = res['summary']
    print('  summary  A=%s B=%s C=%s D=%s E=%s F=%s total=%s'
          % (s[0][2], s[1][2], s[2][2], s[3][2], s[4][2], s[5][2],
             res['summary_total']))
    want = annex['summary'].get('vals', [])
    if len(want) >= 6:
        print('  expected A=%s B=%s C=%s D=%s E=%s F=%s total=%s'
              % tuple(want[:6] + [want[6] if len(want) > 6 else '?']))
    print('  baskets  engine: %s' % {b['code']: (b['min'], b['done'])
                                     for b in res['baskets']})
    print('  baskets  expected: %s' % annex['baskets'])
    return not bad


def main() -> int:
    files = [f for f in sorted(os.listdir(DATA))
             if f.lower().endswith('.docx')]
    if not files:
        print('no Annexure .docx found in %s' % DATA)
        return 1
    allok = True
    for f in files:
        allok = check(f) and allok
    print('\n%s' % ('ALL GOLDEN PAIRS REPRODUCED' if allok
                    else 'SOME GOLDEN PAIRS DIFFER'))
    return 0 if allok else 1


if __name__ == '__main__':
    raise SystemExit(main())

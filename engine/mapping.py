"""Course equivalence / credit-mapping engine.

Given a student's transcript (admission-batch courses with grades) and a pair of
PRC batches (admitted -> readmitted), produce the Annexure-A mapping exactly as
the university template expects:

    Table I    Course Mapping, semester-wise  (new PRC  <->  old PRC)
    Table II   Failed / NP graded courses in the old PRC
    Table III  Exemptions (passed old courses with no new counterpart)
    Table IV   Additional courses needed to make the credits match
    Table V    Old courses to be struck off the transcript
    Basket-wise credit position + Summary block

Matching policy (in order):
    0  manual override chosen by the HoD in the review screen
    1  identical course code
    2  equivalent title at exactly equal credits, same basket
    3  equivalent title where the new PRC splits theory and lab
       (old credits == theory + lab credits)
    4  equivalent title where the new course carries fewer credits; the
       shortfall is closed by an additional course (Table IV)
    5  same basket and equal credits (choice-based baskets such as MAC/PEC/OEC)
Anything still unmatched is reported, never silently dropped.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from . import prc

STOP = {'and', 'of', 'using', 'use', 'for', 'the', 'in', 'to', 'a', 'an',
        'with', 'on', '&', 'as', 'by', 'its', 'other', 'related', 'part'}

# Concept-level synonyms. The PRC renames the same subject between batches far
# more often than it reuses a code, and fuzzy string matching alone gets these
# wrong, so the academic vocabulary is made explicit here.
ALIAS = [
    {'calculus', 'linear', 'algebra', 'differential', 'equations'},
    {'probability', 'statistics', 'statistics', 'applied'},
    {'optoelectronics', 'quantum', 'optoelectronic', 'device', 'devices', 'physics'},
    {'engineering', 'graphics', 'engineering'},
    {'english', 'technical', 'communication'},
    {'python', 'computational', 'thinking'},
    {'digital', 'design'},
    {'design', 'thinking'},
    {'electrical', 'electronics', 'basic'},
    {'problem', 'solving', 'problem'},
    {'data', 'structures', 'structures', 'algorithms'},
    {'object', 'oriented', 'java', 'programming'},
    {'web', 'technologies', 'web'},
    {'operating', 'systems'},
    {'discrete', 'mathematics', 'mathematical'},
    {'computer', 'organization', 'architecture'},
    {'blockchain', 'foundations', 'foundations'},
    {'smart', 'contract', 'solidity'},
    {'distributed', 'ledger', 'technology'},
    {'cryptography', 'security'},
    {'environmental', 'studies', 'science'},
    {'advance', 'advanced', 'english'},
]
ALIAS = [set(g) for g in ALIAS]


def _expand(ts):
    """Add sibling concepts so renamed courses compare on meaning, not wording."""
    out = set(ts)
    for g in ALIAS:
        if ts & g:
            out |= (g - ts)
    return out


def tokens(name: str) -> set:
    t = re.findall(r'[a-z0-9]+', (name or '').lower())
    return {w for w in t if w not in STOP and len(w) > 2}


def name_sim(a: str, b: str) -> float:
    """Semantic similarity.

    Weighted heavily towards the alias-expanded concept overlap rather than raw
    string similarity: a short title like "Advanced English" otherwise scores
    higher against "Technical English" than the genuinely equivalent
    "English for Technical Communication" does.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    ea, eb = _expand(ta), _expand(tb)
    jac = len(ea & eb) / len(ea | eb)
    seq = SequenceMatcher(None, (a or '').lower(), (b or '').lower()).ratio()
    return 0.85 * jac + 0.15 * seq


def dept(code: str) -> str:
    m = re.match(r'([A-Z]{3,4})', str(code or '').upper())
    return m.group(1) if m else ''


class Course:
    """One row of the student's transcript, enriched with PRC data."""

    def __init__(self, batch, code, name=None, credits=None, grade=None,
                 semester=None, month_year=None, term=None, basket=None):
        self.batch = batch
        self.code = prc.norm(code)
        rec = prc.course(batch, self.code) or {}
        self.prc_name = rec.get('name') or ''
        self.name = name or self.prc_name
        self.L = rec.get('L')
        self.T = rec.get('T')
        self.P = rec.get('P')
        self.C = rec.get('C') if credits is None else credits
        self.credits = int(self.C) if isinstance(self.C, (int, float)) else 0
        self.grade = grade
        self.semester = int(semester) if str(semester or '').strip().isdigit() else None
        self.month_year = month_year or ''
        self.term = (term or '').upper()
        self.prc_basket = rec.get('basket')
        self.basket = basket or self.prc_basket or prc.dept_basket(self.code)
        self.cycle = rec.get('cycles')[0] if rec.get('cycles') else ''
        self.known = bool(rec)
        self.passed = prc.is_passed(grade)

    def as_dict(self):
        return {'code': self.code, 'name': self.name, 'L': self.L, 'T': self.T,
                'P': self.P, 'C': self.C, 'credits': self.credits, 'grade': self.grade,
                'basket': self.basket, 'semester': self.semester,
                'month_year': self.month_year, 'term': self.term,
                'passed': self.passed, 'known': self.known}


# ------------------------------------------------------------------ scoring
def score(o: 'Course', nc: str, rec: dict, credit_equal: bool,
          new_batch: str | None = None, allow_credit_delta: bool = False) -> float:
    s = 0.0
    if o.code == nc:
        s += 5.0
    s += 3.0 * name_sim(o.name, rec.get('name') or '')
    same_dept = bool(dept(o.code)) and dept(o.code) == dept(nc)
    same_basket = o.basket and rec.get('basket') == o.basket
    if same_basket:
        s += 1.2
    elif same_dept:
        # the admission PRC sometimes files a subject under a different basket
        # than the readmitted PRC does; a same-department move is not suspicious
        s -= 1.0
    else:
        s -= 2.5
    if same_dept:
        s += 0.8
    # a course taken in semester 3 is normally equivalent to one the new PRC
    # still runs in semester 3 - this is what keeps renamed courses from
    # swapping over each other
    sem_cycle = rec.get('sem_cycle') or {}
    plain_sem = rec.get('sem')
    if o.semester and o.cycle and sem_cycle.get(o.cycle):
        s += 0.9 * (1.0 - abs(o.semester - int(sem_cycle[o.cycle])) / 8.0)
    elif o.semester and str(plain_sem).isdigit():
        s += 0.7 * (1.0 - abs(o.semester - int(plain_sem)) / 8.0)
    oc, nc_c = o.credits, rec.get('C') or 0
    if allow_credit_delta:
        pass                                    # theory+lab cases differ by design
    elif credit_equal:
        if oc != nc_c:
            s -= 3.0
    else:
        s -= 0.7 * max(0, nc_c - oc)
        s -= 0.9 * max(0, oc - nc_c)
    return s


def _sem(rec):
    s = str(rec.get('sem') or '')
    return int(s) if s.isdigit() else 9


def cycles_of(batch, code):
    rec = prc.course(batch, code) or {}
    return rec.get('cycles') or []


def sem_cycle_of(batch, code):
    rec = prc.course(batch, code) or {}
    return rec.get('sem_cycle') or {}


def build_mapping(old_batch: str, new_batch: str, transcript: list,
                  last_completed_sem: int | None = None,
                  lock: dict | None = None,
                  use_llm: bool = True) -> dict:
    lock = {prc.norm(k): prc.norm(v) for k, v in (lock or {}).items()}
    new_courses = prc.courses(new_batch)
    old_courses = prc.courses(old_batch)

    # Passed courses are matched even when their code is absent from the
    # admission PRC (a re-issued PRC or a revised syllabus); the transcript's
    # own name and credits are then used instead.
    passed = [c for c in transcript if c.passed]
    failed = [c for c in transcript if not c.passed]
    unknown = [c for c in passed if not c.known]

    used, pairs = set(), []
    order = lambda c: (c.semester or 9, c.code)          # noqa: E731

    def emit(o, codes, method, conf):
        pairs.append({'old': o, 'new_codes': list(codes), 'method': method,
                      'confidence': round(float(conf), 3),
                      'new_C': sum(new_courses[x].get('C') or 0 for x in codes),
                      'old_C': o.credits,
                      'shortfall': max(0, o.credits -
                                       sum(new_courses[x].get('C') or 0
                                           for x in codes))})
        used.update(codes)

    def done(o):
        return any(p['old'] is o for p in pairs)

    # ---- 0  manual overrides -------------------------------------------
    for o in sorted(passed, key=order):
        want = lock.get(o.code, '')
        if want and want in new_courses and want not in used:
            emit(o, [want], 'manual (HoD)', 1.0)

    # ---- 1  identical code and identical credits -----------------------
    for o in sorted([c for c in passed if not done(c)], key=order):
        rec = new_courses.get(o.code)
        if rec and o.code not in used and (rec.get('C') or 0) == o.credits:
            emit(o, [o.code], 'same course code', 1.0)

    def rank(o, eq):
        return sorted(((nc, rec) for nc, rec in new_courses.items()
                       if nc not in used),
                      key=lambda x: -score(o, x[0], x[1], eq, new_batch))

    # ---- 2  equivalent title, equal credits ----------------------------
    for o in sorted([c for c in passed if not done(c)], key=order):
        for nc, rec in rank(o, True):
            if (rec.get('C') or 0) != o.credits:
                continue
            if rec.get('basket') != o.basket and dept(o.code) != dept(nc):
                continue
            sim = name_sim(o.name, rec.get('name') or '')
            if sim < 0.34:                     # titles must genuinely resemble
                continue
            s = score(o, nc, rec, True, new_batch)
            if s >= 2.6:
                emit(o, [nc], 'equivalent title, equal credits', min(1.0, s / 6.0))
                break

    # ---- 3  old course == theory + lab pair of the new PRC -------------
    for o in sorted([c for c in passed if not done(c)], key=order):
        if not o.credits:
            continue
        for nc, rec in rank(o, True):
            sim = name_sim(o.name, rec.get('name') or '')
            if score(o, nc, rec, True, new_batch, allow_credit_delta=True) < 2.6 \
                    or (rec.get('basket') != o.basket and dept(o.code) != dept(nc)) \
                    or sim < 0.3:
                continue
            base = rec.get('C') or 0
            if base > o.credits:
                continue
            if base == o.credits:
                emit(o, [nc], 'equivalent title, equal credits', 0.9)
                break
            rest = o.credits - base
            partner = None
            for nc2, rec2 in new_courses.items():
                if nc2 in used or nc2 == nc or (rec2.get('C') or 0) != rest:
                    continue
                if rec2.get('basket') != o.basket:
                    continue
                if name_sim(o.name, rec2.get('name') or '') < 0.15:
                    continue
                partner = nc2
                break
            if partner:
                emit(o, [nc, partner], 'theory + lab pair of the new PRC', 0.8)
                break

    # ---- 4  equivalent title, new course carries fewer credits ---------
    # The admission PRC sometimes files a programming course under ESC while
    # the readmitted PRC files it under PCC, so a very strong title match in
    # the same department is allowed to cross baskets.
    for cross in (False, True):
        min_sim = 0.6 if cross else 0.34
        for o in sorted([c for c in passed if not done(c)], key=order):
            if not o.credits:
                continue
            for nc, rec in rank(o, False):
                c = rec.get('C') or 0
                if c == 0 or c >= o.credits:
                    continue
                if rec.get('basket') != o.basket:
                    if not (cross and dept(o.code) == dept(nc)):
                        continue
                if name_sim(o.name, rec.get('name') or '') < min_sim:
                    continue
                s = score(o, nc, rec, False, new_batch)
                if s >= (2.2 if cross else 2.6):
                    emit(o, [nc], 'equivalent title (partial credits)', min(0.85, s / 6.0))
                    break

    # ---- 5  same department / same basket, equal credits ----------------
    CB = {'MAC', 'PEC', 'OEC'}          # choice-based baskets carry no fixed title
    for o in sorted([c for c in passed if not done(c)], key=order):
        pool = [(nc, rec) for nc, rec in new_courses.items()
                if nc not in used and (rec.get('C') or 0) == o.credits
                and rec.get('basket') == o.basket]
        if not pool:
            continue
        sims = {nc: name_sim(o.name, rec.get('name') or '') for nc, rec in pool}
        pool = [(nc, rec) for nc, rec in pool
                if sims[nc] >= 0.2 or o.basket in CB
                or dept(o.code) == dept(nc)]
        if not pool:
            pool = [(nc, rec) for nc, rec in new_courses.items()
                    if nc not in used and (rec.get('C') or 0) == o.credits
                    and rec.get('basket') == o.basket]
            pool = pool[:1]
        pool.sort(key=lambda x: (0 if dept(o.code) == dept(x[0]) else 1,
                                 0 if x[1].get('basket') in CB else 1,
                                 -sims[x[0]], _sem(x[1]), x[0]))
        nc, rec = pool[0]
        emit(o, [nc], 'same department and basket, equal credits'
             + (' (choice-based)' if o.basket in CB else ''), 0.55)

    mapped_old = {p['old'].code for p in pairs}
    exemptions = [c for c in passed if c.code not in mapped_old]

    # ---- advisor pass -------------------------------------------------
    # Only genuinely ambiguous leftovers are offered to the model, and only the
    # credit-exact proposals it returns are accepted. Everything the rule engine
    # already decided is untouched.
    llm_decisions, llm_meta = {}, {'used_api': False, 'error': None}
    if use_llm and exemptions:
        try:
            from . import llm
            if llm.available():
                items = []
                for o in exemptions:
                    cands = llm.candidates_for(o, new_batch)
                    if not cands:
                        continue
                    items.append({'old_batch': old_batch, 'new_batch': new_batch,
                                  'old_code': o.code, 'old_name': o.name,
                                  'old_credits': o.credits, 'old_basket': o.basket,
                                  'old_sem': o.semester, 'candidates': cands})
                res = llm.advise(items)
                llm_decisions = res['decisions']
                llm_meta = {'used_api': res['used_api'], 'error': res['error'],
                            'offered': len(items)}
        except Exception as e:                                # noqa: BLE001
            llm_meta['error'] = 'advisor unavailable: %s' % e

    for o in exemptions:
        d = llm_decisions.get(o.code)
        if not d:
            continue
        codes = [c for c in d['new_codes'] if c in new_courses
                 and c not in used]
        if not codes:
            continue
        emit(o, codes, 'Grok advisor: %s' % (d.get('reason') or 'equivalence'),
             d.get('confidence', 0.5))
    exemptions = [c for c in passed if c.code not in
                  {p['old'].code for p in pairs}]

    # ---- Table IV: close the credit shortfalls, then cover gaps ---------
    last = last_completed_sem if last_completed_sem is not None else \
        max([o.semester or 0 for o in transcript] or [0])
    early = []
    seen = set()
    for sem in range(1, max(last, 0) + 1):
        for rec in prc.semester_courses(new_batch).get(sem, []):
            code = rec['code']
            if code in used or code in seen or (rec.get('C') or 0) <= 0:
                continue
            seen.add(code)
            early.append(dict(rec, sem=sem))
    early.sort(key=lambda r: (r['sem'], r['code']))

    additional = []
    for p in pairs:
        if p['shortfall'] <= 0:
            continue
        need = p['shortfall']
        pool = [r for r in early if r['code'] not in used
                and r['basket'] == p['old'].basket and (r['C'] or 0) <= need]
        if not pool:
            pool = [r for r in early if r['code'] not in used
                    and r['basket'] == p['old'].basket]
        pool.sort(key=lambda r: (_sem(r), r['code']))
        if pool:
            pick = pool[0]
            used.add(pick['code'])
            additional.append(pick)
            note = 'closes %s credit shortfall on %s' % (p['shortfall'], p['old'].code)
            additional[-1]['reason'] = note
    # any remaining new course the student has not yet reached stays visible
    for r in early:
        if r['code'] not in used:
            additional.append(dict(r, reason='not covered by the course mapping'))

    removal = [c for c in failed if c.code not in mapped_old
               and c.code not in lock] if lock else []

    return _assemble(old_batch, new_batch, pairs, failed, exemptions, additional,
                     removal, transcript, last, unknown, llm_meta)


# ------------------------------------------------------------------ assembly
def _assemble(old_batch, new_batch, pairs, failed, exemptions, additional,
              removal, transcript, last, unknown, llm_meta=None):
    nc_db, oc_db = prc.courses(new_batch), prc.courses(old_batch)
    used_new = {c for p in pairs for c in p['new_codes']}
    additional_set = {a['code'] for a in additional}

    groups = {}
    for p in pairs:
        groups.setdefault(p['old'].semester or 0, []).append(p)

    # new courses with no old counterpart are still shown (blank right column)
    gaps = {}
    for r in additional:
        gaps.setdefault(r['sem'], []).append(r)

    table1 = []
    for s in sorted(set(groups) | set(gaps)):
        rows = []
        for p in sorted(groups.get(s, []), key=lambda x: x['new_codes'][0]):
            for c in p['new_codes']:
                rows.append({'new': _cell(nc_db[c]), 'old': _old_cell(p['old']),
                             'method': p['method'], 'confidence': p['confidence'],
                             'shortfall': p['shortfall'] if c == p['new_codes'][-1] else 0})
        for r in gaps.get(s, []):
            rows.append({'new': _cell(nc_db[r['code']]), 'old': None,
                         'method': 'no equivalent in the old PRC', 'confidence': 1.0,
                         'shortfall': 0})
        if not rows:
            continue
        table1.append({'sem': s, 'rows': rows,
                       'new_credits': sum(r['new']['C'] or 0 for r in rows),
                       'old_credits': sum((r['old'] or {}).get('C') or 0 for r in rows)})

    b = sum(g['new_credits'] for g in table1)
    c_ = sum((oc_db.get(x.code, {}).get('C') or x.credits or 0) for x in failed)
    d = sum((oc_db.get(x.code, {}).get('C') or x.credits or 0) for x in exemptions)
    e_ = sum(r.get('C') or 0 for r in additional)
    a = prc.program(new_batch)['total_credits']
    f = max(0, a - b - c_ - d - e_)

    # ---- basket-wise position (Tables I + III) -------------------------
    mins = prc.basket_minimums(new_batch)
    done = {}
    for g in table1:
        for r in g['rows']:
            bk = r['new']['basket']
            done[bk] = done.get(bk, 0) + (r['new']['C'] or 0)
    for x in exemptions:
        rec = oc_db.get(x.code, {})
        bk = rec.get('basket') or x.basket
        done[bk] = done.get(bk, 0) + (rec.get('C') or x.credits or 0)

    labels = prc.basket_label(new_batch)
    labels.update(prc.load_db()['canonical_label'])
    legacy = {k: v for k, v in mins.items() if k.startswith('LEGACY_')}

    rows_b, tot_min, tot_done, tot_sur = [], 0, 0, 0
    for code in prc.load_db()['canonical_order']:
        mn = mins.get(code, 0)
        dc = done.get(code, 0)
        if legacy and mn == 0 and dc == 0:
            continue
        rows_b.append({'code': code, 'label': labels.get(code, code), 'min': mn,
                       'done': dc, 'left': max(0, mn - dc),
                       'surplus': max(0, dc - mn)})
        tot_min += mn
        tot_done += dc
        tot_sur += max(0, dc - mn)
    for k, v in legacy.items():
        rows_b.append({'code': 'LEGACY', 'label': k.replace('_', ' ').title(),
                       'min': v, 'done': 0, 'left': v, 'surplus': 0})
        tot_min += v
    rows_b.append({'code': 'TOTAL', 'label': 'Total Credits (Program)', 'min': tot_min,
                   'done': tot_done, 'left': max(0, tot_min - tot_done),
                   'surplus': tot_sur})

    # ---- credits earned beyond the basket minimum --------------------
    # Only courses the student has actually passed count: Table I rows that
    # carry an old counterpart, plus Table III exemptions. Table I rows with a
    # blank right-hand side are courses the student still has to attend.
    earned = {}
    for g in table1:
        for row in g['rows']:
            if row['old'] is not None:
                bk = row['new']['basket']
                earned[bk] = earned.get(bk, 0) + (row['new']['C'] or 0)
    for x in exemptions:
        rec = oc_db.get(x.code, {})
        bk = rec.get('basket') or x.basket
        earned[bk] = earned.get(bk, 0) + (rec.get('C') or x.credits or 0)

    surplus = {}
    for bk in set(earned) | {k for k in mins if not k.startswith('LEGACY_')}:
        surplus[bk] = max(0, earned.get(bk, 0) - mins.get(bk, 0))
    total_surplus = sum(surplus.values())

    # ---- courses the student may drop in the semesters ahead ----------
    # Surplus credits in a basket discharge the requirement for a later course
    # in the same basket, which is how a readmitted student ends up skipping
    # a course. Walking forward keeps the suggestion in the order they meet it.
    skips = []
    pool = dict(surplus)
    for sem in range(last + 1, 9):
        for rec in prc.semester_courses(new_batch).get(sem, []):
            code, cr, bk = rec['code'], rec.get('C') or 0, rec.get('basket')
            if code in used_new or cr <= 0 or code in additional_set:
                continue
            if pool.get(bk, 0) >= cr:
                pool[bk] -= cr
                skips.append({'code': code, 'name': rec.get('name'),
                              'L': rec.get('L'), 'T': rec.get('T'),
                              'P': rec.get('P'), 'C': cr, 'basket': bk,
                              'sem': sem,
                              'reason': 'absorbs %s surplus %s credit(s) already '
                                        'earned' % (cr, bk)})
    # Surplus that no later course in the same basket can absorb is stranded:
    # basket minima are strict, so it cannot be spent elsewhere.
    stranded = {bk: pool[bk] for bk in pool if pool[bk] > 0}

    return {
        'old_batch': old_batch, 'new_batch': new_batch,
        'program': prc.program(new_batch)['program'],
        'school': prc.program(new_batch)['school'],
        'last_completed_sem': last,
        'table1': table1,
        'table2': [{'course': x.as_dict(),
                    'credits': oc_db.get(x.code, {}).get('C') or x.credits or 0}
                   for x in failed],
        'table2_total': c_,
        'table3': [{'old': x.as_dict(),
                    'credits': oc_db.get(x.code, {}).get('C') or x.credits or 0,
                    'sem': x.semester, 'basket': x.basket} for x in exemptions],
        'table3_total': d,
        'table4': additional, 'table4_total': e_,
        'table5': [{'course': x.as_dict(),
                    'credits': oc_db.get(x.code, {}).get('C') or x.credits or 0}
                   for x in removal],
        'table5_total': sum(oc_db.get(x.code, {}).get('C') or x.credits or 0
                            for x in removal),
        'surplus_by_basket': {k: v for k, v in surplus.items() if v},
        'surplus_total': total_surplus,
        'surplus_stranded': stranded,
        'surplus_stranded_total': sum(stranded.values()),
        'skippable': skips,
        'skippable_total': sum(s['C'] for s in skips),
        'unknown_courses': [{'course': x.as_dict()} for x in unknown],
        'baskets': rows_b,
        'summary': [
            ('A.', 'Minimum Number of credits to be earned as per the New '
                   '(Readmitted) PRC for the award of the Degree', a),
            ('B.', 'The number of credits was earned as per the New (Readmitted) PRC '
                   'based on course mapping (Table I)', b),
            ('C.', 'The number of credits is to be completed because of F/NP grades. '
                   '(Table II)', c_),
            ('D.', 'The number of credits is exempted (Table III)', d),
            ('E.', 'The number of credits is to be earned through additional courses '
                   '(Table IV)', e_),
            ('F.', 'The number of remaining credits is to be earned in the new PRC, '
                   'from the time of readmission (excluding the number of exempted '
                   'credits as in Table III)', f),
        ],
        'summary_total': b + c_ + d + e_ + f,
        'credits_required': a,
        # A readmitted student may legitimately hold more credits than the PRC
        # requires. That surplus is not a defect: it discharges the requirement
        # for a later course in the same basket, which is how the student ends
        # up skipping one. Both figures are reported rather than clamped away.
        'excess_over_requirement': max(0, (b + d) - a),
        'llm': llm_meta,
        'pairs': [{'old': p['old'].as_dict(), 'new_codes': p['new_codes'],
                   'new': [_cell(nc_db[x]) for x in p['new_codes']],
                   'method': p['method'], 'confidence': p['confidence'],
                   'shortfall': p['shortfall']} for p in pairs],
    }


def _cell(rec):
    return {'code': rec['code'], 'name': rec.get('name') or '',
            'L': rec.get('L'), 'T': rec.get('T'), 'P': rec.get('P'),
            'C': rec.get('C'), 'basket': rec.get('basket'), 'sem': rec.get('sem')}


def _old_cell(c):
    rec = prc.courses(c.batch).get(c.code, {})
    return {'code': c.code, 'name': c.name, 'L': rec.get('L'), 'T': rec.get('T'),
            'P': rec.get('P'), 'C': rec.get('C'), 'basket': rec.get('basket'),
            'sem': c.semester, 'grade': c.grade, 'month_year': c.month_year,
            'term': c.term}
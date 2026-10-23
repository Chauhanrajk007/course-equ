"""End-to-end test of the Grok advisor on genuinely ambiguous electives.

Builds a student who took three free-choice electives in the old batch that have
no keyword relationship to anything in the new PRC - exactly the case the rule
engine cannot solve and the advisor exists for.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import llm, prc                                  # noqa: E402
from engine.mapping import Course, build_mapping, name_sim    # noqa: E402

OLD, NEW = '2024-2028', '2025-2029'

# electives the student chose, and what they would plausibly be equivalent to
AMBIGUOUS = ['CBC3401', 'CBC3403', 'CBC3405']


def main():
    print('provider:', llm.status())
    if not llm.available():
        print('no key configured - skipping')
        return 0

    db = prc.courses(OLD)
    print('\nOld-batch electives the student passed:')
    for c in AMBIGUOUS:
        r = db.get(c)
        print('   %-9s %-45s %scr %s'
              % (c, (r or {}).get('name', '?'), (r or {}).get('C'),
                 (r or {}).get('basket')))

    courses = [Course(OLD, c, None, None, 'B+', 5, 'June 2025', '')
               for c in AMBIGUOUS]
    for c in courses:
        best = max(prc.courses(NEW).items(),
                   key=lambda kv: name_sim(c.name, kv[1].get('name') or ''))
        print('   rule engine would have guessed %s (%s, sim %.2f)'
              % (best[0], best[1].get('name'), name_sim(c.name,
                                                          best[1].get('name'))))

    items = []
    for c in courses:
        cands = llm.candidates_for(c, NEW)
        items.append({'old_batch': OLD, 'new_batch': NEW, 'old_code': c.code,
                      'old_name': c.name, 'old_credits': c.credits,
                      'old_basket': c.basket, 'old_sem': c.semester,
                      'candidates': cands})
    print('\ncalling advisor with %d courses, %d candidates each'
          % (len(items), len(items[0]['candidates'])))

    res = llm.advise(items, use_cache=False)
    print('used_api = %s   error = %s' % (res['used_api'], res['error']))
    print('\ndecisions:')
    for code, d in res['decisions'].items():
        names = [next((x['name'] for x in items[0]['candidates']
                       if x['code'] == p), p) for p in d['new_codes']]
        print('   %-9s -> %s' % (code, ', '.join(d['new_codes']) or '(exempt)'))
        for p, n in zip(d['new_codes'], names):
            print('               %s' % n)
        print('               confidence %.2f   %s'
              % (d['confidence'], d['reason']))
    if not res['decisions']:
        print('   (none)')
        return 1

    print('\nfull mapping with the advisor on:')
    # a realistic transcript: every course of the old PRC up to semester 5,
    # with the three free-choice electives swapped in
    db_old = prc.courses(OLD)
    full = [Course(OLD, c, None, None, 'B+', int(v['sem']), '', '')
            for c, v in sorted(db_old.items())
            if str(v.get('sem') or '').isdigit() and int(v['sem']) <= 5
            and (v.get('C') or 0) > 0 and c not in AMBIGUOUS]
    full += courses
    r = build_mapping(OLD, NEW, full, last_completed_sem=5, use_llm=True)
    print('   mapped %d courses, exemptions: %s'
          % (len(r['pairs']), [e['old']['code'] for e in r['table3']] or 'none'))
    for p in r['pairs']:
        if p['old']['code'] in AMBIGUOUS:
            print('   %-9s %-42s -> %s   [%s]'
                  % (p['old']['code'], (p['old']['name'] or '')[:42],
                     ' + '.join(p['new_codes']), p['method']))
    print('   surplus %s  skippable %d courses'
          % (r['surplus_by_basket'] or 'none', len(r['skippable'])))
    print('   reconciles: B=%s C=%s D=%s E=%s F=%s  total=%s / %s'
          % (r['summary'][1][2], r['summary'][2][2], r['summary'][3][2],
             r['summary'][4][2], r['summary'][5][2], r['summary_total'],
             r['credits_required']))
    good = r['summary_total'] >= r['credits_required']
    print('   %s' % ('OK' if good else 'DOES NOT RECONCILE'))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
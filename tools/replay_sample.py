"""Replays the siddarth123 expected outcome (2024 -> 2025 readmission)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import prc                                    # noqa: E402
from engine.mapping import Course, build_mapping          # noqa: E402

OLD, NEW = '2024-2028', '2025-2029'

# transcript exactly as printed in siddarth123.docx (old / 2024 batch side)
TR = [
    # semester 1
    ('MAT1001', 'Calculus and Linear Algebra', 4, 'D', 1, 'April 2025', 'ET'),
    ('PHY1002', 'Optoelectronics and Device Physics', 3, 'B+', 1, 'Jan 2025', ''),
    ('MEC1006', 'Engineering Graphics', 2, 'C', 1, 'Jan 2025', ''),
    ('ENG1002', 'Technical English', 2, 'D', 1, 'Jan 2025', ''),
    ('CSE1500', 'Computational Thinking Using Python', 3, 'D', 2, 'Jan 2025', ''),
    ('ECE2007', 'Digital Design', 3, 'B', 1, 'Dec 2025', 'ET'),
    ('DES1146', 'Introduction to Design Thinking', 1, 'A', 1, 'Jan 2025', ''),
    ('PPS1001', 'Introduction to Soft Skills', 1, 'D', 1, '2025', 'ET'),
    # semester 2
    ('MAT1003', 'Applied Statistics', 2, 'F', 2, 'June 2025', 'ET'),
    ('CHE1018', 'Environmental Science', 0, 'S', 2, 'June 2025', ''),
    ('CHE2501', 'Chemistry of Smart Materials', 3, 'D', 2, 'June 2026', ''),
    ('CHE2502', 'Chemistry of Smart Materials Lab', 1, 'C', 2, 'June 2026', ''),
    ('CIV1008', 'Basic Engineering Sciences', 2, 'D', 2, 'June 2025', ''),
    ('CSE1004', 'Problem Solving using C', 3, 'C', 2, 'July 2025', ''),
    ('ENG2001', 'Advanced English', 2, 'D', 2, 'June 2025', 'ET'),
    ('EEE1007', 'Basics of Electrical and Electronics Engineering', 4, 'D', 2, 'June 2025', ''),
    ('PPS1012', 'Enhancing Personality Through Soft Skills', 1, 'O', 2, '2025', 'ST'),
    ('CIV7601', 'Universal Human Values and Ethics', 0, 'S', 2, '2025', 'ET'),
    ('ECE2010', 'Innovative Projects using Arduino', 1, 'A+', 2, 'July 2025', 'ET'),
    ('CSS2255', 'Object Oriented Programming using Java', 3, 'C', 2, '2025', 'ET'),
    # failure recorded separately in Table II
    ('LAW1007', 'Indian Constitution and Professional Ethics', 0, 'NP', 1, '2025', ''),
]

courses = [Course(OLD, c, n, cr, g, s, my, t) for c, n, cr, g, s, my, t in TR]
res = build_mapping(OLD, NEW, courses, last_completed_sem=2)

print('=' * 100)
print('TABLE I  (new PRC 2025-2029  <->  old PRC 2024-2028)')
for g in res['table1']:
    print('  --- Semester %s ---  new=%s  old-earned=%s'
          % (g['sem'], g['new_credits'], g['old_credits']))
    for r in g['rows']:
        o = r['old'] or {}
        print('    %-9s %-42s %-4s -> %-9s %-42s %-4s  [%s]'
              % (r['new']['code'], (r['new']['name'] or '')[:42], r['new']['C'],
                 o.get('code', ''), (o.get('name') or '')[:42], o.get('C', ''),
                 r['method']))

for key, title in [('table2', 'TABLE II  Failed / NP'),
                   ('table3', 'TABLE III Exemptions'),
                   ('table4', 'TABLE IV  Additional courses'),
                   ('table5', 'TABLE V   Remove from transcript')]:
    print('\n%s  -> total %s' % (title, res[key + '_total']))
    items = res[key]
    if key == 'table3':
        for it in items:
            print('    %-9s %-45s %s cr  sem%s'
                  % (it['old']['code'], it['old']['name'][:45], it['credits'], it['sem']))
    elif key == 'table4':
        for it in items:
            print('    %-9s %-45s %s cr  sem%s %s'
                  % (it['code'], (it['name'] or '')[:45], it['C'], it['sem'],
                     it['basket']))
    else:
        for it in items:
            c = it['course']
            print('    %-9s %-45s %s cr  grade=%s'
                  % (c['code'], c['name'][:45], it['credits'], c['grade']))

print('\nBASKET WISE')
for b in res['baskets']:
    print('    %-6s %-58s min=%-4s done=%-4s left=%s'
          % (b['code'], b['label'][:58], b['min'], b['done'], b['left']))

print('\nSUMMARY')
for idx, desc, val in res['summary']:
    print('    %-3s %-110s %s' % (idx, desc[:110], val))
print('    Total (B+C+D+E+F) =', res['summary_total'],
      '   OK' if res['summary_total'] >= res['credits_required'] else '   SHORT')

STUDENT = {'name': 'SIDDANA GOUDA', 'roll_no': '20241CIT0082',
           'program': 'B.TECH - CSE (Internet of Things)',
           'admission_batch': '2024', 'last_sem': '2',
           'readmission_batch': '2025', 'readmit_sem': '3',
           'school_name': 'Presidency School of Artificial Intelligence & '
                          'Advanced Computing'}

if __name__ == '__main__':
    import io
    from engine import report
    pdf = report.render(res, STUDENT)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'sample_output.pdf')
    with open(out, 'wb') as f:
        f.write(pdf)
    print('\nPDF written:', out, len(pdf), 'bytes')
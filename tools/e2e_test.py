"""End-to-end test: build a report card, drive the web app, fetch the PDF.

Also asserts the invariants the academic cell cares about:
  * credits always reconcile to the PRC total;
  * every mapped pairing balances old credits against new credits, except a
    declared partial match whose shortfall is carried into Table IV.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docx import Document                                    # noqa: E402
from docx.shared import Pt                                   # noqa: E402

from engine import prc                                       # noqa: E402
from engine.mapping import Course, build_mapping             # noqa: E402
from engine import report                                     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, 'tools', '_e2e')
os.makedirs(TMP, exist_ok=True)

OLD, NEW = '2024-2028', '2025-2029'
SEMS = {1: ['MAT1001', 'PHY1002', 'MEC1006', 'ENG1002', 'CSE1500', 'ECE2007',
            'DES1146', 'PPS1001'],
        2: ['MAT1003', 'CHE1018', 'CIV1008', 'CSE1004', 'ENG2001', 'EEE1007',
            'PPS1012', 'CIV7601', 'CSS2255', 'ECE2010'],
        3: ['MAT2303', 'CSS2253', 'CBC2000', 'LAW7601']}
GRADES = {'MAT1003': 'F', 'LAW7601': 'NP'}


def make_docx(path):
    db = prc.courses(OLD)
    d = Document()
    d.add_paragraph('PRESIDENCY UNIVERSITY').runs[0].font.size = Pt(14)
    d.add_paragraph('Statement of Marks - B.Tech Computer Science & Engineering')
    for label, val in [('Name of the Student', 'TEST STUDENT'),
                       ('Roll Number', '20241CIT0001'),
                       ('Program', 'B.Tech CSE (Block Chain)'),
                       ('Admission Batch and Last Semester attended',
                        '2024, 3rd Semester')]:
        d.add_paragraph('').add_run('%s: %s' % (label, val)).font.size = Pt(10)
    for sem, codes in SEMS.items():
        d.add_paragraph('SEMESTER %d' % sem).runs[0].font.size = Pt(12)
        t = d.add_table(rows=1, cols=5)
        t.style = 'Table Grid'
        for i, h in enumerate(['S.No', 'Course Code', 'Course Name',
                               'Credits', 'Grade']):
            t.rows[0].cells[i].text = h
        for i, code in enumerate(codes, 1):
            rec = db.get(code, {})
            t.add_row().cells[0].text = str(i)
            t.rows[i].cells[1].text = code
            t.rows[i].cells[2].text = (rec.get('name') or 'Course')[:44]
            t.rows[i].cells[3].text = str(rec.get('C') or '')
            t.rows[i].cells[4].text = GRADES.get(code, 'B+')
    d.save(path)
    return path


def main():
    from engine.transcript import parse_transcript, to_courses
    path = make_docx(os.path.join(TMP, 'report_card.docx'))
    parsed = parse_transcript('report_card.docx', open(path, 'rb').read())
    print('parsed %d course rows; identity = %s'
          % (len(parsed['records']),
             {k: v for k, v in parsed['identity'].items() if k in
              ('name', 'roll_no', 'program')}))

    courses = to_courses(parsed['records'], OLD)
    res = build_mapping(OLD, NEW, courses, last_completed_sem=3, use_llm=False)

    # ---------------- invariants ----------------
    ok = True
    if res['summary_total'] != res['credits_required']:
        print('FAIL summary %s != required %s'
              % (res['summary_total'], res['credits_required']))
        ok = False
    else:
        print('PASS  credits reconcile exactly: %d'
              % res['summary_total'])

    used = {}
    for p in res['pairs']:
        for c in p['new_codes']:
            assert c not in used, 'new course %s mapped twice' % c
            used[c] = p['old']['code']
    print('PASS  every new course is mapped at most once (%d mappings)'
          % len(used))

    t4 = {a['code'] for a in res['table4']}
    bad = [p for p in res['pairs']
           if p['shortfall'] > 0 and not (t4 & set(p['new_codes']))]
    print('%s  partial matches all carry an additional course (%d shortfall pairs)'
          % ('PASS ' if not bad else 'FAIL ', len(bad)))
    ok = ok and not bad

    for name, rows, key, tkey in [
            ('Table II', res['table2'], 'credits', 'table2_total'),
            ('Table III', res['table3'], 'credits', 'table3_total'),
            ('Table IV', res['table4'], 'C', 'table4_total'),
            ('Table V', res['table5'], 'credits', 'table5_total')]:
        tot = sum(r[key] or 0 for r in rows)
        good = tot == res[tkey]
        print('%s  %s rows sum to the stated total (%d)'
              % ('PASS ' if good else 'FAIL ', name, tot))
        ok = ok and good

    b1 = sum(g['new_credits'] for g in res['table1'])
    print('%s  Table I semester credits sum to B (%d)'
          % ('PASS ' if b1 == res['summary'][1][2] else 'FAIL ', b1))
    ok = ok and b1 == res['summary'][1][2]

    # ---------------- PDF ----------------
    student = {'name': 'TEST STUDENT', 'roll_no': '20241CIT0001',
               'program': 'B.Tech CSE (Block Chain)',
               'admission_batch': OLD, 'readmission_batch': NEW,
               'last_sem': '3', 'readmit_sem': '4',
               'school_name': prc.program(NEW)['school']}
    out = os.path.join(TMP, 'report.pdf')
    open(out, 'wb').write(report.render(res, student))
    print('PASS  PDF written: %s (%d bytes)' % (out, os.path.getsize(out)))

    # ---------------- all batch pairs ----------------
    print('\nBatch-pair smoke test:')
    bs = prc.batches()
    for i, a in enumerate(bs):
        for b in bs[i + 1:]:
            r = build_mapping(a, b, courses, last_completed_sem=3, use_llm=False)
            good = r['summary_total'] == r['credits_required']
            print('  %s -> %-9s B=%-3s D=%-3s E=%-3s  %s'
                  % (a, b, r['summary'][1][2], r['summary'][3][2],
                     r['summary'][4][2], 'ok' if good else 'MISMATCH'))
            ok = ok and good

    print('\n%s' % ('ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
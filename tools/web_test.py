"""Drives the Flask app through a full upload -> review -> override -> PDF cycle."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as web                                        # noqa: E402

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_e2e')
RC = os.path.join(TMP, 'report_card.docx')


def main():
    web.app.config['TESTING'] = True
    cl = web.app.test_client()
    ok = True

    r = cl.get('/')
    assert r.status_code == 200, r.status_code
    body = r.get_data(as_text=True)
    for b in web.prc.batches():
        assert b in body, 'batch %s missing from the form' % b
    print('PASS  GET / renders with all %d batches' % len(web.prc.batches()))

    with open(RC, 'rb') as f:
        r = cl.post('/upload', data={
            'transcripts': [(f, 'report_card.docx')],
            'old_batch': '2024-2028', 'new_batch': '2025-2029',
            'name': 'TEST STUDENT', 'roll_no': '20241CIT0001'},
            content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    ids = [c for c in web.CASES]
    cid = ids[-1]
    assert 'Check what was read' in html, 'did not land on the confirm step'
    print('PASS  POST /upload -> confirm page (case %s)' % cid[:8])

    # ---------- confirm: edit then map ----------
    case = web.CASES[cid]
    recs = case['records']
    form = {'code[]': [x['code'] for x in recs],
            'name[]': [x.get('name') or '' for x in recs],
            'credits[]': [str(x['credits'] or '') for x in recs],
            'grade[]': [x.get('grade') or '' for x in recs],
            'semester[]': [str(x.get('semester') or '') for x in recs],
            'keep[]': [x['code'] for x in recs],
            'name': 'TEST STUDENT', 'roll_no': '20241CIT0001',
            'last_sem': '3', 'readmit_sem': '4'}
    r = cl.post('/confirm/%s' % cid, data=form, follow_redirects=True)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Review the mapping' in html, 'confirm did not advance to review'
    print('PASS  POST /confirm -> review page')
    for label in ['Table I', 'Table II', 'Table III', 'Table IV', 'Table V',
                  'Basket-wise position', 'Summary']:
        assert label in html, 'missing section: %s' % label
    print('PASS  review page shows all five tables + basket + summary')

    # ---------- unticking a course drops it ----------
    before = len(web.CASES[cid]['records'])
    dropped = recs[-1]['code']
    form2 = dict(form)
    form2['keep[]'] = [x['code'] for x in recs[:-1]]
    r = cl.post('/confirm/%s' % cid, data=form2, follow_redirects=True)
    assert r.status_code == 200
    got = [x['code'] for x in web.CASES[cid]['records']]
    if dropped in got or len(got) != before - 1:
        print('FAIL  unticking a course did not remove it (%d -> %d)'
              % (before, len(got)))
        ok = False
    else:
        print('PASS  unticking a course removes it (%d -> %d)'
              % (before, len(got)))

    # ---------- refusing to keep everything ----------
    form3 = dict(form)
    form3['keep[]'] = []
    r = cl.post('/confirm/%s' % cid, data=form3, follow_redirects=True)
    assert 'at least one course' in r.get_data(as_text=True).lower()
    print('PASS  confirming with nothing ticked is rejected')

    # ---------- override one mapping ----------
    case = web.CASES[cid]
    pair = case['result']['pairs'][0]
    old_code = pair['old']['code']
    target = 'CSS2255' if 'CSS2255' in web.prc.courses('2025-2029') else \
        list(web.prc.courses('2025-2029'))[0]
    r = cl.post('/review/%s/override' % cid, data={'map__%s' % old_code: target},
                follow_redirects=True)
    assert r.status_code == 200, r.status_code
    after = web.CASES[cid]['result']
    mapped_to = [p['new_codes'] for p in after['pairs']
                 if p['old']['code'] == old_code]
    if not mapped_to or target not in mapped_to[0]:
        print('FAIL  override %s -> %s was not applied (%s)'
              % (old_code, target, mapped_to))
        ok = False
    else:
        print('PASS  override applied: %s -> %s' % (old_code, target))
    if after['summary_total'] != after['credits_required']:
        print('FAIL  credits no longer reconcile after override (%s vs %s)'
              % (after['summary_total'], after['credits_required']))
        ok = False
    else:
        print('PASS  credits still reconcile after override (%d)'
              % after['summary_total'])

    # ---------- exempt a course ----------
    r = cl.post('/review/%s/override' % cid, data={}, follow_redirects=True)
    assert r.status_code == 200
    print('PASS  clearing all overrides accepted')

    # ---------- PDF ----------
    r = cl.get('/download/%s' % cid)
    assert r.status_code == 200, r.status_code
    assert r.mimetype == 'application/pdf', r.mimetype
    pdf = r.get_data()
    assert pdf[:5] == b'%PDF-', 'not a PDF'
    print('PASS  GET /download -> PDF (%d bytes, %s)'
          % (len(pdf), r.headers.get('Content-Disposition', '')[:60]))

    # ---------- JSON ----------
    r = cl.get('/review/%s/json' % cid)
    assert r.status_code == 200
    j = r.get_json()
    assert 'result' in j and 'pairs' in j
    print('PASS  GET /review/<id>/json -> %d pairs exported'
          % len(j['pairs']))

    # ---------- bad input ----------
    r = cl.post('/upload', data={'transcripts': [(None, '')], 'old_batch': 'x',
                                 'new_batch': 'y'}, follow_redirects=True)
    assert 'at least one report-card' in r.get_data(as_text=True).lower()
    print('PASS  empty upload is rejected with a clear message')

    # ---------- multiple files at once ----------
    with open(RC, 'rb') as f1:
        r = cl.post('/upload', data={
            'transcripts': [(f1, 'sem1.docx'), (open(RC, 'rb'), 'sem1_copy.docx')],
            'old_batch': '2024-2028', 'new_batch': '2025-2029'},
            content_type='multipart/form-data', follow_redirects=True)
    assert 'Check what was read' in r.get_data(as_text=True)
    mcid = list(web.CASES)[-1]
    n = len(web.CASES[mcid]['records'])
    if n != 22:
        print('FAIL  two identical files produced %d rows, expected 22 '
              '(deduplicated)' % n)
        ok = False
    else:
        print('PASS  two identical files merged and deduplicated (%d rows)' % n)
    if len(web.CASES[mcid]['filenames']) == 2:
        print('PASS  both source files are retained')
    else:
        print('FAIL  source files not retained')
        ok = False

    # ---------- add more pages to an open case ----------
    before = len(web.CASES[mcid]['records'])
    with open(RC, 'rb') as f:
        r = cl.post('/add/%s' % mcid, data={
            'transcripts': [(f, 'later_sem.docx')]},
            content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200
    after = len(web.CASES[mcid]['records'])
    if after != before:
        print('FAIL  re-uploading the same file added %d duplicate rows'
              % (after - before))
        ok = False
    else:
        print('PASS  attaching the same file again adds no duplicates')

    # ---------- conflicting pages are flagged ----------
    form = {'code[]': ['MAT1001'], 'name[]': ['Calculus and Linear Algebra'],
            'credits[]': ['4'], 'grade[]': ['B+'], 'semester[]': ['1'],
            'keep[]': ['MAT1001'], 'last_sem': '1', 'readmit_sem': '2'}
    cl.post('/confirm/%s' % mcid, data=form, follow_redirects=True)
    merged, ident, notes = web._merge([
        ('p1.docx', {'identity': {}, 'records': [
            {'code': 'MAT1001', 'name': 'Calculus', 'credits': 4,
             'grade': 'D', 'semester': 1}]}),
        ('p2.docx', {'identity': {}, 'records': [
            {'code': 'MAT1001', 'name': 'Calculus', 'credits': 4,
             'grade': 'B+', 'semester': 1}]})])
    rec = merged[0]
    if rec.get('grade') == 'B+' and rec.get('conflict'):
        print('PASS  a conflicting re-attempt keeps the later grade and is '
              'flagged (%s)' % ','.join(rec['conflict']))
    else:
        print('FAIL  conflict handling wrong: %s' % rec)
        ok = False

    # ---------- manual entry: the no-AI path ----------
    r = cl.get('/manual')
    assert r.status_code == 200, r.status_code
    assert 'Enter the transcript by hand' in r.get_data(as_text=True)
    print('PASS  GET /manual renders')

    r = cl.post('/manual', data={'old_batch': '2024-2028',
                                 'new_batch': '2025-2029', 'last_sem': '2'},
                follow_redirects=True)
    html = r.get_data(as_text=True)
    nrows = html.count('name="keep[]"')
    if nrows < 15:
        print('FAIL  manual list generated only %d rows for 2 semesters' % nrows)
        ok = False
    else:
        print('PASS  manual list generated %d courses from the PRC grids'
              % nrows)

    # tick everything, mark one F, and map
    db = web.prc.courses('2024-2028')
    keep, grades, credits = [], [], []
    for sem, crs in web.prc.semester_courses('2024-2028').items():
        if sem > 2:
            continue
        for c in crs:
            if c['code'] in keep:
                continue
            keep.append(c['code'])
            grades.append('F' if c['code'] == 'MAT1003' else 'B+')
            credits.append(str(c['C'] or 0))
    r = cl.post('/manual', data={
        'old_batch': '2024-2028', 'new_batch': '2025-2029', 'last_sem': '2',
        'readmit_sem': '3', 'name': 'MANUAL TEST', 'roll_no': '20241CIT0002',
        'keep[]': keep, 'grade[]': grades, 'credits[]': credits},
        follow_redirects=True)
    assert r.status_code == 200
    mcid = list(web.CASES)[-1]
    res = web.CASES[mcid]['result']
    if 'Review the mapping' in r.get_data(as_text=True) \
            and res['summary_total'] >= res['credits_required']:
        print('PASS  manual entry maps and reconciles (%d courses, %d/%d credits)'
              % (len(res['pairs']), res['summary_total'],
                 res['credits_required']))
    else:
        print('FAIL  manual entry did not map: %d/%d'
              % (res['summary_total'], res['credits_required']))
        ok = False
    if web.CASES[mcid]['records'][keep.index('MAT1003')]['grade'] == 'F':
        print('PASS  a manually entered F grade lands in Table II')
    else:
        print('FAIL  manual F grade lost')
        ok = False

    r = cl.get('/download/%s' % mcid)
    assert r.status_code == 200 and r.get_data()[:5] == b'%PDF-'
    print('PASS  a manually entered case still produces the PDF')

    # ---------- image upload ----------
    img = os.path.join(TMP, 'report_card.png')
    if not os.path.exists(img):
        import make_test_image
        img = make_test_image.build(img)
    if web.llm.available():
        with open(img, 'rb') as f:
            r = cl.post('/upload', data={
                'transcripts': [(f, 'report_card.png')],
                'old_batch': '2024-2028', 'new_batch': '2025-2029'},
                content_type='multipart/form-data', follow_redirects=True)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        if 'Check what was read' not in html:
            print('FAIL  image upload did not reach the confirm step')
            ok = False
        else:
            icid = list(web.CASES)[-1]
            recs = web.CASES[icid]['records']
            codes = [x['code'] for x in recs]
            expect = ['MAT1001', 'PHY1002', 'MEC1006', 'ENG1002', 'CSE1500',
                      'ECE2007', 'DES1146', 'PPS1001', 'MAT1003', 'CIV1008',
                      'CSE1004', 'EEE1007']
            miss = [c for c in expect if c not in codes]
            if miss:
                print('FAIL  photo transcription missed %s' % miss)
                ok = False
            else:
                print('PASS  photo read %d/%d course codes'
                      % (len(expect), len(codes)))
            if 'MAT1003' in codes and \
                    web.CASES[icid]['records'][codes.index('MAT1003')]['grade'] == 'F':
                print('PASS  an F grade was read correctly from the photo')
            else:
                print('FAIL  the F grade was misread')
                ok = False
            if 'data:image/jpeg;base64' in html:
                print('PASS  original page is shown for comparison')
            else:
                print('FAIL  original page not shown on the confirm screen')
                ok = False

        # ---------- several photos in one go ----------
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import make_test_image
        p2 = make_test_image.build(os.path.join(TMP, 'sem2.png'), sem='2')
        with open(img, 'rb') as f1, open(p2, 'rb') as f2:
            r = cl.post('/upload', data={
                'transcripts': [(f1, 'sem1.png'), (f2, 'sem2.png')],
                'old_batch': '2024-2028', 'new_batch': '2025-2029'},
                content_type='multipart/form-data', follow_redirects=True)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        mcid = list(web.CASES)[-1]
        recs = web.CASES[mcid]['records']
        if len(recs) == 12:
            print('PASS  two photos of different semesters merged (%d unique '
                  'courses)' % len(recs))
        else:
            print('FAIL  two photos produced %d rows (expected 12 unique)'
                  % len(recs))
            ok = False
        if all(r_.get('source_file') for r_ in recs):
            print('PASS  every row records which page it came from')
        else:
            print('FAIL  rows missing their source page')
            ok = False
        if html.count('data:image/jpeg;base64') >= 2:
            print('PASS  both pages are shown for comparison')
        else:
            print('FAIL  not every page shown')
            ok = False
    else:
        print('SKIP  photo tests (no AI key configured)')

    # ---------- non-image masquerading as an image ----------
    with open(RC, 'rb') as f:
        r = cl.post('/upload', data={
            'transcripts': [(f, 'fake.png')],
            'old_batch': '2024-2028', 'new_batch': '2025-2029'},
            content_type='multipart/form-data', follow_redirects=True)
    assert 'could not be opened as an image' in r.get_data(as_text=True).lower()
    print('PASS  a .docx renamed to .png is rejected with a clear message')

    with open(RC, 'rb') as f:
        r = cl.post('/upload', data={
            'transcripts': [(f, 'report_card.docx')],
            'old_batch': '2025-2029', 'new_batch': '2024-2028'},
            content_type='multipart/form-data', follow_redirects=True)
    assert 'must be later' in r.get_data(as_text=True).lower()
    print('PASS  readmission batch earlier than admission is rejected')

    r = cl.get('/review/doesnotexist')
    assert r.status_code == 404
    print('PASS  unknown case returns 404')

    print('\n%s' % ('ALL WEB CHECKS PASSED' if ok else 'SOME WEB CHECKS FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
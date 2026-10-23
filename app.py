"""Course Equivalence & Credit Mapping - Flask application."""
from __future__ import annotations

import io
import os
import secrets
import time
import uuid
from datetime import timedelta

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)

from engine import llm, ocr, prc, report
from engine.mapping import Course, build_mapping
from engine.transcript import ParseError, parse_transcript, to_courses

BASE = os.path.dirname(os.path.abspath(__file__))
MAX_UPLOAD = 60 * 1024 * 1024          # room for a whole transcript's pages
MAX_FILES = 24
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=6)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# In-memory working set. Swap for a database if this ever runs multi-worker.
CASES: dict[str, dict] = {}

STUDENT_FIELDS = ('name', 'roll_no', 'program', 'previous_institution',
                  'school_name', 'last_sem', 'readmit_sem')


# ---------------------------------------------------------------- helpers
def _batches_for_ui() -> list[dict]:
    out = []
    for b in prc.batches():
        p = prc.program(b)
        out.append({'batch': b, 'label': '%s  (%s)' % (b, p['program'][:52]),
                    'legacy': p.get('legacy_baskets', False)})
    return out


def _case(cid: str) -> dict:
    c = CASES.get(cid)
    if not c:
        abort(404, 'This case has expired. Please upload the report card again.')
    return c


def _recompute(c: dict) -> dict:
    c['result'] = build_mapping(
        c['old_batch'], c['new_batch'], c['courses'],
        last_completed_sem=c.get('last_sem') or None,
        lock=c.get('lock'), use_llm=c.get('use_llm', True))
    return c['result']


def _new_courses(c: dict) -> list[dict]:
    """Everything the review screen needs to offer as an override target."""
    rows = []
    for code, rec in sorted(prc.courses(c['new_batch']).items()):
        rows.append({'code': code, 'name': rec.get('name') or '',
                     'C': rec.get('C'), 'basket': rec.get('basket'),
                     'sem': rec.get('sem'), 'dept': code[:3]})
    return rows


# ------------------------------------------------------------------ routes
@app.route('/')
def index():
    return render_template('index.html', batches=_batches_for_ui(),
                           llm=llm.status(), credit=llm.credit_status())


@app.route('/api/batches')
def api_batches():
    return jsonify(_batches_for_ui())


def _read_one(filename: str, raw: bytes, old: str):
    """-> parsed dict, or raises ValueError with a message fit for the user."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXT:
        try:
            return ocr.transcribe(raw, filename, old)
        except (ValueError, RuntimeError) as e:
            raise ValueError('%s: %s' % (filename, e))
    try:
        return parse_transcript(filename, raw)
    except ParseError as e:
        raise ValueError(str(e))


def _merge(chunks: list[tuple[str, dict]]) -> tuple[list, dict, list]:
    """Combine parsed files into one record list.

    The same course code can legitimately appear twice - a summer-term or
    make-up attempt supersedes the earlier grade. Where two files disagree the
    later file wins but the row is flagged so the operator can check it.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    identity, notes = {}, []
    for fname, parsed in chunks:
        for k, v in (parsed.get('identity') or {}).items():
            if k not in identity and v not in (None, ''):
                identity[k] = v
        for n in parsed.get('notes') or []:
            notes.append('%s: %s' % (fname, n))
        for r in parsed['records']:
            code = prc.norm(r.get('code'))
            if not code:
                continue
            rec = dict(r)
            rec['source_file'] = fname
            if code in merged:
                prev = merged[code]
                diffs = [k for k in ('name', 'credits', 'grade', 'semester')
                         if (prev.get(k) or None) != (rec.get(k) or None)]
                if diffs:
                    rec['conflict'] = diffs
                    prev['conflict'] = diffs
                    prev['conflict_with'] = fname
                # the later page wins for any field it actually states
                for k in ('name', 'credits', 'grade', 'semester'):
                    if rec.get(k) not in (None, ''):
                        prev[k] = rec[k]
                prev.setdefault('also_in', [])
                if fname not in prev['also_in']:
                    prev['also_in'].append(fname)
                prev['source_file'] = '%s (+%s)' % (prev['source_file'], fname)
            else:
                merged[code] = rec
                order.append(code)
    return [merged[c] for c in order], identity, notes


@app.route('/manual', methods=['GET', 'POST'])
def manual():
    """Enter the transcript by hand - no AI, no credit balance required.

    The course list is generated from the admission-batch PRC semester grids, so
    the operator only has to tick what the student completed and type the grades.
    """
    if request.method == 'GET':
        return render_template('manual.html', batches=_batches_for_ui(),
                               rows=[], old=prc.batches()[0],
                               new=prc.batches()[-1], last_sem=0,
                               filled=False, llm=llm.status())

    old = prc.resolve_batch(request.form.get('old_batch', ''))
    new = prc.resolve_batch(request.form.get('new_batch', ''))
    if not old or not new:
        flash('Choose a valid admission batch and readmission batch.', 'error')
        return redirect(url_for('manual'))
    if prc.batch_year(new) <= prc.batch_year(old):
        flash('The readmission batch must be later than the admission batch.',
              'error')
        return redirect(url_for('manual'))

    try:
        last = int(request.form.get('last_sem') or 0)
    except ValueError:
        last = 0
    last = max(0, min(8, last))

    keep = set(request.form.getlist('keep[]'))
    grades = request.form.getlist('grade[]')
    credits = request.form.getlist('credits[]')
    readmit = (request.form.get('readmit_sem') or '').strip()
    readmit = readmit if readmit.isdigit() else str(min(8, last + 1))

    rows, records = [], []
    seen = set()
    for sem, courses in prc.semester_courses(old).items():
        if sem > max(last, 1):
            continue
        for rec in courses:
            code = rec['code']
            cr = rec.get('C') or 0
            if cr <= 0 and rec.get('basket') == 'MAC':
                pass                                   # still show mandatory ones
            if code in seen:
                continue
            seen.add(code)
            i = len(rows)
            ticked = code in keep
            rows.append({'code': code, 'name': rec.get('name') or '',
                         'L': rec.get('L'), 'T': rec.get('T'), 'P': rec.get('P'),
                         'C': cr, 'basket': rec.get('basket'), 'sem': sem,
                         'ticked': ticked,
                         'grade': grades[i] if i < len(grades) else '',
                         'credits': credits[i] if i < len(credits) else ''})
            if ticked:
                g = (grades[i] if i < len(grades) else '').strip() or None
                cval = (credits[i] if i < len(credits) else '').strip()
                try:
                    cval = int(float(cval)) if cval else cr
                except ValueError:
                    cval = cr
                records.append({'code': code, 'name': rec.get('name') or '',
                                'credits': cval, 'grade': g, 'semester': sem,
                                'month_year': '', 'term': '',
                                'in_prc': True, 'prc_basket': rec.get('basket'),
                                'source_file': 'entered by hand'})

    if not records:
        flash('Tick at least one completed course.', 'error')
        return render_template('manual.html', batches=_batches_for_ui(),
                               rows=rows, old=old, new=new, last_sem=last,
                               filled=True, llm=llm.status())

    cid = uuid.uuid4().hex
    c = {'id': cid, 'old_batch': old, 'new_batch': new, 'records': records,
         'student': {
             'name': (request.form.get('name') or '').strip(),
             'roll_no': (request.form.get('roll_no') or '').strip(),
             'program': (request.form.get('program') or '').strip(),
             'previous_institution': '',
             'school_name': prc.program(new)['school'],
             'admission_batch': old, 'readmission_batch': new,
             'last_sem': str(last), 'readmit_sem': readmit},
         'last_sem': last, 'use_llm': request.form.get('use_llm') == '1',
         'lock': {}, 'filenames': ['entered by hand'], 'source': 'manual',
         'ocr_meta': {}, 'notes': [], 'warnings': [], 'images': [],
         'retry_files': []}
    c['courses'] = to_courses(records, old)
    c['warnings'] = _warnings({'records': records}, records, old)
    _recompute(c)
    CASES[cid] = c
    session['cid'] = cid
    flash('Recorded %d course(s). Review the mapping before downloading.'
          % len(records), 'ok')
    return redirect(url_for('review', cid=cid))


@app.route('/upload', methods=['POST'])
def upload():
    files = [f for f in request.files.getlist('transcripts') if f and f.filename]
    if not files:
        flash('Please choose at least one report-card file or photo.', 'error')
        return redirect(url_for('index'))
    if len(files) > MAX_FILES:
        flash('That is %d files; the limit is %d per case.'
              % (len(files), MAX_FILES), 'error')
        return redirect(url_for('index'))

    old = prc.resolve_batch(request.form.get('old_batch', ''))
    new = prc.resolve_batch(request.form.get('new_batch', ''))
    if not old or not new:
        flash('Choose a valid admission batch and readmission batch.', 'error')
        return redirect(url_for('index'))
    if prc.batch_year(new) <= prc.batch_year(old):
        flash('The readmission batch must be later than the admission batch.',
              'error')
        return redirect(url_for('index'))

    chunks, failed, blobs = [], [], {}
    gap = float(request.form.get('page_gap') or os.environ.get('PAGE_GAP', '1.5'))
    for i, f in enumerate(files):
        raw = f.read()
        ext = os.path.splitext(f.filename)[1].lower()
        if i and gap:
            # one image at a time: gateways cap work in flight
            time.sleep(gap)
        try:
            if ext in IMAGE_EXT:
                blobs[f.filename] = raw
            chunks.append((f.filename, _read_one(f.filename, raw, old)))
        except ValueError as e:
            failed.append(str(e))
    if not chunks:
        for m in failed:
            flash(m, 'error')
        return redirect(url_for('index'))

    records, ident, notes = _merge(chunks)
    if not records:
        flash('No courses could be read from %d file(s).' % len(chunks), 'error')
        for m in failed:
            flash(m, 'error')
        return redirect(url_for('index'))
    for m in failed:
        flash(m, 'error')

    last_sem = (request.form.get('last_sem') or '').strip()
    if not last_sem.isdigit():
        last_sem = str(max([r.get('semester') or 0 for r in records] or [0]))
    readmit_sem = (request.form.get('readmit_sem') or '').strip()
    if not readmit_sem.isdigit():
        readmit_sem = str(min(8, int(last_sem) + 1))

    is_image = all(os.path.splitext(n)[1].lower() in IMAGE_EXT
                   for n, _ in chunks)
    cid = uuid.uuid4().hex
    meta = {}
    for _, p in chunks:
        for k in ('model', 'provider', 'dims'):
            meta.setdefault(k, p.get(k))
    c = {
        'id': cid, 'old_batch': old, 'new_batch': new,
        'records': records,
        'student': {
            'name': (request.form.get('name') or ident.get('name', '')).strip(),
            'roll_no': (request.form.get('roll_no')
                        or ident.get('roll_no', '')).strip(),
            'program': (request.form.get('program')
                        or ident.get('program', '')).strip(),
            'previous_institution': ident.get('previous_institution', ''),
            'school_name': prc.program(new)['school'],
            'admission_batch': old, 'readmission_batch': new,
            'last_sem': last_sem, 'readmit_sem': readmit_sem,
        },
        'last_sem': int(last_sem),
        'use_llm': request.form.get('use_llm') == '1',
        'lock': {},
        'filenames': [n for n, _ in chunks],
        'source': 'image' if is_image else 'file',
        'ocr_meta': meta,
        'notes': notes,
        'warnings': [],
        'images': [],
        'retry_files': [m.split(':', 1)[0] for m in failed],
    }
    if is_image:
        # keep a copy of each page so the operator can compare them
        for name, _ in chunks:
            try:
                c['images'].append({'name': name,
                                    'data': 'data:image/png;base64,%s'
                                            % _data_url(blobs[name])})
            except Exception:                                    # noqa: BLE001
                pass
    CASES[cid] = c
    session['cid'] = cid
    return redirect(url_for('confirm', cid=cid))


def _data_url(raw: bytes) -> str:
    """Downscale and base64 a page for display on the confirm screen."""
    import base64
    import io
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:                                            # noqa: BLE001
        return base64.b64encode(raw).decode()
    img = img.convert('RGB')
    if max(img.size) > 1400:
        ratio = 1400.0 / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)),
                         Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=82, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


@app.route('/add/<cid>', methods=['POST'])
def add_files(cid):
    """Attach more pages to a case that has not been confirmed yet."""
    c = _case(cid)
    if 'result' in c:
        flash('This case has already been mapped. Start a new case to add '
              'more pages.', 'error')
        return redirect(url_for('review', cid=cid))
    files = [f for f in request.files.getlist('transcripts') if f and f.filename]
    if not files:
        flash('Nothing to add.', 'error')
        return redirect(url_for('confirm', cid=cid))
    chunks, failed = [], []
    for i, f in enumerate(files):
        if i:
            time.sleep(float(os.environ.get('PAGE_GAP', '1.5')))
        try:
            chunks.append((f.filename, _read_one(f.filename, f.read(),
                                                  c['old_batch'])))
        except ValueError as e:
            failed.append(str(e))
    for m in failed:
        flash(m, 'error')
    if not chunks:
        return redirect(url_for('confirm', cid=cid))
    records, ident, notes = _merge(chunks)
    have = {prc.norm(r['code']) for r in c['records']}
    added = [r for r in records if prc.norm(r['code']) not in have]
    c['records'] += added
    for k, v in ident.items():
        if not c['student'].get(k if k in ('name', 'roll_no', 'program') else k):
            c['student'].setdefault(k, v)
    c['notes'] = (c.get('notes') or []) + notes
    c['filenames'] = list(c.get('filenames') or []) + [n for n, _ in chunks]
    c['retry_files'] = [m.split(':', 1)[0] for m in failed]
    if failed:
        flash('%d page(s) could not be read and are listed for retry.'
              % len(failed), 'error')
    flash('Added %d course(s) from %d file(s).'
          % (len(added), len(chunks)), 'ok')
    return redirect(url_for('confirm', cid=cid))


@app.route('/confirm/<cid>', methods=['GET', 'POST'])
def confirm(cid):
    """Nothing is mapped until the operator has seen what was read."""
    c = _case(cid)
    if request.method == 'POST':
        codes = request.form.getlist('code[]')
        names = request.form.getlist('name[]')
        credits = request.form.getlist('credits[]')
        grades = request.form.getlist('grade[]')
        sems = request.form.getlist('semester[]')
        keep = set(request.form.getlist('keep[]'))
        out = []
        for i, code in enumerate(codes):
            code = prc.norm(code)
            if not code or (code not in keep):
                continue
            cr = credits[i].strip() if i < len(credits) else ''
            try:
                cr = int(float(cr)) if cr else None
            except ValueError:
                cr = None
            sem = sems[i].strip() if i < len(sems) else ''
            rec = prc.course(c['old_batch'], code)
            out.append({'code': code,
                        'name': (names[i] if i < len(names) else '').strip()
                                or (rec or {}).get('name') or '',
                        'credits': cr,
                        'grade': (grades[i] if i < len(grades) else '').strip()
                                 or None,
                        'semester': int(sem) if sem.isdigit() else
                                    prc.semester_of(c['old_batch'], code),
                        'month_year': '', 'term': '',
                        'in_prc': bool(rec),
                        'prc_basket': (rec or {}).get('basket'),
                        'transcribed': c.get('source') == 'image'})
        if not out:
            flash('Keep at least one course.', 'error')
            return redirect(url_for('confirm', cid=cid))

        c['records'] = out
        for k in ('name', 'roll_no', 'program'):
            v = (request.form.get(k) or '').strip()
            if v:
                c['student'][k] = v
        ls = (request.form.get('last_sem') or '').strip()
        rs = (request.form.get('readmit_sem') or '').strip()
        if ls.isdigit():
            c['last_sem'] = int(ls)
            c['student']['last_sem'] = ls
        if rs.isdigit():
            c['student']['readmit_sem'] = rs
        c['use_llm'] = request.form.get('use_llm') == '1'

        c['courses'] = to_courses(out, c['old_batch'])
        c['warnings'] = _warnings({'records': out}, out, c['old_batch'])
        _recompute(c)
        return redirect(url_for('review', cid=cid))

    rows = []
    for r in c['records']:
        rows.append({**r,
                     'prc_name': (prc.course(c['old_batch'], r['code'])
                                  or {}).get('name') or ''})
    return render_template('confirm.html', c=c, rows=rows, llm=llm.status())


def _warnings(parsed, records, batch) -> list[str]:
    w = []
    unknown = [r['code'] for r in records if not prc.course(batch, r['code'])]
    if unknown:
        w.append('%d course code(s) are not in the %s PRC and were matched on the '
                 'report card alone: %s' % (len(unknown), batch,
                                            ', '.join(unknown[:8])))
    missing = [r['code'] for r in records if r.get('semester') is None]
    if missing:
        w.append('%d course(s) had no recognisable semester and were shown in the '
                 'first group: %s' % (len(missing), ', '.join(missing[:8])))
    nog = [r['code'] for r in records if not r.get('grade')]
    if nog:
        w.append('%d course(s) have no grade; they are treated as passed: %s'
                 % (len(nog), ', '.join(nog[:8])))
    return w


@app.route('/review/<cid>')
def review(cid):
    c = _case(cid)
    r = c['result']
    return render_template(
        'review.html', c=c, r=r, student=c['student'],
        options=_new_courses(c), warnings=c['warnings'],
        llm=llm.status(),
        sems=sorted({x['sem'] for x in r['table1']}, key=lambda v: (v is None, v)))


@app.route('/review/<cid>/override', methods=['POST'])
def override(cid):
    c = _case(cid)
    for old_code in list(c['lock']):
        if old_code not in request.form:
            c['lock'].pop(old_code, None)
    for key, val in request.form.items():
        if key.startswith('map__'):
            old_code = prc.norm(key[5:])
            val = prc.norm(val)
            if val:
                c['lock'][old_code] = val
    _recompute(c)
    flash('Mapping updated.', 'ok')
    return redirect(url_for('review', cid=cid))


@app.route('/review/<cid>/toggle_llm', methods=['GET', 'POST'])
def toggle_llm(cid):
    c = _case(cid)
    c['use_llm'] = not c.get('use_llm', True)
    _recompute(c)
    return redirect(url_for('review', cid=cid))


@app.route('/download/<cid>')
def download(cid):
    c = _case(cid)
    if 'result' not in c or request.args.get('refresh'):
        _recompute(c)
    try:
        pdf = report.render(c['result'], c['student'])
    except ValueError as e:
        abort(500, 'The report could not be laid out: %s' % e)
    name = '_'.join(x for x in [c['student'].get('roll_no'),
                                c['student'].get('name')] if x)
    fn = (name or 'course_equivalence').replace(' ', '_')
    return send_file(io.BytesIO(pdf), mimetype='application/pdf',
                     as_attachment=True,
                     download_name='Course_Equivalence_%s_%s_to_%s.pdf'
                                   % (fn, c['old_batch'], c['new_batch']))


@app.route('/review/<cid>/json')
def as_json(cid):
    c = _case(cid)
    return jsonify({'student': c['student'], 'old_batch': c['old_batch'],
                    'new_batch': c['new_batch'], 'lock': c['lock'],
                    'result': {k: v for k, v in c['result'].items()
                               if k != 'pairs'},
                    'pairs': c['result'].get('pairs')})


@app.errorhandler(413)
def too_big(_):
    flash('That file is larger than %d MB.' % (MAX_UPLOAD // (1024 * 1024)),
          'error')
    return redirect(url_for('index'))


@app.errorhandler(404)
def nf(e):
    return render_template('error.html', message=getattr(e, 'description',
                                                         'Not found')), 404


@app.errorhandler(500)
def se(e):
    return render_template('error.html', message=str(e)), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=bool(os.environ.get('DEBUG')))
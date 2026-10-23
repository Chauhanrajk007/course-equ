"""Transcribe a photographed / scanned report card using a vision model.

Images go through the same normalisation as a parsed .docx or .xlsx: the result
is a list of plain dicts that transcript.to_courses() can consume. Nothing here
guesses - every field is validated against the admission-batch PRC before it is
returned, and anything doubtful is flagged for the user to correct on screen.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time

from . import llm, prc

MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
        '.tif': 'image/tiff', '.tiff': 'image/tiff'}
IMAGE_EXT = set(MIME)
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_SIDE = 1700                       # keeps the request within gateway limits

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'data', 'ocr_cache.json')

SYSTEM = """You transcribe academic report cards into JSON. Accuracy matters more \
than completeness.

For each course row you can see, output one object with:
  code     - the course code exactly as printed, uppercase, no spaces (e.g. "MAT1001")
  name     - the course name as printed
  credits  - the credit value as a number, or null if not shown
  grade    - the letter grade exactly as printed (e.g. "B+", "F", "NP"), or null
  semester - 1-8 if the document shows which semester it is, otherwise null

Rules:
- Transcribe only what you can actually read. Never guess a course code.
- If a code is unclear or partly obscured, still include it but set "code" to your
  best reading and add it to "uncertain".
- Do not include totals, CGPA, SGPA or attendance rows as courses.
- A lab/theory row counts as its own course if it has its own code.

Also return "identity" with any of: name, roll_no, program, semester - taken
only from what is printed.

Reply with JSON only, no prose and no code fences:
{"identity":{"name":null,"roll_no":null,"program":null,"semester":null},
 "rows":[{"code":"...","name":"...","credits":0,"grade":"...","semester":1}],
 "uncertain":["..."]}"""


def supported(filename: str) -> bool:
    return os.path.splitext(filename or '')[1].lower() in IMAGE_EXT


def prepare(data: bytes):
    """Downscale in place; returns (b64, mime, note) or raises ValueError."""
    if not data:
        raise ValueError('The image file is empty.')
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Image is larger than %d MB.'
                         % (MAX_IMAGE_BYTES // (1024 * 1024)))
    try:
        from PIL import Image
    except ImportError:
        raise ValueError('Image support needs Pillow: pip install Pillow')
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:                                  # noqa: BLE001
        raise ValueError('That file could not be opened as an image (%s).' % e)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    if max(img.size) > MAX_SIDE:
        ratio = MAX_SIDE / float(max(img.size))
        img = img.resize((max(1, int(img.width * ratio)),
                          max(1, int(img.height * ratio))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return b64, 'image/png', '%dx%d' % (img.width, img.height)


def _cache_key(b64: str, model: str, batch: str) -> str:
    return hashlib.sha256(
        ('%s|%s|%s' % (model, batch, b64[:4096])).encode()).hexdigest()[:32]


def _load() -> dict:
    try:
        with open(CACHE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except OSError:
        pass


def transcribe(data: bytes, filename: str, batch: str,
               use_cache: bool = True) -> dict:
    """-> {'identity', 'records', 'notes', 'source'}"""
    # validate the file before anything else, so a corrupt upload is reported as
    # such even when no AI key is configured
    b64, mime, dims = prepare(data)
    if not llm.available():
        raise RuntimeError(
            'Reading an image needs an AI key. Set OPENROUTER_API_KEY (or '
            'GROQ_API_KEY / XAI_API_KEY) and restart, or use "Enter the courses '
            'manually" which needs no AI at all.')

    cfg = llm._cfg()
    key = _cache_key(b64, cfg['model'], batch)
    cache = _load()
    if use_cache and key in cache:
        out = dict(cache[key])
        out['cached'] = True
        return out

    db = prc.courses(batch)
    # give the model the code list so it can correct its own misreads
    known = sorted(db)
    prompt = (
        'Transcribe the report card in this image.\n'
        'The student was admitted to batch %s. These course codes exist in that '
        'PRC - if a printed code is very close to one of them, prefer that exact '
        'spelling:\n%s'
        % (batch, ', '.join(known[:400])))

    content = [{'type': 'text', 'text': prompt},
               {'type': 'image_url',
                'image_url': {'url': 'data:%s;base64,%s' % (mime, b64)}}]
    body = json.dumps({
        'model': cfg['model'],
        'messages': [{'role': 'system', 'content': SYSTEM},
                     {'role': 'user', 'content': content}],
        'temperature': 0,
        'max_tokens': llm.MAX_TOKENS,
        'response_format': {'type': 'json_object'},
    }).encode()

    payload = llm._post(cfg['url'], body, llm._headers(cfg), timeout=200)

    try:
        raw = payload['choices'][0]['message']['content']
        parsed = json.loads(raw if isinstance(raw, str) else json.dumps(raw))
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError('The AI service did not return usable JSON.')

    out = _normalise(parsed, batch)
    out.update({'source': 'image', 'filename': filename, 'model': cfg['model'],
                'provider': cfg['label'], 'dims': dims, 'cached': False,
                'transcribed_at': time.strftime('%Y-%m-%d %H:%M')})
    cache[key] = {k: out[k] for k in ('identity', 'records', 'notes')}
    _save(cache)
    return out


def _normalise(parsed: dict, batch: str) -> dict:
    ident_raw = parsed.get('identity') or {}
    notes = []
    records, seen = [], set()

    for r in (parsed.get('rows') or []):
        if not isinstance(r, dict):
            continue
        code = prc.norm(r.get('code'))
        if not re.match(r'^[A-Z]{3,4}\d{3,4}[A-Z]?$', code):
            if code:
                notes.append('Ignored an unreadable course code: %r'
                             % str(r.get('code'))[:24])
            continue
        if code in seen:
            continue
        seen.add(code)
        rec = prc.course(batch, code)
        cr = r.get('credits')
        cr = int(cr) if isinstance(cr, (int, float)) else None
        grade = str(r.get('grade') or '').strip() or None
        sem = r.get('semester')
        sem = int(sem) if isinstance(sem, (int, float)) and 1 <= sem <= 8 else None
        if sem is None and ident_raw.get('semester'):
            s = ident_raw['semester']
            s = str(s).strip().rstrip('.').upper()
            if s.isdigit():
                sem = int(s)
        if sem is None and rec:
            sem = prc.semester_of(batch, code)
        if cr is None and rec:
            cr = rec.get('C')
        records.append({
            'code': code,
            'name': str(r.get('name') or '').strip()
                    or (rec or {}).get('name') or '',
            'credits': cr,
            'grade': grade,
            'semester': sem,
            'month_year': '', 'term': '',
            'in_prc': bool(rec),
            'prc_basket': (rec or {}).get('basket'),
            'transcribed': True,
        })

    unknown = [r['code'] for r in records if not r['in_prc']]
    if unknown:
        notes.append('%d code(s) are not in the %s PRC: %s'
                     % (len(unknown), batch, ', '.join(unknown)))
    if not records:
        notes.append('No courses could be read from the image. Try a sharper '
                     'photo, or upload the original file.')

    ident = {}
    for key in ('name', 'roll_no', 'program', 'semester'):
        v = ident_raw.get(key)
        if v not in (None, ''):
            ident[key] = str(v).strip()
    return {'identity': ident, 'records': records, 'notes': notes}
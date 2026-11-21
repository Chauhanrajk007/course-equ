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
MAX_SIDE = 1200                       # keeps image crisp while minimizing payload & upload time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.environ.get('COURSE_EQUIV_CACHE_DIR') or (
    '/tmp' if os.environ.get('VERCEL') else os.path.join(_BASE, 'data'))
CACHE = os.path.join(_CACHE_DIR, 'ocr_cache.json')

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
    img.save(buf, 'JPEG', quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return b64, 'image/jpeg', '%dx%d' % (img.width, img.height)


def _cache_key(b64: str, model: str, batch: str, program: str | None = None) -> str:
    return hashlib.sha256(
        ('%s|%s|%s|%s' % (model, batch, program or '', b64[:4096])).encode()).hexdigest()[:32]


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


def _prompt(batch: str, program: str | None, label: str) -> str:
    # give the model the code list so it can correct its own misreads
    db = prc.courses(batch, program)
    known = sorted({(r.get('code') or u) for u, r in db.items()})
    return (
        'Transcribe %s.\n'
        'The student was admitted to batch %s. These course codes exist in that '
        'PRC - if a printed code is very close to one of them, prefer that exact '
        'spelling:\n%s'
        % (label, batch, ', '.join(known[:400])))


def _ask(cfg, prompt: str, b64: str, mime: str) -> dict:
    """One vision request. Returns the model's parsed JSON object."""
    content = [{'type': 'text', 'text': prompt},
               {'type': 'image_url',
                'image_url': {'url': 'data:%s;base64,%s' % (mime, b64)}}]
    payload_body = {
        'model': cfg['model'],
        'messages': [{'role': 'system', 'content': SYSTEM},
                     {'role': 'user', 'content': content}],
        'temperature': 0,
        'max_tokens': int(os.environ.get('COURSE_EQUIV_VISION_MAX_TOKENS',
                                         '4000')),
        'response_format': {'type': 'json_object'},
    }
    if cfg['model'].endswith(':free'):
        # free vision models spend the token budget on reasoning first
        payload_body['reasoning'] = {'enabled': False}
    body = json.dumps(payload_body).encode()

    try:
        payload = llm._post(cfg['url'], body, llm._headers(cfg), timeout=60)
    except Exception as err:
        # Fallback to secondary vision provider if available
        fallback_cfg = None
        if cfg['name'] == 'groq' and (os.environ.get('OPENROUTER_API_KEY') or '').strip():
            fallback_cfg = {'name': 'openrouter', 'url': 'https://openrouter.ai/api/v1/chat/completions',
                            'key': os.environ['OPENROUTER_API_KEY'].strip(),
                            'model': 'nvidia/nemotron-3.5-super-vl:free', 'label': 'OpenRouter'}
        elif cfg['name'] == 'openrouter' and (os.environ.get('GROQ_API_KEY') or '').strip():
            fallback_cfg = {'name': 'groq', 'url': 'https://api.groq.com/openai/v1/chat/completions',
                            'key': os.environ['GROQ_API_KEY'].strip(),
                            'model': 'qwen/qwen3.8-27b', 'label': 'Groq'}
        if fallback_cfg:
            try:
                payload_body['model'] = fallback_cfg['model']
                if fallback_cfg['model'].endswith(':free'):
                    payload_body['reasoning'] = {'enabled': False}
                else:
                    payload_body.pop('reasoning', None)
                fb_body = json.dumps(payload_body).encode()
                payload = llm._post(fallback_cfg['url'], fb_body, llm._headers(fallback_cfg), timeout=60)
            except Exception:
                raise err
        else:
            raise err
    try:
        raw = payload['choices'][0]['message']['content']
        return json.loads(raw if isinstance(raw, str) else json.dumps(raw))
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError('The AI service did not return usable JSON.')


_rapid_engine = None

def _get_rapid_engine():
    global _rapid_engine
    if _rapid_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_engine = RapidOCR()
        except Exception:
            _rapid_engine = False
    return _rapid_engine if _rapid_engine is not False else None

CODE_RE = re.compile(r'^[A-Z]{3,4}\d{3,4}[A-Z]?$')
GRADE_RE = re.compile(r'^(O|A\+|A|B\+|B|C|D|F|S|U|I|RC|NP|NC|NE)$', re.I)

def parse_with_rapid(img, batch: str, program: str | None = None) -> dict | None:
    engine = _get_rapid_engine()
    if not engine:
        return None
    try:
        from PIL import Image
        import numpy as np
        if isinstance(img, (bytes, bytearray)):
            img = Image.open(io.BytesIO(img)).convert('RGB')
        elif not isinstance(img, Image.Image):
            return None
        arr = np.array(img)
        result, _ = engine(arr)
        if not result:
            return None
        texts = [item[1].strip() for item in result]
        full_text = '\n'.join(texts)

        identity = {}
        m_name = re.search(r'Student\s*Name\s*[:\-]?\s*([A-Za-z\s]+)', full_text, re.I)
        if m_name:
            name_clean = m_name.group(1).split('\n')[0].strip()
            name_clean = re.sub(r'^(Father|Mother|Batch|Roll).*', '', name_clean, flags=re.I).strip()
            if name_clean:
                identity['name'] = name_clean
        m_roll = re.search(r'Roll\s*Number\s*[:\-]?\s*([0-9]{4,5}[A-Za-z0-9]+)', full_text, re.I)
        if m_roll:
            identity['roll_no'] = m_roll.group(1).upper().replace('L', 'I')
        m_sem = re.search(r'(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|[1-8])\s*Semester', full_text, re.I)
        sem_map = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5, 'sixth': 6, 'seventh': 7, 'eighth': 8}
        sem_val = sem_map.get(m_sem.group(1).lower()) if m_sem else None
        if sem_val:
            identity['semester'] = sem_val

        # Cluster items by horizontal line (y-proximity)
        items = []
        for box, text, score in result:
            y_center = sum(pt[1] for pt in box) / 4.0
            x_left = min(pt[0] for pt in box)
            items.append({'y': y_center, 'x': x_left, 'text': text.strip()})

        items.sort(key=lambda it: it['y'])
        line_clusters = []
        for it in items:
            placed = False
            for cluster in line_clusters:
                if abs(cluster['y'] - it['y']) < 18:
                    cluster['items'].append(it)
                    cluster['y'] = sum(x['y'] for x in cluster['items']) / len(cluster['items'])
                    placed = True
                    break
            if not placed:
                line_clusters.append({'y': it['y'], 'items': [it]})

        rows = []
        seen = set()
        for cluster in line_clusters:
            cluster['items'].sort(key=lambda it: it['x'])
            c_texts = [it['text'] for it in cluster['items']]
            code = None
            for txt in c_texts:
                norm_t = prc.norm(txt)
                if CODE_RE.match(norm_t) and not code:
                    code = norm_t
            if not code or code in seen:
                continue
            seen.add(code)
            name, credits, grade = '', None, None
            for txt in c_texts:
                if txt.isdigit() and len(txt) == 1 and credits is None:
                    credits = int(txt)
                elif GRADE_RE.match(txt) and grade is None:
                    grade = txt.upper()
                elif not name and len(txt) > 2 and not CODE_RE.match(prc.norm(txt)) and not txt.isdigit():
                    name = txt
            rec = prc.course(batch, code, program)
            if rec:
                name = name or rec.get('name')
                credits = credits or rec.get('C')
                row_sem = sem_val or prc.semester_of(batch, code, program)
            else:
                row_sem = sem_val
            rows.append({'code': code, 'name': name, 'credits': credits, 'grade': grade, 'semester': row_sem})
        return {'identity': identity, 'rows': rows, 'uncertain': []} if rows else None
    except Exception:
        return None


def _vision_cfg_or_raise():
    cfg = llm.vision_cfg()
    if not cfg:
        raise RuntimeError(
            'Reading an image needs an AI key with a vision model. Set '
            'OPENROUTER_API_KEY or XAI_API_KEY (free vision models need no '
            'credit) and restart, or use "Enter the courses manually" which '
            'needs no AI at all.')
    return cfg


def transcribe(data: bytes, filename: str, batch: str,
               program: str | None = None, use_cache: bool = True) -> dict:
    """-> {'identity', 'records', 'notes', 'source'}"""
    # validate the file before anything else, so a corrupt upload is reported as
    # such even when no AI key is configured
    b64, mime, dims = prepare(data)

    # 1. Try RapidOCR (PaddleOCR local) first
    rapid_parsed = parse_with_rapid(data, batch, program)
    if rapid_parsed and rapid_parsed.get('rows'):
        out = _normalise(rapid_parsed, batch, program)
        out.update({'source': 'image', 'filename': filename, 'model': 'rapidocr-paddle',
                    'provider': 'RapidOCR (PaddleOCR Local)', 'dims': dims, 'cached': False,
                    'transcribed_at': time.strftime('%Y-%m-%d %H:%M')})
        return out

    # 2. Fall back to cloud vision
    cfg = _vision_cfg_or_raise()

    key = _cache_key(b64, cfg['model'], batch, program)
    cache = _load()
    parsed = cache.get(key) if use_cache else None
    if not parsed:
        parsed = _ask(cfg, _prompt(batch, program, 'the report card in this image'),
                      b64, mime)
        cache[key] = {k: parsed.get(k) for k in ('identity', 'rows', 'uncertain')}
        _save(cache)
    out = _normalise(parsed, batch, program)
    out.update({'source': 'image', 'filename': filename, 'model': cfg['model'],
                'provider': cfg['label'], 'dims': dims, 'cached': False,
                'transcribed_at': time.strftime('%Y-%m-%d %H:%M')})
    return out


def pdf_page_images(data: bytes, dpi: int = 150) -> list:
    """Render each PDF page to a PIL image. Raises ValueError when it cannot."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise ValueError('PDF support needs pypdfium2: pip install pypdfium2')
    try:
        doc = pdfium.PdfDocument(io.BytesIO(data))
    except Exception as e:                                  # noqa: BLE001
        raise ValueError('That file could not be opened as a PDF (%s).' % e)
    scale = max(1.0, dpi / 72.0)
    out = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            out.append(page.render(scale=scale).to_pil().convert('RGB'))
    finally:
        doc.close()
    return out


def transcribe_pdf(data: bytes, filename: str, batch: str,
                   program: str | None = None, use_cache: bool = True) -> dict:
    """Read a scanned PDF page by page with RapidOCR or vision model."""
    pages = pdf_page_images(data)
    if not pages:
        raise ValueError('The PDF has no pages to read.')
    total_pages = len(pages)
    limit = int(os.environ.get('COURSE_EQUIV_MAX_PAGES', '60'))
    truncated = total_pages > limit
    pages = pages[:limit]

    # 1. Try RapidOCR (PaddleOCR local) on the pages
    engine = _get_rapid_engine()
    if engine:
        rapid_pages = []
        for p in pages:
            r = parse_with_rapid(p, batch, program)
            if r and r.get('rows'):
                rapid_pages.append(r)
        if len(rapid_pages) == len(pages) and rapid_pages:
            merged_rows, identity, uncertain, notes = [], {}, [], []
            for parsed in rapid_pages:
                for r in (parsed.get('rows') or []):
                    if isinstance(r, dict):
                        merged_rows.append(r)
                for k, v in (parsed.get('identity') or {}).items():
                    if v not in (None, '') and identity.get(k) in (None, ''):
                        identity[k] = v
            if truncated:
                notes.append('Only the first %d pages were read; the PDF has %d.'
                             % (limit, total_pages))
            out = _normalise({'identity': identity, 'rows': merged_rows,
                              'uncertain': uncertain}, batch, program)
            out['notes'] = notes + out['notes']
            out.update({'source': 'pdf-scan', 'filename': filename, 'model': 'rapidocr-paddle',
                        'provider': 'RapidOCR (PaddleOCR Local)', 'dims': '%d page(s)' % len(pages),
                        'cached': False,
                        'transcribed_at': time.strftime('%Y-%m-%d %H:%M')})
            return out

    # 2. Fall back to cloud vision
    cfg = _vision_cfg_or_raise()
    pages = pdf_page_images(data)
    if not pages:
        raise ValueError('The PDF has no pages to read.')
    total_pages = len(pages)
    limit = int(os.environ.get('COURSE_EQUIV_MAX_PAGES', '60'))
    truncated = total_pages > limit
    pages = pages[:limit]
    from PIL import Image

    import threading
    from concurrent.futures import ThreadPoolExecutor

    prompt = _prompt(batch, program, 'the report card on this page')
    cache = _load()
    cache_lock = threading.Lock()

    def _read_single_page(n_img):
        n, img = n_img
        buf = io.BytesIO()
        if max(img.size) > MAX_SIDE:
            ratio = MAX_SIDE / float(max(img.size))
            img = img.resize((max(1, int(img.width * ratio)),
                              max(1, int(img.height * ratio))), Image.LANCZOS)
        img.save(buf, 'JPEG', quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        key = _cache_key(b64, cfg['model'], batch, program)
        with cache_lock:
            parsed = cache.get(key)
        if not (use_cache and parsed):
            parsed = _ask(cfg, prompt, b64, 'image/jpeg')
            with cache_lock:
                cache[key] = {k: parsed.get(k) for k in ('identity', 'rows',
                                                         'uncertain')}
        return n, parsed

    workers = min(4, len(pages))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        page_results = list(executor.map(_read_single_page, enumerate(pages, 1)))

    merged_rows, identity, uncertain, notes = [], {}, [], []
    for n, parsed in sorted(page_results, key=lambda x: x[0]):
        for r in (parsed.get('rows') or []):
            if isinstance(r, dict):
                merged_rows.append(r)
        for k, v in (parsed.get('identity') or {}).items():
            if v not in (None, '') and identity.get(k) in (None, ''):
                identity[k] = v
        uncertain.extend(parsed.get('uncertain') or [])
    _save(cache)

    if truncated:
        notes.append('Only the first %d pages were read; the PDF has %d.'
                     % (limit, total_pages))
    out = _normalise({'identity': identity, 'rows': merged_rows,
                      'uncertain': uncertain}, batch, program)
    out['notes'] = notes + out['notes']
    out.update({'source': 'pdf-scan', 'filename': filename, 'model': cfg['model'],
                'provider': cfg['label'], 'dims': '%d page(s)' % len(pages),
                'cached': False,
                'transcribed_at': time.strftime('%Y-%m-%d %H:%M')})
    return out


def _normalise(parsed: dict, batch: str, program: str | None = None) -> dict:
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
        rec = prc.course(batch, code, program)
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
            sem = prc.semester_of(batch, code, program)
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
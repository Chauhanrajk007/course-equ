"""Grok advisor for ambiguous course equivalences.

The rule engine (mapping.py) owns every credit decision. This module is only
consulted for courses the engine could not place with confidence - in practice
professional and open electives, where a student picks arbitrary subjects and no
keyword rule can judge equivalence.

Guarantees:
  * the model may only choose from the candidate shortlist we supply;
  * every proposal must reconcile credits exactly, otherwise it is discarded;
  * the model never sets credits, totals or basket minima;
  * results are cached on disk, so a repeated run costs nothing;
  * with no API key set the app behaves exactly as if the advisor were absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

from . import prc

PROVIDERS = {
    'xai': {
        'env': 'XAI_API_KEY',
        'url': 'https://api.x.ai/v1/chat/completions',
        'models': ['grok-4-fast-non-reasoning', 'grok-4', 'grok-3-mini',
                   'grok-3'],
        'label': 'xAI Grok',
    },
    'groq': {
        'env': 'GROQ_API_KEY',
        'url': 'https://api.groq.com/openai/v1/chat/completions',
        'models': ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant',
                   'openai/gpt-oss-120b', 'qwen/qwen3-32b'],
        'label': 'Groq',
    },
    'openrouter': {
        'env': 'OPENROUTER_API_KEY',
        'url': 'https://openrouter.ai/api/v1/chat/completions',
        'models': ['x-ai/grok-4.3', 'openai/gpt-4.1-mini',
                   'google/gemini-2.5-flash', 'anthropic/claude-sonnet-4.5',
                   'openai/gpt-oss-120b', 'meta-llama/llama-3.3-70b-instruct'],
        'label': 'OpenRouter',
    },
}
ORDER = ('xai', 'openrouter', 'groq')
UA = 'CourseEquivalence/1.0 (+presidency university academic cell)'
# A capped ceiling keeps gateway accounts with a low balance from rejecting the
# request outright, and is ample for the short JSON reply we ask for.
MAX_TOKENS = int(os.environ.get('COURSE_EQUIV_MAX_TOKENS', '2000'))


def _provider():
    """Pick a provider: an explicit COURSE_EQUIV_PROVIDER wins, otherwise the
    first one whose key is present."""
    want = (os.environ.get('COURSE_EQUIV_PROVIDER') or '').strip().lower()
    if want in PROVIDERS and (os.environ.get(PROVIDERS[want]['env']) or '').strip():
        return want
    for name in ORDER:
        if (os.environ.get(PROVIDERS[name]['env']) or '').strip():
            return name
    return None


def _cfg():
    name = _provider()
    if not name:
        return None
    p = PROVIDERS[name]
    key = (os.environ.get(p['env']) or '').strip()
    model = (os.environ.get('COURSE_EQUIV_MODEL') or '').strip()
    if model not in p['models']:
        model = os.environ.get('COURSE_EQUIV_MODEL_%s' % name.upper()) \
            or p['models'][0]
    return {'name': name, 'url': p['url'], 'key': key, 'model': model,
            'label': p['label'], 'env': p['env']}


# Vercel's bundle is read-only; /tmp is the only writable location there.
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.environ.get('COURSE_EQUIV_CACHE_DIR') or (
    '/tmp' if os.environ.get('VERCEL') else os.path.join(_BASE, 'data'))
CACHE_PATH = os.path.join(_CACHE_DIR, 'llm_cache.json')
_lock = threading.Lock()
_cache = None


# ----------------------------------------------------------------- cache
def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH, encoding='utf-8') as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is None:
        return
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, indent=1, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def _key(old_batch, new_batch, old_code, candidates) -> str:
    blob = json.dumps([old_batch, new_batch, old_code, candidates], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def api_key() -> str | None:
    c = _cfg()
    return c['key'] if c else None


def available() -> bool:
    return _cfg() is not None


def status() -> dict:
    c = _cfg()
    n = len(_load_cache())
    if not c:
        return {'available': False, 'model': None, 'provider': None,
                'label': None, 'cached': n,
                'hint': 'set one of: %s'
                        % ', '.join(PROVIDERS[k]['env'] for k in ORDER)}
    return {'available': True, 'model': c['model'], 'provider': c['name'],
            'label': c['label'], 'cached': n}


def credit_status(force: bool = False) -> dict:
    """Remaining gateway credit, so the UI can warn before a page fails.

    Only OpenRouter exposes this. Cached briefly - it is informational.
    """
    c = _cfg()
    if not c or c['name'] != 'openrouter':
        return {'known': False}
    with _lock:
        cached = _credit_cache.get(c['key'], {})
        if not force and cached and time.time() - cached.get('at', 0) < 600:
            return cached['value']
    try:
        req = urllib.request.Request('https://openrouter.ai/api/v1/credits',
                                     headers={'Authorization': 'Bearer %s'
                                                      % c['key'],
                                              'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode()).get('data', {})
        val = {'known': True,
               'remaining': round((d.get('total_credits') or 0)
                                  - (d.get('total_usage') or 0), 4),
               'exhausted': ((d.get('total_credits') or 0)
                              - (d.get('total_usage') or 0)) <= 0}
    except Exception:                                        # noqa: BLE001
        val = {'known': False}
    with _lock:
        _credit_cache[c['key']] = {'at': time.time(), 'value': val}
    return val


_credit_cache: dict = {}


# ------------------------------------------------------------- candidates
def candidates_for(o, new_batch: str, limit: int = 10) -> list[dict]:
    """Shortlist the model is allowed to choose from."""
    out = []
    for nc, rec in prc.courses(new_batch).items():
        if (rec.get('C') or 0) > o.credits:
            continue
        if rec.get('basket') != o.basket and \
                not nc.startswith(o.code[:3]):
            continue
        out.append({'code': nc, 'name': rec.get('name') or '',
                    'credits': rec.get('C') or 0, 'basket': rec.get('basket'),
                    'sem': rec.get('sem')})
    out.sort(key=lambda r: (abs((r['credits'] or 0) - o.credits), r['code']))
    return out[:limit]


SYSTEM = """You are a course-equivalence officer for a university academic cell.

You decide whether a course a student already passed in an older curriculum is
equivalent to a course in the curriculum they are re-entered into.

Rules you must follow:
1. Choose ONLY from the candidate list given for that course. Never invent a code.
2. You may choose more than one candidate ONLY when together they represent the
   single subject the student already passed (for example a theory course that
   the new curriculum splits into a theory course plus its laboratory).
3. The credits of the candidates you choose MUST sum to exactly the credits of
   the passed course. If no combination sums exactly, return an empty list.
4. If nothing is genuinely equivalent, return an empty list. An empty list is a
   normal, acceptable answer. Never guess to avoid returning nothing.
5. Judge equivalence by subject content, not by similar wording. A renamed
   subject is equivalent; a different subject with a similar name is not.

Reply with JSON only, no prose and no code fences:
{"decisions":[{"old_code":"...","new_codes":["..."],"confidence":0.0,"reason":"one short sentence"}]}"""


def _build_prompt(batch_pairs: list[dict]) -> str:
    blocks = []
    for it in batch_pairs:
        cands = '\n'.join(
            '    - %s | %s | %s credits | basket %s'
            % (c['code'], c['name'], c['credits'], c['basket'])
            for c in it['candidates'])
        blocks.append(
            'Passed course (older curriculum %s):\n'
            '  %s | %s | %s credits | basket %s | semester %s\n'
            '  Candidates (newer curriculum %s):\n%s'
            % (it['old_batch'], it['old_code'], it['old_name'], it['old_credits'],
               it['old_basket'], it['old_sem'], it['new_batch'], cands))
    return ('Decide equivalence for each of the following %d passed courses.\n\n%s'
            % (len(batch_pairs), '\n\n'.join(blocks)))


def _post(url: str, body: bytes, headers: dict, timeout: int = 120):
    """POST with backoff.

    Gateways such as OpenRouter cap how much work may be *in flight* at once and
    answer HTTP 402 in_flight_budget_exhausted or 429 when a burst arrives.
    Retrying after a short pause is the documented remedy, so this is not an
    error path - it is the normal path.
    """
    import urllib.error
    import urllib.request
    attempts = int(os.environ.get('COURSE_EQUIV_RETRIES', '5'))
    last = None
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, method='POST',
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')
            last = (e.code, detail)
            if e.code in (402, 408, 409, 429, 500, 502, 503, 529):
                budget = 'in_flight_budget_exhausted' in detail
                # a budget rejection needs a longer settle than a rate limit
                base = 6.0 if budget else 1.5
                time.sleep(base * (2 ** attempt))
                continue
            raise RuntimeError('HTTP %s from %s: %s'
                               % (e.code, url.split('/')[2], detail[:300]))
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = (0, str(e))
            time.sleep(1.5 * (2 ** attempt))
            continue
    code, detail = last or (0, 'no response')
    if 'in_flight_budget' in detail or code in (402, 429):
        if 'add credits' in detail or 'available credits' in detail:
            raise RuntimeError(
                'The AI account has no credit left, so this page cannot be read. '
                'Top up the balance, or use "Enter the courses manually" - it '
                'needs no AI at all.')
        raise RuntimeError(
            'The AI gateway is busy - it caps how much work may run at once. '
            'This normally clears within a minute: press Retry, or attach the '
            'remaining pages one at a time.')
    raise RuntimeError('The AI service could not be reached after %d attempt(s). %s'
                       % (attempts, detail[:200]))


def _headers(cfg) -> dict:
    h = {'Authorization': 'Bearer %s' % cfg['key'],
         'Content-Type': 'application/json',
         'User-Agent': UA, 'Accept': 'application/json'}
    if cfg['name'] == 'openrouter':
        # OpenRouter asks callers to identify themselves and route by header.
        h['HTTP-Referer'] = os.environ.get('OPENROUTER_SITE',
                                           'http://localhost:5000')
        h['X-Title'] = 'Course Equivalence'
    return h


def _call(prompt: str, timeout: int = 120) -> dict | None:
    cfg = _cfg()
    if not cfg:
        return None
    body = json.dumps({
        'model': cfg['model'],
        'messages': [{'role': 'system', 'content': SYSTEM},
                     {'role': 'user', 'content': prompt}],
        'temperature': 0,
        'max_tokens': MAX_TOKENS,
        'response_format': {'type': 'json_object'},
    }).encode()
    try:
        payload = _post(cfg['url'], body, _headers(cfg), timeout)
    except RuntimeError:
        return None
    try:
        content = payload['choices'][0]['message']['content']
        if isinstance(content, list):                 # some gateways stream parts
            content = ''.join(p.get('text', '') for p in content
                              if isinstance(p, dict))
        return json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _validate(raw, items) -> list[dict]:
    """Keep only proposals that are internally consistent and credit-exact."""
    by_code = {it['old_code']: it for it in items}
    out = []
    for d in (raw or {}).get('decisions', []):
        try:
            old_code = prc.norm(d.get('old_code'))
            picks = [prc.norm(x) for x in (d.get('new_codes') or []) if prc.norm(x)]
            conf = float(d.get('confidence', 0))
        except (TypeError, ValueError):
            continue
        it = by_code.get(old_code)
        if not it or not picks or len(set(picks)) != len(picks):
            continue
        allowed = {c['code'] for c in it['candidates']}
        if any(p not in allowed for p in picks):
            continue                                  # model invented a code
        total = sum(c['credits'] for c in it['candidates'] if c['code'] in picks)
        if total != it['old_credits']:
            continue                                  # credits would not balance
        if not (0.0 <= conf <= 1.0):
            conf = 0.0
        out.append({'old_code': old_code, 'new_codes': picks,
                    'confidence': round(conf, 3),
                    'reason': ' '.join(str(d.get('reason', '')).split())[:200]})
    return out


def advise(batch_pairs: list[dict], use_cache: bool = True) -> dict:
    """batch_pairs: [{old_batch,new_batch,old_code,old_name,old_credits,
                       old_basket,old_sem,candidates}]"""
    if not batch_pairs:
        return {'decisions': {}, 'used_api': False, 'error': None}
    if not available():
        c = _cfg()
        return {'decisions': {}, 'used_api': False,
                'error': 'no API key set (need one of: %s)'
                         % ', '.join(PROVIDERS[k]['env'] for k in ORDER)
                         if not c else 'unavailable'}

    cache = _load_cache()
    todo, decisions = [], {}
    for it in batch_pairs:
        k = _key(it['old_batch'], it['new_batch'], it['old_code'], it['candidates'])
        if use_cache and k in cache:
            hit = cache[k]
            if hit:
                decisions[it['old_code']] = hit
                continue
        todo.append((k, it))

    used_api, error = False, None
    for i in range(0, len(todo), 8):                  # batch to bound cost
        chunk = todo[i:i + 8]
        raw = _call(_build_prompt([it for _, it in chunk]))
        if raw is None:
            error = 'Grok request failed or timed out'
            continue
        used_api = True
        for d in _validate(raw, [it for _, it in chunk]):
            decisions[d['old_code']] = d
        for k, it in chunk:
            cache[k] = decisions.get(it['old_code'])
    with _lock:
        _save_cache()
    return {'decisions': decisions, 'used_api': used_api, 'error': error}


def clear_cache() -> int:
    global _cache
    with _lock:
        n = len(_load_cache())
        _cache = {}
        _save_cache()
    return n


def last_call_at() -> float:
    return _cache.get('__last_call__', 0) if _cache else 0


def mark_called() -> None:
    cache = _load_cache()
    cache['__last_call__'] = time.time()
    _save_cache()
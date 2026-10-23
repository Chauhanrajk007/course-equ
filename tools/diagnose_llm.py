"""Diagnose a provider: shows the real HTTP status and body for one request."""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import llm  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else None
if name == 'credits':
    print('credit balance:', json.dumps(llm.credit_status(force=True)))
    raise SystemExit(0)
for n in ([name] if name else llm.ORDER):
    p = llm.PROVIDERS[n]
    key = (os.environ.get(p['env']) or '').strip()
    print('=== %s (%s)' % (n, p['env']))
    if not key:
        print('    no key set\n')
        continue
    for model in p['models'][:3]:
        body = json.dumps({
            'model': model,
            'messages': [{'role': 'user', 'content': 'Reply with only: {"ping":1}'}],
            'temperature': 0,
            'max_tokens': 1500,
            'response_format': {'type': 'json_object'},
        }).encode()
        h = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
             'User-Agent': llm.UA, 'Accept': 'application/json'}
        if n == 'openrouter':
            h['HTTP-Referer'] = 'http://localhost:5000'
            h['X-Title'] = 'Course Equivalence'
        req = urllib.request.Request(p['url'], data=body, method='POST', headers=h)
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode())
            print('    %-32s OK  %s' % (model, json.dumps(d['choices'][0]
                                                         ['message'])[:110]))
        except urllib.error.HTTPError as e:
            print('    %-32s HTTP %s  %s' % (model, e.code,
                                             e.read().decode()[:200]))
        except Exception as e:                                # noqa: BLE001
            print('    %-32s %s: %s' % (model, type(e).__name__, str(e)[:160]))
    print()
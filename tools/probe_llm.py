"""Live probe for the LLM advisor: checks each configured provider answers."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import llm  # noqa: E402


def probe(name):
    p = llm.PROVIDERS[name]
    if not (os.environ.get(p['env']) or '').strip():
        return '%s: no %s set' % (name, p['env'])
    llm.os.environ['COURSE_EQUIV_PROVIDER'] = name
    for m in p['models']:
        llm.os.environ['COURSE_EQUIV_MODEL'] = m
        cfg = llm._cfg()
        out = llm._call('Reply with only this JSON object: {"ping": 1}',
                       timeout=45)
        if out is not None:
            return ('%s OK  model=%s  response=%s'
                    % (name, m, json.dumps(out)[:80]))
    llm.os.environ.pop('COURSE_EQUIV_PROVIDER', None)
    return '%s: key present but every model failed' % name


def main():
    print('detected:', json.dumps(llm.status()))
    print()
    for n in llm.ORDER:
        print(' ', probe(n))
    llm.os.environ.pop('COURSE_EQUIV_PROVIDER', None)


if __name__ == '__main__':
    main()
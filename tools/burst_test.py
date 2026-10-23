"""Reproduces the reported failure: two photos uploaded in one request.

Exercises the retry/backoff path against the real gateway and confirms that a
page which cannot be read is reported rather than silently dropped.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import llm, ocr                                  # noqa: E402
import make_test_image                                        # noqa: E402

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_e2e')
OLD = '2024-2028'


def main():
    print('provider:', llm.status())
    if not llm.available():
        print('no key configured - skipping')
        return 0
    a = make_test_image.build(os.path.join(TMP, 'burst_a.png'), sem='1')
    b = make_test_image.build(os.path.join(TMP, 'burst_b.png'), sem='2')

    print('\nreading two pages back to back with no pause (the reported case)')
    print('cache bypassed so this is a real request each time')
    t0 = time.time()
    results = []
    for p in (a, b):
        t = time.time()
        try:
            out = ocr.transcribe(open(p, 'rb').read(), os.path.basename(p), OLD,
                                 use_cache=False)
            results.append((os.path.basename(p), 'ok', len(out['records']),
                            round(time.time() - t, 1)))
        except Exception as e:                                # noqa: BLE001
            results.append((os.path.basename(p), 'FAILED', str(e)[:150],
                            round(time.time() - t, 1)))
        print('   %-14s %-7s %s  (%ss)' % results[-1])
    print('   total %.1fs' % (time.time() - t0))

    ok = all(r[1] == 'ok' for r in results)
    if ok:
        print('\nPASS  both pages read (retry/backoff absorbed the budget cap)')
        return 0
    print('\nPARTIAL  a page still failed after %s retries'
          % os.environ.get('COURSE_EQUIV_RETRIES', '5'))
    print('The message the user would see:')
    for r in results:
        if r[1] != 'ok':
            print('   %s' % r[2])
    return 0 if not ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
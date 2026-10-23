# Course Equivalence & Credit Mapping

Generates the **Annexure A** course-equivalence report used by Presidency
University when a student takes a break and is re-admitted into a later batch.

Upload a report card, pick the admission and readmission batches, review the
proposed mapping, override anything you disagree with, and download the signed
PDF.

---

## What you can upload

| Input | How it is read |
|---|---|
| `.docx`, `.xlsx`, `.csv`, `.txt` | parsed directly from the table — no AI needed |
| `.pdf` | table extraction, then the same parser — no AI needed |
| `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.tif` | read by a vision model — **needs AI credit** |
| **Enter manually** | the course list is generated from the PRC; you tick what was passed — **never needs AI** |

**Nothing is mapped straight from a file or a photo.** Whatever was read is
shown on a *Check what was read* screen with an editable table — correct a
misread code, grade or semester, untick anything to ignore — and only then does
the mapping run. For a photo, the original pages are shown underneath so you can
compare side by side.

Rows the reader is unsure about are highlighted: a code that is not in the
admission PRC, a missing grade, a missing semester, or two pages that disagree.

### Several pages at once

Select all the pages in one go. They are merged by course code, and each row
records which page it came from. The same course appearing twice keeps the
**later** grade and is flagged — that is how a summer-term or make-up attempt
supersedes the original. You can attach further pages afterwards without
re-reading the ones that worked.

### When the AI is unavailable

Photo reading stops working if the key is missing or the account is out of
credit. That does **not** take the app down:

- `.docx` / `.xlsx` / `.csv` / `.pdf` still work.
- **Enter the courses manually** still works — it needs no AI at all, and the
  course list comes from the PRC itself, so you only tick what was completed and
  type the grades.
- The homepage shows an out-of-credit banner instead of letting you discover it
  through a failed upload.

### One-liner (skip the venv if packages are already installed)

```powershell
cd "$HOME\course-equivalence"; python app.py
```

### Linux / macOS

```bash
cd ~/course-equivalence
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## Enabling the advisor (optional)

The app is fully functional without it. The advisor is only consulted for
courses the rules cannot place confidently — in practice professional and open
electives, where a student picks arbitrary subjects.

Any OpenAI-compatible provider works. Set **one** key:

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-..."   # currently working here
# $env:GROQ_API_KEY     = "gsk_..."
# $env:XAI_API_KEY      = "xai-..."
```

To persist it for your account (registry, not a file):

```powershell
[Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', 'sk-or-v1-...', 'User')
```

Then restart the terminal and run the app.

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | – | Enables the advisor via OpenRouter. |
| `GROQ_API_KEY` | – | Enables the advisor via Groq. |
| `XAI_API_KEY` | – | Enables the advisor via xAI direct. |
| `COURSE_EQUIV_PROVIDER` | auto | Force `xai`, `openrouter` or `groq`. Auto picks the first key found, in that order. |
| `COURSE_EQUIV_MODEL` | provider default | e.g. `x-ai/grok-4.3`. |
| `COURSE_EQUIV_MAX_TOKENS` | `2000` | Keep this capped. Some gateways reject requests whose `max_tokens` ceiling exceeds the account balance. |
| `COURSE_EQUIV_RETRIES` | `5` | Retries with exponential backoff. Gateways cap work in flight, so a burst of images can be rejected and then succeeds on retry. |
| `PAGE_GAP` | `1.5` | Seconds between pages. Keeps image reads sequential. |
| `SECRET_KEY` | random each start | Set it so sessions survive a restart. |
| `PORT` | `5000` | HTTP port. |

**Check the balance before relying on it.** A present key does not mean a working
key — an account with no credit left fails every request with `HTTP 402`:

```powershell
python tools\diagnose_llm.py credits
```

Top up at <https://openrouter.ai/settings/credits>.

Check what is connected before you rely on it:

```powershell
python tools\diagnose_llm.py          # real HTTP status per provider
python tools\advisor_test.py          # live end-to-end advisor run
```

Advisor answers are cached in `data/llm_cache.json`, keyed by the exact
candidate list, so re-running a case costs nothing.

> **Note on the Groq key.** It returns `HTTP 403 / error code 1010`, which is
> Cloudflare blocking this machine's requests to `api.groq.com`, not a bad key.
> OpenRouter is the working path today.

---

## Credits in excess

A readmitted student may legitimately end up holding **more** credits than the
PRC requires — for instance when the old curriculum ran a 3-credit programming
course and the new one runs it as a 2-credit theory plus a 2-credit lab.

The engine does not clamp this away. It reports:

- **Credits in excess of the requirement** — per basket, and in total.
- **Courses that may be skipped** — later-semester courses in the same basket
  that the surplus fully covers, in the order the student meets them.
- **Stranded surplus** — surplus in a basket with no later course to absorb it.
  Basket minima are strict, so these credits cannot be spent elsewhere; the
  Board of Studies may decide otherwise.

Skipping a course is an academic decision. The list is a suggestion from the
engine and pre-requisites are not evaluated.

`B + C + D + E + F` will equal `A` exactly when there is no surplus. When the
mapping produces more credits than the PRC asks for, `F` floors at 0 and the
total reads higher than `A` — which the template's note allows (`≥ A`).

---

## How the mapping is decided

The rule engine owns every credit decision. The model never sets credits.

| Step | Method |
|---|---|
| 0 | Manual override chosen by the HoD in the review screen |
| 1 | Identical course code **and** identical credits |
| 2 | Equivalent title at exactly equal credits, same basket |
| 3 | Equivalent title where the new PRC splits theory and lab |
| 4 | Equivalent title where the new course carries fewer credits — the shortfall is carried into Table IV |
| 5 | Same department and basket, equal credits |
| 6 | **Grok advisor**, offered only what is still unmatched and only a shortlist of candidates. Its answer is discarded unless the credits sum exactly |

Whatever is left over is reported, never silently dropped:

| Table | Contents |
|---|---|
| I | Semester-wise mapping, new PRC ↔ old PRC |
| II | F / NP graded courses |
| III | Passed courses with no counterpart (exemptions) |
| IV | Additional courses needed to make the credits balance |
| V | Courses to strike off the transcript |

Credits always reconcile: `B + C + D + E + F == A`, where `A` is the PRC total
(160 credits).

---

## Adding a new batch (e.g. 2027-2031)

1. Drop the official PRC `.docx` next to the others in `Downloads`.
2. Add it to `FILES` in `tools/build_prc_db.py`.
3. Rebuild:

```powershell
.\.venv\Scripts\python.exe tools\build_prc_db.py
```

Nothing else changes — the picker, engine and PDF all read from
`data/prc_db.json`. Update `SRC` in that file if the PRC files move.

---

## Testing

```powershell
# engine + PDF + all 10 batch-pair combinations
.\.venv\Scripts\python.exe tools\e2e_test.py

# full web flow: upload -> confirm -> review -> override -> PDF -> JSON
.\.venv\Scripts\python.exe tools\web_test.py

# photo reading end to end (needs an AI key)
.\.venv\Scripts\python.exe tools\make_test_image.py
.\.venv\Scripts\python.exe tools\advisor_test.py

# replay the siddarth123 sample and write tools\sample_output.pdf
.\.venv\Scripts\python.exe tools\replay_sample.py
```

`e2e_test.py` asserts the invariants that matter: credits reconcile exactly,
no new course is mapped twice, every partial match carries an additional
course, and each table's rows sum to its stated total.

---

## Layout

```
app.py                  Flask routes
data/prc_db.json        course database extracted from the 5 official PRCs
engine/
  prc.py                read-only access to the PRC database
  transcript.py         report-card parsing (.docx/.xlsx/.csv/.pdf)
  ocr.py                photo/scan transcription via a vision model
  mapping.py            the equivalence engine
  llm.py                advisor (optional, cached, strictly validated)
  report.py             Annexure A PDF
tools/
  build_prc_db.py       regenerates data/prc_db.json from the .docx files
  e2e_test.py           engine tests
  web_test.py           web tests
  advisor_test.py       live advisor run on ambiguous electives
  diagnose_llm.py       real HTTP status for each provider
  make_test_image.py    builds a realistic scanned report card for testing
  replay_sample.py      the siddarth123 sample
```

## Notes and limits

- **A photo of a report card is read by a vision model, so it can misread a
  digit.** The confirm screen exists for that: nothing is mapped until someone
  has looked at it. Treat it as mandatory for official use.
- Large scans are downscaled to 2200px before sending; very dense or rotated
  photos do worse, so straighten and fill the frame when photographing.
- Cases live in memory and are lost on restart; set `SECRET_KEY` and put a real
  store behind `CASES` before running this for a whole department.
- `data/ocr_cache.json` and `data/llm_cache.json` are keyed by content, so the
  same photo or case never bills twice. Delete a file there to force a re-read.
- The 2022 and 2023 PRCs use the older basket names (School Core, Program Core,
  Discipline Elective, Open Elective). Those are normalised to the 8-basket
  scheme by course-code department so old students can be mapped forward.
- The review screen is the approval step. Equivalences are proposals until the
  Board of Studies signs off.
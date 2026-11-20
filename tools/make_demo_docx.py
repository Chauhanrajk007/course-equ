"""Builds clean .docx report cards for all 5 sample students.

This enables instantaneous (<0.05s) demonstration of any student case
without requiring external AI vision calls or waiting on network latency.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docx
from engine import prc
from engine.transcript import parse_transcript

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'demo_report_cards')
os.makedirs(OUT, exist_ok=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, 'data', 'ocr_cache.json')

with open(CACHE_PATH, 'r', encoding='utf-8') as f:
    cache = json.load(f)

students = [
    {
        'file': 'Kunduru_Harsha_Vardhan_Reddy_20221CAI0014_Report_Card.docx',
        'name': 'KUNDURU HARSHA VARDHAN REDDY',
        'roll': '20221CAI0014',
        'prog': 'B.Tech - Computer Science and Engineering (AI and ML)',
        'old_batch': '2022-2026',
        'new_batch': '2023-2027',
        'last_sem': 4,
    },
    {
        'file': 'Ranjith_N_20221CAI0160_Report_Card.docx',
        'name': 'RANJITH N',
        'roll': '20221CAI0160',
        'prog': 'B.Tech - Computer Science and Engineering (AI and ML)',
        'old_batch': '2022-2026',
        'new_batch': '2023-2027',
        'last_sem': 4,
    },
    {
        'file': 'Chaitanya_Reddy_V_20231CAI0045_Report_Card.docx',
        'name': 'CHAITANYA REDDY V',
        'roll': '20231CAI0045',
        'prog': 'B.Tech - Computer Science and Engineering (AI and ML)',
        'old_batch': '2023-2027',
        'new_batch': '2024-2028',
        'last_sem': 4,
    },
    {
        'file': 'Pranav_S_20231CAI0033_Report_Card.docx',
        'name': 'PRANAV S',
        'roll': '20231CAI0033',
        'prog': 'B.Tech - Computer Science and Engineering (AI and ML)',
        'old_batch': '2023-2027',
        'new_batch': '2024-2028',
        'last_sem': 4,
    },
    {
        'file': 'Pavithra_RS_20241CAI0205_Report_Card.docx',
        'name': 'PAVITHRA RS',
        'roll': '20241CAI0205',
        'prog': 'B.Tech - Computer Science and Engineering (AI and ML)',
        'old_batch': '2024-2028',
        'new_batch': '2025-2029',
        'last_sem': 2,
    },
]

def main():
    prog_key = 'CAI'
    for s in students:
        roll = s['roll']
        name = s['name']
        old_b = s['old_batch']

        courses_by_code = {}
        for k, v in cache.items():
            ident = str(v.get('identity', {})).upper()
            if roll in ident or (name.split()[0] in ident and name.split()[-1] in ident):
                sem_hint = v.get('identity', {}).get('semester')
                for r in v.get('rows', []):
                    code = r.get('code')
                    if not code:
                        continue
                    sem = r.get('semester') or sem_hint
                    gr = r.get('grade')
                    cr = r.get('credits')
                    nm = r.get('name')

                    # Enrich from official PRC grid
                    prc_course = prc.courses(old_b, prog_key).get(code)
                    if prc_course:
                        if not nm or len(nm) < 3:
                            nm = prc_course.get('name')
                        if not cr:
                            cr = prc_course.get('C')
                        if not sem:
                            sem = prc_course.get('sem')

                    if code in courses_by_code:
                        old_rec = courses_by_code[code]
                        if gr and gr != 'F' and (old_rec.get('grade') == 'F' or not old_rec.get('grade')):
                            courses_by_code[code] = {
                                'code': code, 'name': nm, 'credits': cr, 'grade': gr,
                                'semester': sem or old_rec.get('semester')
                            }
                    else:
                        courses_by_code[code] = {
                            'code': code, 'name': nm, 'credits': cr, 'grade': gr, 'semester': sem
                        }

        # Sort courses by semester then code
        course_list = sorted(
            courses_by_code.values(),
            key=lambda x: (int(x['semester']) if x['semester'] and str(x['semester']).isdigit() else 99, x['code'])
        )

        doc = docx.Document()
        doc.add_heading('PRESIDENCY UNIVERSITY', level=1)
        doc.add_paragraph('Statement of Marks / Academic Record')
        doc.add_paragraph(f'Name of the Student: {name}')
        doc.add_paragraph(f'Roll Number: {roll}')
        doc.add_paragraph(f'Program: {s["prog"]}')
        doc.add_paragraph(f'Admission Batch: {s["old_batch"]}')
        doc.add_paragraph(f'Last Semester Attended: {s["last_sem"]}')

        table = doc.add_table(rows=1, cols=6)
        table.style = 'Table Grid'
        hdr = table.rows[0].cells
        hdr[0].text = 'Sl.No'
        hdr[1].text = 'Course Code'
        hdr[2].text = 'Course Name'
        hdr[3].text = 'Credits'
        hdr[4].text = 'Grade'
        hdr[5].text = 'Semester'

        for i, c in enumerate(course_list, start=1):
            row = table.add_row().cells
            row[0].text = str(i)
            row[1].text = str(c.get('code') or '')
            row[2].text = str(c.get('name') or '')
            row[3].text = str(c.get('credits') or '')
            row[4].text = str(c.get('grade') or '')
            row[5].text = str(c.get('semester') or '')

        out_path = os.path.join(OUT, s['file'])
        doc.save(out_path)

        with open(out_path, 'rb') as f:
            parsed = parse_transcript(s['file'], f.read())
        print(f'Created {s["file"]}: {len(parsed["records"])} courses parsed cleanly ({parsed["identity"].get("name")})')

if __name__ == '__main__':
    main()

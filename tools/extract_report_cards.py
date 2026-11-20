"""Extract actual student grade card pages from raw multi-page scanned PDF packages.

Saves:
1. Clean student report card PDFs containing only the grade cards.
2. High-resolution PNG images of each semester's grade card ready to upload and test.
"""
from __future__ import annotations

import os
import pypdfium2 as pdfium

STUDENTS = {
    'Pavithra_RS_20241CAI0205': {
        'pdf': 'new data to train/Pavithra RS_20241CAI0205.pdf',
        'pages': [19, 20, 21, 22],
        'admission_batch': '2024-2028',
        'readmit_batch': '2025-2029',
        'program': 'CAI'
    },
    'Chaitanya_Reddy_V_20231CAI0045': {
        'pdf': 'new data to train/Chaitanya Reddy V_20231CAI0045.pdf',
        'pages': [21, 22, 23, 24, 25, 26, 27, 28],
        'admission_batch': '2023-2027',
        'readmit_batch': '2024-2028',
        'program': 'CAI'
    },
    'Pranav_S_20231CAI0033': {
        'pdf': 'new data to train/Pranav S_20231CAI0033.pdf',
        'pages': [23, 24, 25, 26, 27, 28, 29, 30, 31],
        'admission_batch': '2023-2027',
        'readmit_batch': '2024-2028',
        'program': 'CAI'
    },
    'Kunduru_Harsha_Vardhan_Reddy_20221CAI0014': {
        'pdf': 'new data to train/7.KUNDURU HARSHA VARDHAN REDDY _20221CAI0014_CE.pdf',
        'pages': [16, 17, 18, 19, 20, 21, 22],
        'admission_batch': '2022-2026',
        'readmit_batch': '2023-2027',
        'program': 'CAI'
    },
    'Ranjith_N_2022CAI0160': {
        'pdf': 'new data to train/10.RANJITH N_2022CAI0160_CE NEW.pdf',
        'pages': list(range(16, 30)),
        'admission_batch': '2022-2026',
        'readmit_batch': '2023-2027',
        'program': 'CAI'
    }
}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_base = os.path.join(root, 'extracted_report_cards')
    os.makedirs(out_base, exist_ok=True)

    manifest = []
    for name, info in STUDENTS.items():
        src_path = os.path.join(root, info['pdf'])
        if not os.path.isfile(src_path):
            print(f'Warning: source file not found: {src_path}')
            continue

        student_dir = os.path.join(out_base, name)
        os.makedirs(student_dir, exist_ok=True)

        src_doc = pdfium.PdfDocument(src_path)
        dest_doc = pdfium.PdfDocument.new()
        dest_doc.import_pages(src_doc, [p - 1 for p in info['pages']])
        dest_pdf_path = os.path.join(out_base, f'{name}_Report_Card.pdf')
        dest_doc.save(dest_pdf_path)
        dest_doc.close()

        img_paths = []
        for idx, p_num in enumerate(info['pages'], 1):
            page = src_doc[p_num - 1]
            img = page.render(scale=2.0).to_pil()
            img_filename = f'Semester_Grade_Card_{idx}.png'
            img_path = os.path.join(student_dir, img_filename)
            img.save(img_path, 'PNG')
            img_paths.append(img_filename)

        src_doc.close()
        manifest.append({
            'student': name,
            'pdf': os.path.basename(dest_pdf_path),
            'page_count': len(info['pages']),
            'admission_batch': info['admission_batch'],
            'readmit_batch': info['readmit_batch'],
            'program': info['program'],
            'images': img_paths
        })
        print(f'[OK] Extracted {name}: {len(info["pages"])} grade card pages -> {dest_pdf_path}')

    import json
    with open(os.path.join(out_base, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    print(f'\nFinished extracting all student report cards into: {out_base}')


if __name__ == '__main__':
    main()

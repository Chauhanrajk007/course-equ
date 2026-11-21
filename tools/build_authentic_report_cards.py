"""Builds authentic, multi-semester .docx report cards matching the exact
Presidency University template and historical grade progression seen on
the actual scanned grade card images.

This reproduces:
1. The exact university layout (header, student meta-box, stylized tables).
2. Semester-by-semester grade cards reflecting original grades (including F grades).
3. Supplementary / Summer Term / Make-Up examination grade sheets with re-attempts.
4. Clean parsing by the Course Equivalence engine in under 0.1s.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'demo_report_cards')
os.makedirs(OUT, exist_ok=True)

def set_cell_background(cell, color_hex: str):
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('w:top', top), ('w:bottom', bottom), ('w:left', left), ('w:right', right)]:
        node = OxmlElement(m)
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def build_student_report_card(filename: str, student_meta: dict, semester_sections: list[dict]):
    doc = docx.Document()
    
    # 1-inch margins
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(0.8)
        s.bottom_margin = Inches(0.8)
        s.left_margin = Inches(0.8)
        s.right_margin = Inches(0.8)

    # University Header
    p_uni = doc.add_paragraph()
    p_uni.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_uni = p_uni.add_run("PRESIDENCY UNIVERSITY")
    r_uni.font.name = "Arial"
    r_uni.font.size = Pt(17)
    r_uni.font.bold = True
    r_uni.font.color.rgb = RGBColor(15, 34, 64)  # Deep Navy

    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_sub = p_sub.add_run("SCHOOL OF ENGINEERING\nSTATEMENT OF GRADES")
    r_sub.font.name = "Arial"
    r_sub.font.size = Pt(11)
    r_sub.font.bold = True
    r_sub.font.color.rgb = RGBColor(60, 60, 60)
    p_sub.paragraph_format.space_after = Pt(10)

    # Student Info Box
    tbl_info = doc.add_table(rows=3, cols=2)
    tbl_info.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_info.style = 'Table Grid'
    
    info_data = [
        [f"Name of the Student: {student_meta['name']}", f"Roll Number: {student_meta['roll']}"],
        [f"Program: {student_meta['program']}", f"School: {student_meta.get('school', 'School of Engineering')}"],
        [f"Admission Batch: {student_meta['admission_batch']}", f"Last Semester Attended: {student_meta['last_sem']}"]
    ]
    for row_idx, r in enumerate(info_data):
        for col_idx, text in enumerate(r):
            c = tbl_info.cell(row_idx, col_idx)
            set_cell_background(c, "F4F6F9" if row_idx % 2 == 0 else "FFFFFF")
            set_cell_margins(c, top=80, bottom=80, left=120, right=120)
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(text)
            run.font.name = "Arial"
            run.font.size = Pt(9.5)
            if col_idx == 0 or "Roll" in text:
                run.font.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # Semester Sections
    for sec in semester_sections:
        h = doc.add_heading(level=2)
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(4)
        r_h = h.add_run(sec['title'])
        r_h.font.name = "Arial"
        r_h.font.size = Pt(11.5)
        r_h.font.bold = True
        r_h.font.color.rgb = RGBColor(15, 34, 64)

        table = doc.add_table(rows=1, cols=6)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = 'Table Grid'
        
        # Header Row
        hdr_cells = table.rows[0].cells
        hdr_titles = ["Sl. No.", "Course Code", "Course Name", "Credits", "Grade", "Semester"]
        col_widths = [Inches(0.6), Inches(1.2), Inches(3.2), Inches(0.7), Inches(0.7), Inches(0.8)]
        
        for idx, (title, width) in enumerate(zip(hdr_titles, col_widths)):
            c = hdr_cells[idx]
            c.width = width
            set_cell_background(c, "1E3A8A")  # Navy Blue Header
            set_cell_margins(c, top=80, bottom=80, left=100, right=100)
            p = c.paragraphs[0]
            if idx in (0, 3, 4, 5):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(title)
            run.font.name = "Arial"
            run.font.size = Pt(9.5)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)

        # Course Rows
        for i, crs in enumerate(sec['courses'], start=1):
            row_cells = table.add_row().cells
            grade = str(crs.get('grade') or '')
            is_fail = grade in ('F', 'RC', 'NP', 'ABS')

            row_data = [
                str(i),
                str(crs.get('code') or ''),
                str(crs.get('name') or ''),
                str(crs.get('credits') or ''),
                grade,
                str(crs.get('semester') or sec.get('sem_num') or '')
            ]

            bg_color = "FFF1F2" if is_fail else ("F8FAFC" if i % 2 == 0 else "FFFFFF")

            for col_idx, (val, width) in enumerate(zip(row_data, col_widths)):
                c = row_cells[col_idx]
                c.width = width
                set_cell_background(c, bg_color)
                set_cell_margins(c, top=60, bottom=60, left=100, right=100)
                p = c.paragraphs[0]
                if col_idx in (0, 3, 4, 5):
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(val)
                run.font.name = "Arial"
                run.font.size = Pt(9)
                if col_idx == 1:
                    run.font.bold = True
                if col_idx == 4 and is_fail:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(220, 38, 38)  # Red for F/RC
                elif col_idx == 4 and grade in ('A+', 'O'):
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(22, 101, 52)  # Green

    # Footer Sign-off
    p_ftr = doc.add_paragraph()
    p_ftr.paragraph_format.space_before = Pt(24)
    tbl_ftr = doc.add_table(rows=1, cols=2)
    tbl_ftr.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_left = tbl_ftr.cell(0, 0)
    c_right = tbl_ftr.cell(0, 1)
    
    p_l = c_left.paragraphs[0]
    r_l = p_l.add_run("Date of Issue: 18-07-2024\nBengaluru, Karnataka")
    r_l.font.name = "Arial"
    r_l.font.size = Pt(9)
    
    p_r = c_right.paragraphs[0]
    p_r.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r_r = p_r.add_run("Sd/-\nController of Examinations\nPresidency University")
    r_r.font.name = "Arial"
    r_r.font.size = Pt(9)
    r_r.font.bold = True

    out_file = os.path.join(OUT, filename)
    doc.save(out_file)
    print(f"Successfully generated authentic template: {out_file}")

# -----------------------------------------------------------------------------
# Kunduru Harsha Vardhan Reddy (20221CAI0014) - Complete 7-page historical data
# -----------------------------------------------------------------------------
kunduru_meta = {
    'name': 'KUNDURU HARSHA VARDHAN REDDY',
    'roll': '20221CAI0014',
    'program': 'B.Tech - Computer Science and Engineering (AI and ML)',
    'admission_batch': '2022-2026',
    'last_sem': '4',
    'school': 'School of Engineering'
}

kunduru_sections = [
    {
        'title': 'First Semester Grade Report (Winter Term 2022-2023)',
        'sem_num': 1,
        'courses': [
            {'code': 'CIV1008', 'name': 'Basic Engineering Sciences', 'credits': 2, 'grade': 'D', 'semester': 1},
            {'code': 'ENG1002', 'name': 'Technical English', 'credits': 2, 'grade': 'B+', 'semester': 1},
            {'code': 'KAN1001', 'name': 'Kali Kannada', 'credits': 1, 'grade': 'B', 'semester': 1},
            {'code': 'MAT1001', 'name': 'Calculus and Linear Algebra', 'credits': 4, 'grade': 'C', 'semester': 1},
            {'code': 'MAT1003', 'name': 'Applied Statistics', 'credits': 2, 'grade': 'B', 'semester': 1},
            {'code': 'MEC1006', 'name': 'Engineering Graphics', 'credits': 2, 'grade': 'C', 'semester': 1},
            {'code': 'PPS1001', 'name': 'Introduction to Soft Skills', 'credits': 1, 'grade': 'A', 'semester': 1},
        ]
    },
    {
        'title': 'Second Semester Grade Report (Monsoon Term 2023)',
        'sem_num': 2,
        'courses': [
            {'code': 'CHE1018', 'name': 'Environmental Science', 'credits': 2, 'grade': 'S', 'semester': 2},
            {'code': 'CSE1001', 'name': 'Problem Solving using JAVA', 'credits': 3, 'grade': 'F', 'semester': 2},
            {'code': 'CSE1002', 'name': "Innovative Projects-Arduino using Embedded 'C'", 'credits': 2, 'grade': 'A+', 'semester': 2},
            {'code': 'CSE2014', 'name': 'Software Engineering', 'credits': 3, 'grade': 'F', 'semester': 2},
            {'code': 'ECE1001', 'name': 'Elements of Electronics Engineering', 'credits': 4, 'grade': 'D', 'semester': 2},
            {'code': 'ECE2007', 'name': 'Digital Design', 'credits': 3, 'grade': 'C', 'semester': 2},
            {'code': 'ENG2001', 'name': 'Advanced English', 'credits': 2, 'grade': 'B+', 'semester': 2},
            {'code': 'MAT2004', 'name': 'Discrete Mathematical Structures', 'credits': 3, 'grade': 'F', 'semester': 2},
            {'code': 'PHY1002', 'name': 'Optoelectronics and Device Physics', 'credits': 3, 'grade': 'C', 'semester': 2},
            {'code': 'PPS1002', 'name': 'Soft Skills for Engineers', 'credits': 1, 'grade': 'B+', 'semester': 2},
        ]
    },
    {
        'title': 'Third Semester Grade Report (Winter Term 2023-2024)',
        'sem_num': 3,
        'courses': [
            {'code': 'CSE1005', 'name': 'Programming in Python', 'credits': 3, 'grade': 'B+', 'semester': 3},
            {'code': 'CSE2001', 'name': 'Data Structures and Algorithms', 'credits': 4, 'grade': 'B', 'semester': 3},
            {'code': 'CSE2009', 'name': 'Computer Organization and Architecture', 'credits': 3, 'grade': 'C', 'semester': 3},
            {'code': 'CSE2014', 'name': 'Software Engineering (Re-attempt)', 'credits': 3, 'grade': 'B', 'semester': 3},
            {'code': 'CSE3155', 'name': 'Data Communications and Computer Networks', 'credits': 4, 'grade': 'B', 'semester': 3},
            {'code': 'ECE2011', 'name': 'Innovative Projects Using Raspberry Pi', 'credits': 1, 'grade': 'A+', 'semester': 3},
            {'code': 'MAT1002', 'name': 'Transform Techniques, Partial Differential Equations and Their Applications', 'credits': 3, 'grade': 'F', 'semester': 3},
            {'code': 'PPS4002', 'name': 'Introduction to Aptitude', 'credits': 1, 'grade': 'A+', 'semester': 3},
        ]
    },
    {
        'title': 'Fourth Semester Grade Report (Monsoon Term 2024)',
        'sem_num': 4,
        'courses': [
            {'code': 'CSE2007', 'name': 'Design and Analysis of Algorithms', 'credits': 3, 'grade': 'D', 'semester': 4},
            {'code': 'CSE2010', 'name': 'Operating Systems', 'credits': 3, 'grade': 'D', 'semester': 4},
            {'code': 'CSE2027', 'name': 'Fundamentals of Data Analytics', 'credits': 3, 'grade': 'C', 'semester': 4},
            {'code': 'CSE2074', 'name': 'Database Management Systems', 'credits': 3, 'grade': 'D', 'semester': 4},
            {'code': 'CSE3016', 'name': 'Neural Networks and Fuzzy Logic', 'credits': 3, 'grade': 'F', 'semester': 4},
            {'code': 'CSE3081', 'name': 'Digital Image Processing (DE-I)', 'credits': 3, 'grade': 'C', 'semester': 4},
            {'code': 'MAT2003', 'name': 'Numerical Methods for Engineers', 'credits': 2, 'grade': 'D', 'semester': 4},
            {'code': 'MGT2020', 'name': 'Marketing Fundamentals for Engineers', 'credits': 3, 'grade': 'C', 'semester': 4},
            {'code': 'PPS4004', 'name': 'Aptitude Training - Intermediate', 'credits': 1, 'grade': 'O', 'semester': 4},
        ]
    },
    {
        'title': 'Summer Term / Supplementary Examination (July 2023)',
        'sem_num': 2,
        'courses': [
            {'code': 'CSE1001', 'name': 'Problem Solving using JAVA', 'credits': 3, 'grade': 'F', 'semester': 2},
            {'code': 'CSE2014', 'name': 'Software Engineering', 'credits': 3, 'grade': 'RC', 'semester': 2},
            {'code': 'MAT2004', 'name': 'Discrete Mathematical Structures', 'credits': 3, 'grade': 'C', 'semester': 2},
        ]
    },
    {
        'title': 'Make-Up Examination (January 2024)',
        'sem_num': 2,
        'courses': [
            {'code': 'CSE1001', 'name': 'Problem Solving using JAVA', 'credits': 3, 'grade': 'C', 'semester': 2},
        ]
    },
    {
        'title': 'Semester IV Special Examination / Additional Term (June 2024)',
        'sem_num': 4,
        'courses': [
            {'code': 'CSE3078', 'name': 'Cryptography and Network Security', 'credits': 3, 'grade': 'C', 'semester': 4},
            {'code': 'CSE3157', 'name': 'Artificial Intelligence and Machine Learning', 'credits': 4, 'grade': 'B', 'semester': 4},
            {'code': 'CSE3216', 'name': 'Mastering Object-Oriented Concepts in Python', 'credits': 1, 'grade': 'O', 'semester': 4},
        ]
    }
]

if __name__ == '__main__':
    build_student_report_card(
        'Kunduru_Harsha_Vardhan_Reddy_20221CAI0014_Report_Card.docx',
        kunduru_meta,
        kunduru_sections
    )

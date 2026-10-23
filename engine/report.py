"""Annexure-A PDF generation.

Reproduces the university's "Course Equivalence and Credit Mapping - Transfer
Case" template: header, student particulars, Table I (semester-wise mapping),
Tables II-V, the basket-wise position, the Summary block with the
"(B + C + D + E + F) >= A" check, the signature block and the undertaking letter.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

PAGE = landscape(A4)                      # the mapping tables are very wide
M = 10 * mm
GREY = colors.HexColor('#f0f0f0')
LINE = colors.HexColor('#9a9a9a')
ACCENT = colors.HexColor('#1f3864')

FS = 6.6                                # body table font


def _s(name, size, leading=None, **kw):
    return ParagraphStyle(name, fontName=kw.pop('font', 'Helvetica'),
                          fontSize=size, leading=leading or size + 1.6, **kw)


ST = {
    'h1': _s('h1', 11, 14, font='Helvetica-Bold', alignment=TA_CENTER,
             textColor=ACCENT),
    'h2': _s('h2', 8.4, 10.5, font='Helvetica-Bold', spaceBefore=4,
             spaceAfter=3),
    'body': _s('body', 7.4, 9.6, alignment=TA_JUSTIFY),
    'cell': _s('cell', FS, FS + 1.3),
    'cellb': _s('cellb', FS, FS + 1.3, font='Helvetica-Bold'),
    'cellc': _s('cellc', FS, FS + 1.3, alignment=TA_CENTER),
    'note': _s('note', 6.2, 7.6),
    'hdr': _s('hdr', FS, FS + 1.3, font='Helvetica-Bold', alignment=TA_CENTER),
    'sig': _s('sig', 7.4, 9.6),
}


def P(txt, st='cell'):
    return Paragraph('' if txt is None else str(txt), ST[st])


def _sp(v):
    return '' if v is None else str(v)


class Report:
    def __init__(self, result: dict, student: dict):
        self.r = result
        self.s = student or {}

    # ------------------------------------------------------------ header
    def _chrome(self, canvas, doc):
        canvas.saveState()
        w, h = PAGE
        canvas.setFont('Helvetica-Bold', 7.4)
        canvas.setFillColor(ACCENT)
        canvas.drawString(M, h - 9 * mm, 'PRESIDENCY UNIVERSITY')
        canvas.setFont('Helvetica', 7)
        canvas.drawRightString(w - M, h - 9 * mm,
                               'Office of the Dean - Academics   EF-2')
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(M, h - 10.5 * mm, w - M, h - 10.5 * mm)
        canvas.setFont('Helvetica', 6.4)
        canvas.drawString(M, 6 * mm,
                          'Annexure - A  |  Course Equivalence and Credit Mapping '
                          '- Transfer Case')
        canvas.drawRightString(w - M, 6 * mm, 'Page %d' % canvas.getPageNumber())
        canvas.restoreState()

    # ------------------------------------------------------------- build
    def build(self) -> bytes:
        buf = io.BytesIO()
        doc = BaseDocTemplate(buf, pagesize=PAGE,
                              leftMargin=M, rightMargin=M,
                              topMargin=14 * mm, bottomMargin=11 * mm,
                              title='Course Equivalence Report',
                              author='Presidency University')
        frame = Frame(M, 11 * mm, PAGE[0] - 2 * M, PAGE[1] - 25 * mm, id='f')
        doc.addPageTemplates([PageTemplate(id='p', frames=[frame],
                                           onPage=self._chrome)])
        doc.build(self._story())
        return buf.getvalue()

    def _story(self):
        st = [Paragraph('Annexure &ndash; A', ST['h1']),
              Paragraph('Course Equivalence and Credit Mapping &ndash; Transfer Case',
                        ST['h1']),
              Spacer(1, 3 * mm),
              self._particulars(),
              Spacer(1, 3 * mm),
              Paragraph('Course Mapping: Semester-wise (Only up to the number of '
                        'semesters completed by the student at the previous '
                        'Institution)', ST['h2'])]
        st += self._table1()
        st.append(Paragraph('* ET: End-Term;&nbsp;&nbsp; ST: Summer Term;&nbsp;&nbsp;'
                            ' MU: Make-Up Examinations', ST['note']))
        st.append(Spacer(1, 2.5 * mm))
        st += self._table2()
        st += self._table3()
        st += self._table4()
        st += self._table5()
        st += self._surplus()
        st += self._basket()
        st += self._summary()
        st += self._signatures()
        st.append(PageBreak())
        st += self._undertaking()
        return st

    # -------------------------------------------------------- particulars
    def _particulars(self):
        s, r = self.s, self.r
        rows = [
            ['Name of the Student', s.get('name', '')],
            ['Roll Number', s.get('roll_no', '')],
            ['Program', s.get('program') or r['program']],
            ['Name of the previous institution',
             s.get('previous_institution')
             or 'Presidency University (same institution - re-admission)'],
            ['Admission Batch and Last Semester attended',
             '%s , %s Semester' % (self._old_label(s), s.get('last_sem', ''))],
            ['Batch and Semester of Admission at Presidency University',
             '%s , %s Semester' % (self._new_label(s), s.get('readmit_sem', ''))],
        ]
        t = Table([[P(a, 'cellb'), P(b)] for a, b in rows],
                  colWidths=[70 * mm, PAGE[0] - 2 * M - 70 * mm])
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.4, LINE),
            ('BACKGROUND', (0, 0), (0, -1), GREY),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 2.2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.2),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ]))
        return t

    def _old_label(self, s):
        return s.get('admission_batch') or self.r['old_batch']

    def _new_label(self, s):
        return s.get('readmission_batch') or self.r['new_batch']

# ------------------------------------------------------------ Table I
    def _table1(self):
        nb, ob = self._new_label(self.s), self._old_label(self.s)
        head = [
            [P('Semester', 'hdr'),
             P('Courses as per the New (Readmitted) PRC (%s)' % nb, 'hdr'),
             P('', 'hdr'), P('', 'hdr'), P('', 'hdr'), P('', 'hdr'), P('', 'hdr'),
             P('', 'hdr'),
             P('Equivalent Courses that can be mapped as per the curriculum of the '
               'previous institution in which the student studied (%s)' % ob, 'hdr'),
             P('', 'hdr'), P('', 'hdr'), P('', 'hdr'), P('', 'hdr'), P('', 'hdr'),
             P('', 'hdr'),
             P('Semester &amp; Month - Year of Passing (ET/ST/MU)', 'hdr')],
            [P('', 'cellc'),
             P('Course Code', 'hdr'), P('Course Name', 'hdr'),
             P('Credit Structure (L-T-P-C)', 'hdr'), P('', 'cellc'),
             P('', 'cellc'), P('', 'cellc'), P('Course Basket', 'hdr'),
             P('Course Code', 'hdr'), P('Course Name', 'hdr'),
             P('Credit Structure (L-T-P-C)', 'hdr'), P('', 'cellc'),
             P('', 'cellc'), P('', 'cellc'), P('Course Basket', 'hdr'),
             P('', 'hdr')],
            [P('', 'cellc'), P('', 'cellc'), P('', 'cellc'), P('L', 'hdr'),
             P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'), P('', 'cellc'),
             P('', 'cellc'), P('', 'cellc'), P('L', 'hdr'),
             P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'), P('', 'cellc'),
             P('', 'cellc')],
        ]
        data, styles = list(head), [
            ('GRID', (0, 0), (-1, -1), 0.4, LINE),
            ('BACKGROUND', (0, 0), (-1, 2), colors.HexColor('#dde3ef')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 1.6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.6),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('SPAN', (0, 0), (0, 2)),
            ('SPAN', (1, 0), (7, 0)),
            ('SPAN', (8, 0), (14, 0)),
            ('SPAN', (15, 0), (15, 2)),
            ('SPAN', (3, 1), (6, 1)),
            ('SPAN', (10, 1), (13, 1)),
            ('SPAN', (1, 2), (2, 2)),
            ('SPAN', (8, 2), (9, 2)),
        ]
        width = PAGE[0] - 2 * M
        mm_ = mm
        colw = [13, 15, 40, 5, 5, 5, 5, 13, 13, 38, 5, 5, 5, 5, 13]
        colw = [c * mm_ for c in colw]
        colw.append(width - sum(colw))

        r = 3
        for g in self.r['table1']:
            data.append([P('Semester %s' % g['sem'], 'cellb')] + [P('')] * 15)
            styles += [('BACKGROUND', (0, r), (-1, r), colors.HexColor('#f4f6fb'))]
            r += 1
            seen_old = None
            for row in g['rows']:
                n, o = row['new'], row['old']
                cont = o is not None and seen_old == o['code'] and o is not None
                if o is not None:
                    seen_old = o['code']
                data.append([
                    P('', 'cellc'),
                    P(n['code'], 'cellb'), P(n['name']),
                    P(_sp(n['L']), 'cellc'), P(_sp(n['T']), 'cellc'),
                    P(_sp(n['P']), 'cellc'), P(_sp(n['C']), 'cellb'),
                    P(_sp(n['basket']), 'cellc'),
                    P(o['code'], 'cellb') if (o and not cont) else (P('', 'cellc')
                                                                 if o else P('', 'cellc')),
                    P(o['name']) if (o and not cont) else P('', 'cellc'),
                    P(_sp(o['L']), 'cellc') if (o and not cont) else P('', 'cellc'),
                    P(_sp(o['T']), 'cellc') if (o and not cont) else P('', 'cellc'),
                    P(_sp(o['P']), 'cellc') if (o and not cont) else P('', 'cellc'),
                    P(_sp(o['C']), 'cellb') if (o and not cont) else P('', 'cellc'),
                    P(_sp(o['basket']), 'cellc') if (o and not cont) else P('', 'cellc'),
                    P(self._passing(o) if not cont else '', 'cell')])
                if o is None:
                    styles.append(('BACKGROUND', (8, r), (15, r),
                                   colors.HexColor('#fbf3e4')))
                r += 1
            data.append([P('TOTAL CREDITS', 'cellb'), P('', 'cellc'),
                         P('Total Number of credits', 'cellc'),
                         P('', 'cellc'), P('', 'cellc'), P('', 'cellc'),
                         P('<b>%s</b>' % g['new_credits'], 'cellc'), P('', 'cellc'),
                         P('', 'cellc'), P('Total Number of credits Earned', 'cellc'),
                         P('', 'cellc'), P('', 'cellc'), P('', 'cellc'),
                         P('<b>%s</b>' % g['old_credits'], 'cellc'), P('', 'cellc'),
                         P('', 'cellc')])
            styles.append(('BACKGROUND', (0, r), (-1, r), GREY))
            r += 1

        tot_b = sum(g['new_credits'] for g in self.r['table1'])
        data.append([P('TOTAL NUMBER OF CREDITS = %s' % tot_b, 'cellb')]
                    + [P('')] * 14 + [P('', 'cellc')])
        styles.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#dde3ef')))
        styles.append(('SPAN', (0, r), (6, r)))
        t = Table(data, colWidths=colw, repeatRows=3)
        t.setStyle(TableStyle(styles))
        return [t]

    @staticmethod
    def _passing(o):
        if not o:
            return ''
        bits = [str(o.get('semester') or '')]
        if o.get('month_year'):
            bits.append(str(o['month_year']))
        bits = ' '.join(x for x in bits if x)
        if o.get('grade'):
            bits += ' - %s GRADE' % o['grade']
        if o.get('term'):
            bits += ' (%s)' % o['term']
        return bits.strip()

    # ----------------------------------------------------------- Tables
    def _title(self, txt):
        return Paragraph(txt, ST['h2'])

    def _table2(self):
        items = self.r['table2']
        data = [[P('S.No', 'hdr'),
                 P('The courses in which the student has been awarded an F or NP '
                   'grade as listed in Table I.', 'hdr'),
                 P('L', 'hdr'), P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'),
                 P('Course Basket', 'hdr')]]
        for i, it in enumerate(items, 1):
            c = it['course']
            data.append([P(i, 'cellc'), P('%s &nbsp;&ndash;&nbsp; %s%s'
                                          % (c['code'], c['name'],
                                             ' (grade %s)' % c['grade']
                                             if c.get('grade') else ''), 'cell'),
                         P(_sp(c['L']), 'cellc'), P(_sp(c['T']), 'cellc'),
                         P(_sp(c['P']), 'cellc'), P(_sp(c['C']), 'cellb'),
                         P(_sp(c['basket']), 'cellc')])
        data.append([P('', 'cellc'), P('Total Number of credits', 'cellb')]
                    + [P('', 'cellc')] * 4 + [P('<b>%s</b>' % self.r['table2_total'],
                                                'cellc')])
        w = PAGE[0] - 2 * M
        fixed = 10 + 6 * 4 + 18
        t = _mk(data, [10 * mm, w - fixed * mm] + [6 * mm] * 4 + [18 * mm])
        return [Spacer(1, 2.5 * mm), self._title(
            'Failed / NP Graded Courses (if any)'), t]

    def _table3(self):
        items = self.r['table3']
        data = [[P('The courses successfully completed and are not mapped in Table I',
                   'hdr'), P('', 'hdr'), P('', 'hdr'), P('', 'hdr'),
                 P('Courses can be exempted in the New (Readmitted) PRC', 'hdr'),
                 P('', 'hdr'), P('', 'hdr'), P('', 'hdr'),
                 P('Semester in which the course is offered / Basket', 'hdr')],
                [P('Course Code', 'hdr'), P('Course Name', 'hdr'),
                 P('L', 'hdr'), P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'),
                 P('Course Code', 'hdr'), P('Course Name', 'hdr'),
                 P('L', 'hdr'), P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'),
                 P('', 'hdr')]]
        for it in items:
            o = it['old']
            data.append([P(o['code'], 'cellb'), P(o['name']),
                         P(_sp(o['L']), 'cellc'), P(_sp(o['T']), 'cellc'),
                         P(_sp(o['P']), 'cellc'), P(_sp(it['credits']), 'cellb'),
                         P('', 'cellc'), P('Exempted', 'cellc'),
                         P('', 'cellc'), P('', 'cellc'), P('', 'cellc'),
                         P('', 'cellc'),
                         P('Semester %s / %s' % (_sp(o.get('semester')),
                                                  _sp(o.get('basket'))), 'cellc')])
        if not items:
            data.append([P('None', 'cellc')] + [P('', 'cellc')] * 12)
        data.append([P('', 'cellc'), P('Total Number of credits exempted', 'cellb')]
                    + [P('', 'cellc')] * 9
                    + [P('<b>%s</b>' % self.r['table3_total'], 'cellc'), P('', 'cellc')])
        w = PAGE[0] - 2 * M
        cw = [13, 38, 5, 5, 5, 5, 13, 30, 5, 5, 5, 5, 32]
        cw = [c * mm for c in cw]
        cw[12] += w - sum(cw)
        t = _mk(data, cw, _grid(len(data)) + [
            ('SPAN', (0, 0), (5, 0)), ('SPAN', (6, 0), (11, 0))])
        return [Spacer(1, 2.5 * mm), self._title(
            'Exemption of Course(s) (if any) in the New (Readmitted) PRC'), t]

    def _table4(self):
        items = self.r['table4']
        data = [[P('S.No', 'hdr'),
                 P('Additional Course(s) (if any) that need to be completed to meet '
                   'the requirements as per the New (Readmitted) PRC', 'hdr'),
                 P('L', 'hdr'), P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'),
                 P('Semester in which it is offered / Basket', 'hdr'),
                 P('Reason', 'hdr')]]
        for i, it in enumerate(items, 1):
            data.append([P(i, 'cellc'), P('%s &nbsp;&ndash;&nbsp; %s'
                                          % (it['code'], it.get('name') or ''), 'cell'),
                         P(_sp(it.get('L')), 'cellc'), P(_sp(it.get('T')), 'cellc'),
                         P(_sp(it.get('P')), 'cellc'), P(_sp(it.get('C')), 'cellb'),
                         P('Semester %s / %s' % (_sp(it.get('sem')),
                                                  _sp(it.get('basket'))), 'cellc'),
                         P(it.get('reason') or '', 'note')])
        if not items:
            data.append([P('', 'cellc'), P('None', 'cellc')] + [P('', 'cellc')] * 6)
        data.append([P('', 'cellc'), P('Total number of credits', 'cellb')]
                    + [P('', 'cellc')] * 4
                    + [P('<b>%s</b>' % self.r['table4_total'], 'cellb'),
                       P('', 'cellc')])
        w = PAGE[0] - 2 * M
        cw = [9, 62, 5, 5, 5, 5, 30, 48]
        cw = [c * mm for c in cw]
        cw[7] += w - sum(cw)
        t = _mk(data, cw)
        return [Spacer(1, 2.5 * mm), self._title(
            'Additional Course(s) (if any)'), t]

    def _table5(self):
        items = self.r['table5']
        data = [[P('S.No', 'hdr'),
                 P('Courses not successfully completed and not part of the mapping as '
                   'per Table I', 'hdr'),
                 P('L', 'hdr'), P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'),
                 P('Semester in which it is offered / Basket', 'hdr')]]
        for i, it in enumerate(items, 1):
            c = it['course']
            data.append([P(i, 'cellc'), P('%s &nbsp;&ndash;&nbsp; %s'
                                          % (c['code'], c['name']), 'cell'),
                         P(_sp(c['L']), 'cellc'), P(_sp(c['T']), 'cellc'),
                         P(_sp(c['P']), 'cellc'), P(_sp(it['credits']), 'cellb'),
                         P('Semester %s / %s' % (_sp(c.get('semester')),
                                                  _sp(c.get('basket'))), 'cellc')])
        if not items:
            data.append([P('', 'cellc'),
                         P('None - every F / NP graded course is already listed in '
                           'Table II and has to be re-attempted.', 'cell')]
                        + [P('', 'cellc')] * 5)
        data.append([P('', 'cellc'), P('Total Number of credits', 'cellb')]
                    + [P('', 'cellc')] * 4
                    + [P('<b>%s</b>' % self.r['table5_total'], 'cellb')])
        w = PAGE[0] - 2 * M
        cw = [9, 78, 5, 5, 5, 5, 40]
        cw = [c * mm for c in cw]
        cw[6] += w - sum(cw)
        t = _mk(data, cw)
        return [Spacer(1, 2.5 * mm), self._title(
            'Courses to be removed from the transcript (if any)'), t]

    # ----------------------------------------------------------- surplus
    def _surplus(self):
        r = self.r
        if not r.get('skippable') and not r.get('surplus_total'):
            return []
        out = []
        if r.get('surplus_total'):
            rows = [[P('Basket', 'hdr'),
                     P('Credits already earned beyond the minimum required for '
                       'this basket', 'hdr')]]
            for bk, v in sorted(r['surplus_by_basket'].items()):
                rows.append([P(bk, 'cell'), P(v, 'cellc')])
            rows.append([P('Total surplus', 'cellb'),
                         P('<b>%s</b>' % r['surplus_total'], 'cellb')])
            w = PAGE[0] - 2 * M
            out += [Spacer(1, 2.5 * mm), self._title(
                'Credits in excess of the PRC requirement'), _mk(rows, [
                    40 * mm, w - 40 * mm], _grid(len(rows)) + [
                        ('BACKGROUND', (0, len(rows) - 1), (-1, len(rows) - 1),
                         GREY)])]
        if r.get('skippable'):
            rows = [[P('S.No', 'hdr'),
                     P('Course that may be dropped, because the credits already '
                       'earned in the same basket exceed the requirement', 'hdr'),
                     P('L', 'hdr'), P('T', 'hdr'), P('P', 'hdr'), P('C', 'hdr'),
                     P('Basket', 'hdr'),
                     P('Semester in which it is offered', 'hdr')]]
            for i, s in enumerate(r['skippable'], 1):
                rows.append([P(i, 'cellc'),
                             P('%s &nbsp;&ndash;&nbsp; %s'
                               % (s['code'], s.get('name') or ''), 'cell'),
                             P(_sp(s.get('L')), 'cellc'),
                             P(_sp(s.get('T')), 'cellc'),
                             P(_sp(s.get('P')), 'cellc'),
                             P(_sp(s.get('C')), 'cellb'),
                             P(_sp(s.get('basket')), 'cellc'),
                             P(_sp(s.get('sem')), 'cellc')])
            rows.append([P('', 'cellc'),
                         P('Total credits that may be dropped', 'cellb')]
                        + [P('', 'cellc')] * 4
                        + [P('<b>%s</b>' % r['skippable_total'], 'cellb'),
                           P('', 'cellc'), P('', 'cellc')])
            w = PAGE[0] - 2 * M
            cw = [9, 74, 5, 5, 5, 5, 13]
            cw = [c * mm for c in cw]
            cw[6] += w - sum(cw)
            out += [Spacer(1, 2.5 * mm), self._title(
                'Course(s) that may be skipped from the semesters ahead (if any)'),
                _mk(rows, cw),
                Paragraph('Dropping a course is an academic decision. This list is '
                          'suggested by the equivalence engine from the surplus '
                          'credits above and must be approved by the Board of '
                          'Studies. Pre-requisites are not evaluated.', ST['note'])]
        return out

    # ----------------------------------------------------------- baskets
    def _basket(self):
        rows = self.r['baskets']
        data = [[P('Basket', 'hdr'),
                 P('Minimum Credits to be completed for the award of the Degree',
                   'hdr'),
                 P('Credits Completed (as per Tables I and III)', 'hdr'),
                 P('Credits to be completed from the time of readmission '
                   '(including the courses listed in Tables II and IV)', 'hdr'),
                 P('Credits in excess of the requirement', 'hdr')]]
        for b in rows:
            last = b['code'] == 'TOTAL'
            stl = 'cellb' if last else 'cell'
            data.append([P(b['label'], stl), P(b['min'], 'cellc'),
                         P(b['done'], 'cellc'), P(b['left'], 'cellc'),
                         P(b.get('surplus', 0), 'cellc')])
        w = PAGE[0] - 2 * M
        t = _mk(data, [w - 4 * 36 * mm] + [36 * mm] * 4,
                _grid(len(data)) + [
                    ('BACKGROUND', (0, len(data) - 1), (-1, len(data) - 1), GREY)])
        return [Spacer(1, 2.5 * mm), self._title(
            'Basket-wise Mapping of Courses as per the New (Readmitted) PRC'), t]

    # ----------------------------------------------------------- summary
    def _summary(self):
        rows = list(self.r['summary'])
        tot = self.r['summary_total']
        req = self.r['credits_required']
        ok = tot >= req
        data = [[P('Index', 'hdr'), P('Description', 'hdr'),
                 P('Number of Credits', 'hdr')]]
        for idx, desc, val in rows:
            data.append([P(idx, 'cellc'), P(desc, 'cell'), P('<b>%s</b>' % val, 'cellc')])
        data.append([P('', 'cellc'), P('<b>Total (B + C + D + E + F)</b>', 'cellb'),
                     P('<b>%s</b>' % tot, 'cellb')])
        n = len(data)
        excess = self.r.get('excess_over_requirement', 0)
        if ok and excess:
            note = ('Kindly Note: (B + C + D + E + F) &ge; A &nbsp;&ndash;&nbsp; '
                    'satisfied: %s &ge; %s. &nbsp;The student already holds '
                    '<b>%s</b> credit(s) more than the PRC requires; the course(s) '
                    'listed above may be dropped from the semesters ahead.'
                    % (tot, req, excess))
        elif ok:
            note = ('Kindly Note: (B + C + D + E + F) &ge; A &nbsp;&ndash;&nbsp; '
                    'satisfied: %s &ge; %s' % (tot, req))
        else:
            note = ('<b>%s</b> &lt; <b>%s</b> - credits do not reconcile; the '
                    'student cannot be awarded the degree under this mapping'
                    % (tot, req))
        data.append([P('', 'cellc'), P(note, 'cellb'), P('', 'cellc')])
        w = PAGE[0] - 2 * M
        t = _mk(data, [16 * mm, w - 16 * mm - 34 * mm, 34 * mm],
                _grid(n) + [
                    ('BACKGROUND', (0, n - 2), (-1, n - 2), GREY),
                    ('BACKGROUND', (0, n - 1), (-1, n - 1),
                     colors.HexColor('#d6ead6' if ok else '#f8d7da'))])
        return [Spacer(1, 2.5 * mm), self._title('Summary'), t]

    # -------------------------------------------------------- signatures
    def _signatures(self):
        w = PAGE[0] - 2 * M
        cells = []
        for label in ('Signature of the HoD', 'Signature of the Associate Dean',
                      'Signature of the Dean',
                      'Signature of the Dean - Academics'):
            cells.append([P('', 'cell'), P('<br/><br/>' + label, 'note')])
        t = Table([cells], colWidths=[w / 4] * 4, rowHeights=[13 * mm])
        t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.4, LINE),
            ('INNERGRID', (0, 0), (-1, -1), 0.4, LINE),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
        ]))
        return [Spacer(1, 4 * mm), t]

    # ------------------------------------------------------- undertaking
    def _undertaking(self):
        s = self.s
        w = PAGE[0] - 2 * M
        letter = [
            [P('From', 'cellb')],
            [P('<b>%s</b><br/>%s<br/>%s'
               % (s.get('name', ''), s.get('roll_no', ''),
                  s.get('program') or self.r['program']), 'cell')],
            [P('To', 'cellb')],
            [P('Dean / Director of the School<br/>%s<br/>Presidency University'
               '<br/>Bengaluru.' % s.get('school_name', ''), 'cell')],
            [P('Subject: Undertaking for Acceptance of Course Equivalence Report',
               'cellb')],
            [P('Dear Sir / Madam,', 'body')],
            [P('I, <b>%s</b>, student of <b>%s</b>, bearing Roll No. <b>%s</b>, at '
               '%s, accept the course equivalence decision and I acknowledge that it '
               'is final and binding.'
               % (s.get('name', ''), s.get('program') or self.r['program'],
                  s.get('roll_no', ''),
                  s.get('school_name', 'Presidency University')), 'body')],
            [P('I hereby commit to the following:', 'body')],
            [P('1.&nbsp;&nbsp;I will fulfil all the additional academic requirements, '
               'if any, as mentioned in the equivalence report (%s credits).'
               % self.r['table4_total'], 'body')],
            [P('2.&nbsp;&nbsp;I will adhere to all academic policies as per the '
               'readmitted Programme Regulations and Curriculum.', 'body')],
            [P('3.&nbsp;&nbsp;I take full responsibility for completing all the '
               'requirements as mentioned in the equivalence report.', 'body')],
            [P('4.&nbsp;&nbsp;I understand that compliance with the equivalence report '
               'is mandatory for becoming eligible for the award of the degree.',
               'body')],
            [P('<br/>Place: Bengaluru<br/>Date: ______________', 'body')],
            [P('Sincerely,<br/><br/><br/>____________________________'
               '<br/>Signature of the Student', 'body')],
            [P('<br/><br/>Countersigned<br/><br/><br/>'
               '____________________________<br/>Signature of the HoD', 'body')],
        ]
        t = Table(letter, colWidths=[w])
        t.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.4, LINE),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('BACKGROUND', (0, 0), (0, -1), colors.white),
        ]))
        return [KeepTogether([Paragraph('Format of Undertaking Letter from the Student',
                                     ST['h1']),
                            Spacer(1, 4 * mm), t]),
                Spacer(1, 3 * mm),
                Paragraph('Report generated on %s. Course credits, basket minima and '
                          'all totals are computed from the official PRC of batch %s; '
                          'course equivalences were proposed by the equivalence engine '
                          'and are subject to approval by the Board of Studies.'
                          % (date.today().strftime('%d %B %Y'),
                             self.r['new_batch']), ST['note'])]


def _grid(n):
    return [('GRID', (0, 0), (-1, n - 1), 0.4, LINE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 1.8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.8),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dde3ef'))]


def _mk(data, widths, style=None):
    """Build a Table, guarding against the two silent layout bugs: a row with
    more cells than there are columns, and total width off the page.

    Rows may be shorter than the column count because SPAN merges cells, but no
    row may be longer.
    """
    ncol = len(widths)
    for i, row in enumerate(data):
        if len(row) > ncol:
            raise ValueError('row %d has %d cells but only %d columns were declared'
                             % (i, len(row), ncol))
    if max((len(r) for r in data), default=0) != ncol:
        raise ValueError('no row fills the %d declared columns' % ncol)
    total = sum(widths)
    avail = PAGE[0] - 2 * M
    if abs(total - avail) > 0.6:
        raise ValueError('table is %.1fpt wide but only %.1fpt is available'
                         % (total, avail))
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle(style or _grid(len(data))))
    return t


def render(result: dict, student: dict) -> bytes:
    return Report(result, student).build()
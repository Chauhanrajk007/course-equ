"""Build a realistic scanned-looking report card PNG for vision testing."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_e2e')
os.makedirs(OUT, exist_ok=True)

ROWS = [
    ('1', 'MAT1001', 'Calculus and Linear Algebra', '4', 'D'),
    ('2', 'PHY1002', 'Optoelectronics and Device Physics', '3', 'B+'),
    ('3', 'MEC1006', 'Engineering Graphics', '2', 'C'),
    ('4', 'ENG1002', 'Technical English', '2', 'D'),
    ('5', 'CSE1500', 'Computational Thinking Using Python', '3', 'D'),
    ('6', 'ECE2007', 'Digital Design', '3', 'B'),
    ('7', 'DES1146', 'Introduction to Design Thinking', '1', 'A'),
    ('8', 'PPS1001', 'Introduction to Soft Skills', '1', 'D'),
    ('9', 'MAT1003', 'Applied Statistics', '2', 'F'),
    ('10', 'CIV1008', 'Basic Engineering Sciences', '2', 'D'),
    ('11', 'CSE1004', 'Problem Solving Using C', '3', 'C'),
    ('12', 'EEE1007', 'Basics of Electrical and Electronics Engineering', '4', 'D'),
]


def font(size, bold=False):
    names = (['arialbd.ttf', 'seguisb.ttf'] if bold
             else ['arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf'])
    for n in names:
        for root in (r'C:\Windows\Fonts', '/usr/share/fonts/truetype/dejavu'):
            p = os.path.join(root, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def build(path, sem='1', noise=True):
    W, H = 1500, 1080
    img = Image.new('RGB', (W, H), (252, 251, 247))
    d = ImageDraw.Draw(img)

    d.text((60, 40), 'PRESIDENCY UNIVERSITY', font=font(34, True), fill=(20, 30, 50))
    d.text((60, 92), 'STATEMENT OF MARKS', font=font(26, True), fill=(20, 30, 50))
    d.text((60, 140), 'Name of the Student : SIDDANA GOUDA', font=font(20), fill=(20, 30, 50))
    d.text((60, 174), 'Roll Number : 20241CIT0082', font=font(20), fill=(20, 30, 50))
    d.text((60, 208), 'Program : B.Tech CSE (Block Chain)', font=font(20), fill=(20, 30, 50))
    d.text((60, 252), 'SEMESTER %s' % sem, font=font(24, True), fill=(20, 30, 50))

    cols = [(60, 'Sl.No'), (150, 'Course Code'), (370, 'Course Name'),
            (1060, 'Credits'), (1180, 'Grade')]
    y0, rh = 300, 56
    for x, label in cols:
        d.text((x, y0 - 36), label, font=font(20, True), fill=(20, 30, 50))
    d.line([(55, y0 - 6), (1450, y0 - 6)], fill=(60, 60, 60), width=2)
    for i, (sn, code, name, cr, gr) in enumerate(ROWS):
        y = y0 + i * rh
        d.text((cols[0][0], y), sn, font=font(20), fill=(25, 25, 25))
        d.text((cols[1][0], y), code, font=font(20, True), fill=(25, 25, 25))
        d.text((cols[2][0], y), name[:52], font=font(20), fill=(25, 25, 25))
        d.text((cols[3][0], y), cr, font=font(20), fill=(25, 25, 25))
        d.text((cols[4][0], y), gr, font=font(20, True), fill=(25, 25, 25))
        d.line([(55, y + 30), (1450, y + 30)], fill=(200, 200, 200), width=1)

    if noise:                       # a slightly rotated, grainy "scan"
        from PIL import ImageEnhance, ImageFilter
        img = img.rotate(0.6, expand=False, fillcolor=(252, 251, 247),
                         resample=Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(0.3))
        img = ImageEnhance.Contrast(img).enhance(0.94)
        img = ImageEnhance.Brightness(img).enhance(0.98)
    img.save(path)
    return path


if __name__ == '__main__':
    p = build(os.path.join(OUT, 'report_card.png'))
    print('wrote', p, os.path.getsize(p), 'bytes')
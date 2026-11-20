"""Helper for reading docx tables and paragraphs as pipe-separated lines."""
from __future__ import annotations

import io
import zipfile
from lxml import etree


def docx_lines(path: str) -> list[str]:
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with open(path, 'rb') as f:
        data = f.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = etree.fromstring(z.read('word/document.xml'))
    body = root.find(W + 'body')
    lines = []
    for child in body:
        if child.tag == W + 'p':
            t = ' '.join(''.join(n.text or '' for n in child.iter()
                                 if n.tag == W + 't').split())
            if t:
                lines.append(t)
        elif child.tag == W + 'tbl':
            for tr in child.findall(W + 'tr'):
                seen, cells = set(), []
                for tc in tr.findall(W + 'tc'):
                    if id(tc) in seen:
                        continue
                    seen.add(id(tc))
                    cell_text = ' '.join(
                        ''.join(n.text or '' for n in tc.iter()
                                if n.tag == W + 't').split())
                    cells.append(cell_text)
                if cells:
                    lines.append('| ' + ' | '.join(cells) + ' |')
    return lines

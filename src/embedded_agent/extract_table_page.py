"""Isolated layout extraction of exactly one physical PDF page."""
import sys
import shutil
import subprocess
import json
from pypdf import PdfReader

reader=PdfReader(sys.argv[1])
page=int(sys.argv[2])
if not 1<=page<=len(reader.pages):raise ValueError('physical page out of range')
binary=shutil.which('pdftotext')
if binary:
    result=subprocess.run([binary,'-f',str(page),'-l',str(page),'-layout','-enc','UTF-8',sys.argv[1],'-'],capture_output=True,text=True,encoding='utf-8',timeout=15,check=True)
    body=result.stdout
else:
    body=reader.pages[page-1].extract_text(extraction_mode='layout',layout_mode_space_vertically=False,layout_mode_strip_rotated=False)
body='\n'.join(line.rstrip() for line in (body or '').splitlines())
import pdfplumber
with pdfplumber.open(sys.argv[1]) as pdf:
    surface=pdf.pages[page-1]
    tables=[]
    for table in surface.find_tables()[:6]:
        rows=table.extract();corrected=[];rotations=[]
        for row_index,row in enumerate(rows):
            cells=list(row)
            for col_index,bbox in enumerate(table.rows[row_index].cells):
                if not bbox or not cells[col_index]:continue
                chars=surface.crop(bbox).chars
                if chars and sum(not c.get('upright',True) for c in chars)/len(chars)>0.8:
                    cells[col_index]=cells[col_index][::-1]
                    rotations.append([row_index,col_index])
            corrected.append(cells)
        tables.append({'rows':corrected,'original_rows':rows,'rotation_corrected_cells':rotations})
    if tables:
        body=json.dumps({'physical_page':page,'extraction':'PDF grid cells; row/column order preserved. Rotated text reversed only when glyph orientation proves rotation; original cells retained.','tables':tables},ensure_ascii=False,indent=2)
if not body or len(body)>80000:raise ValueError('table text empty or too large')
sys.stdout.reconfigure(encoding='utf-8')
sys.stdout.write(body)

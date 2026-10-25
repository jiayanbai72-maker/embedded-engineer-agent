"""Isolated bounded text/page extraction; never executes PDF attachments or scripts."""
import json
import sys
from pathlib import Path

def main():
    from pypdf import PdfReader
    path=Path(sys.argv[1]);reader=PdfReader(path)
    if reader.is_encrypted or not 1<=len(reader.pages)<=1000:raise ValueError('PDF加密或页数超限')
    text=[];index=[];offset=0
    for number,page in enumerate(reader.pages,1):
        body=(page.extract_text() or '')+'\n\f\n'
        if offset+len(body)>4_000_000:raise ValueError('提取文本超限')
        text.append(body);index.append({'page':number,'start':offset,'end':offset+len(body)});offset+=len(body)
    if sum(len(t.strip()) for t in text)<100:raise ValueError('扫描PDF无足够文本，需要OCR或人工资料')
    (path.parent/'body.txt').write_text(''.join(text),encoding='utf-8')
    (path.parent/'pages.json').write_text(json.dumps(index),encoding='utf-8')

if __name__=='__main__':main()

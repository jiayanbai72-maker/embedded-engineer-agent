"""Text-only extraction of saved webpages. Never executes HTML or invents pages."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin,urlsplit

def pdf_links(raw,base):
    """Visible PDF anchors only; candidates, never automatically trusted facts."""
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.urls=[]
        def handle_starttag(self,tag,attrs):
            if tag!='a':return
            href=dict(attrs).get('href','')
            url=urljoin(base,href);parsed=urlsplit(url)
            if parsed.scheme=='https' and not parsed.username and parsed.path.lower().endswith('.pdf') and url not in self.urls:
                self.urls.append(url)
    parser=Links();parser.feed(raw)
    # Technical manuals precede legal declarations; no invented document URLs.
    ordered=sorted(parser.urls,key=lambda url:(0 if any(t in url.lower() for t in ('datasheet','reference_manual','user_manual','application_note')) else 1,url))
    return ordered[:12]


class WebText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []; self.title = []; self.hidden = []; self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == 'title': self.in_title = True
        if tag in ('script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer'):
            self.hidden.append(tag)
        if tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3'): self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
        if self.hidden and tag == self.hidden[-1]: self.hidden.pop()
        if tag in ('p', 'div', 'li', 'tr'): self.parts.append('\n')

    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        elif not self.hidden: self.parts.append(data)


def extract(raw):
    parser = WebText(); parser.feed(raw); parser.close()
    title = ' '.join(''.join(parser.title).split())
    body = re.sub(r'\n\s*\n+', '\n\n', '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines())).strip()
    if any(marker in title.lower() for marker in ('access denied', 'just a moment', 'verify you are human')):
        raise ValueError('网页是访问验证页，不入库')
    if len(body) < 100: raise ValueError('网页正文过少，需人工核对或动态页面采集')
    return title, body

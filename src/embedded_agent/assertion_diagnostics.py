"""Diagnostic replay on a separate test copy; original verdict stays authoritative."""
import re


def instrument(files, log):
    match=re.search(r'Assertion failed: (.*?), file ([^,\r\n]+), line (\d+)',log)
    if not match:return None
    expression,name,number=match.group(1),match.group(2),int(match.group(3))
    if name not in files or not name.startswith('test_'):return None
    lines=files[name].splitlines(keepends=True)
    if not 1<=number<=len(lines):return None
    line=lines[number-1]
    needle='assert('+expression+')'
    if line.count(needle)!=1:return None
    # Instrument only simple scalar reads. Never evaluate function calls,
    # assignments, ++/--, indexing or dereference as a diagnostic probe.
    scalar=r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*'
    allowed=re.fullmatch(r'[A-Za-z_0-9.\s&|!=<>+\-]*',expression)
    if not allowed or '++' in expression or '--' in expression or re.search(r'(?<![=!<>])=(?!=)',expression):return None
    probes=[]
    for part in re.split(r'&&|\|\|',expression):
        atom=part.strip().lstrip('!')
        parsed=re.fullmatch('('+scalar+r')\s*(?:(?:==|!=|<=|>=|<|>)\s*([A-Za-z_0-9]+))?',atom)
        if not parsed:continue
        for value in parsed.groups():
            if value and re.fullmatch(scalar,value) and value not in probes:probes.append(value)
    if not probes:return None
    probes=probes[:12]
    prefix='do { '+''.join('fprintf(stderr, "DRAFT_DIAG '+v+'=%lld\\n", (long long)('+v+')); ' for v in probes)+'fflush(stderr); '
    lines[number-1]=line.replace(needle,prefix+needle+'; } while(0)',1)
    # Include stdio separately and restore physical source line numbers.
    body='#include <stdio.h>\n#line 1 "'+name+'"\n'+''.join(lines)
    return {'file':name,'line':number,'expression':expression,'probes':probes,'instrumented_source':body}


def values(log):
    return {name:int(value) for name,value in re.findall(r'DRAFT_DIAG ([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)=(-?\d+)',log)}

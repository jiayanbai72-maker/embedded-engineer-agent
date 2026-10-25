"""Bounded debugging guidance and lexical C evidence, not model reasoning."""
import re

LESSONS = [
 {'id':'callback_fanout','triggers':['count','pulses','calls'],
  'lesson':'一次上层调用可能经循环/辅助函数产生多次回调。区分调用次数、输出次数与执行轴，追踪运行调用记录和循环体，不能只增加防重复标记。',
  'example':'匿名案例：移动一次后调用批量回中函数，批量函数遍历N个通道，输出总数为1+N；若契约只允许当前通道，则应审查调用范围。例子不是当前项目结论。'},
 {'id':'phase_timing','triggers':['time','busy','phase','clock'],
  'lesson':'区分总动作起点、阶段起点、完成状态与断电状态。检查边界前后和时钟回绕，不能只改延时常量。',
  'example':'已验证的合成案例：进入新阶段时记录该阶段实际开始时刻，用无符号差值判断阶段间隔；总超时使用独立起点。阶段切换与到期输出不能无条件多延后一拍。此方法不是当前代码结论，须对照原测试与实际调用时刻。'},
 {'id':'interface_consistency','triggers':['undeclared','identifier','未声明','error'],
  'lesson':'修复前对照声明、定义和调用，新增状态必须同步头文件；编译错误与行为错误分别处理。'}]


def masked(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ''.join('\n' if c=='\n' else ' ' for c in m.group()),text,flags=re.S)


def function_index(files):
    result=[]
    for name,body in files.items():
        if not name.endswith('.c') or name.startswith('test_'):continue
        clean=masked(body)
        pattern=r'(?m)^[ \t]*(?:(?:static|inline|const|unsigned|signed|long|short|struct)\s+)*[A-Za-z_]\w*(?:\s*\*)?\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{'
        for match in re.finditer(pattern,clean):
            level=1;end=match.end()
            while end<len(clean) and level:
                level+=(clean[end]=='{')-(clean[end]=='}');end+=1
            section=clean[match.end():end]
            calls=list(dict.fromkeys(re.findall(r'([A-Za-z_]\w*(?:->\w+)*)\s*\(',section)))
            calls=[c for c in calls if c not in ('if','while','for','switch','sizeof')]
            result.append({'file':name,'function':match.group(1),'line':body.count('\n',0,match.start())+1,
                           'calls':calls[:20],'has_loop':bool(re.search(r'\b(for|while)\s*\(',section))})
    return result[:60]


def trace_source(body, filename="diagnostic.c"):
    """Add logging to indirect call expressions on a diagnostic-only copy."""
    clean=masked(body)
    comparisons=list(re.finditer(r'\bif\s*\(\s*(([A-Za-z_]\w*)\s*(>=|<=|==|!=|>|<)\s*([A-Z_]\w*|[0-9]+[uUlL]*))',clean))
    for match in reversed(comparisons):
        lhs,op,rhs=match.group(2),match.group(3),match.group(4)
        # Only named local scalar declarations; skip volatile sources entirely.
        if re.search(r'\bvolatile\b',clean) or not re.search(r'\b(?:uint32_t|int32_t|uint16_t|int16_t|int|unsigned|long)\s+'+re.escape(lhs)+r'\s*[;=]',clean):continue
        expression=body[match.start(1):match.end(1)]
        replacement='(fprintf(stderr,"DRAFT_BRANCH %s:%d %s '+lhs+'=%lld '+op+' '+rhs+'=%lld result=%d\\n",__FILE__,__LINE__,__func__,(long long)('+lhs+'),(long long)('+rhs+'),('+expression+')),('+expression+'))'
        body=body[:match.start(1)]+replacement+body[match.end(1):]
    clean=masked(body);matches=list(re.finditer(r'\b[A-Za-z_]\w*(?:->\w+)+(?=\s*\()',clean))
    for match in reversed(matches):
        original=body[match.start():match.end()]
        replacement='(fprintf(stderr,"DRAFT_CALL %s:%d %s %s\\n",__FILE__,__LINE__,__func__,"'+original+'"),('+original+'))'
        body=body[:match.start()]+replacement+body[match.end():]
    return '#include <stdio.h>\n#line 1 "'+filename+'"\n'+body if matches or comparisons else body


def parse_trace(log):
    entries=[]
    for file,line,caller,callback in re.findall(r'DRAFT_CALL ([^:\r\n]+):(\d+) (\w+) ([^\s]+)',log):
        key=(file,int(line),caller,callback)
        if entries and entries[-1]['key']==key:entries[-1]['count']+=1
        else:entries.append({'key':key,'file':file,'line':int(line),'caller':caller,'callback':callback,'count':1})
    return [{k:v for k,v in e.items() if k!='key'} for e in entries[-60:]]


def brief(files,report):
    diagnostic=report.get('host_tests',{}).get('assertion_diagnostic',{})
    text=(diagnostic.get('expression','')+' '+str(diagnostic.get('branch_trace',[]))+' '+report.get('mcu_compile',{}).get('log','')).lower()
    lessons=[x for x in LESSONS if any(t in text for t in x['triggers'])][:2]
    return {'mode':'diagnosis_before_edit','function_index':function_index(files),'matched_lessons':lessons,
            'required_evidence':['逐项比较断言预期与实际值','引用实际文件、函数、行号与调用/循环证据','提出一个可检验的修复假设和受影响范围','最小修改后运行原失败测试和完整回归'],
            'rules':'案例只是排查线索，不是当前证据。rationale只给简短结论、证据位置和预期变化，不输出内部思维链。不删改测试，不把编译通过当行为通过。'}


def parse_branches(log):
    rows=[]
    pattern=r'DRAFT_BRANCH ([^:\r\n]+):(\d+) (\w+) (\w+)=(-?\d+) (>=|<=|==|!=|>|<) (\w+)=(-?\d+) result=([01])'
    for file,line,caller,lhs,left,op,rhs,right,result in re.findall(pattern,log):
        rows.append({'file':file,'line':int(line),'caller':caller,'condition':lhs+' '+op+' '+rhs,
                     'left':int(left),'right':int(right),'result':bool(int(result))})
    return rows[-60:]


def trace_assertions(body, filename):
    """Observe assertion completion on a replay copy; evaluate each assert once."""
    clean=masked(body);edits=[];ordinal=0
    for match in re.finditer(r'\bassert\s*\(',clean):
        ordinal+=1;depth=1;end=match.end()
        while end<len(clean) and depth:
            depth+=(clean[end]=='(')-(clean[end]==')');end+=1
        if depth:continue
        original=body[match.start():end]
        replacement='('+original+', fprintf(stderr,"DRAFT_ASSERT_PASS '+filename+'#'+str(ordinal)+'\\n"))'
        edits.append((match.start(),end,replacement))
    for start,end,replacement in reversed(edits):body=body[:start]+replacement+body[end:]
    return body


def assertion_progress(log):
    return sorted(set(re.findall(r'DRAFT_ASSERT_PASS ([A-Za-z_][A-Za-z0-9_.]*#\d+)',log)))

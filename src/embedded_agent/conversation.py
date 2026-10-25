"""Project-scoped, persisted conversations. Replies never execute tool actions."""
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID


class Conversations:
    def __init__(self, root):
        self.root=Path(root)/'runtime/conversations';self.root.mkdir(parents=True,exist_ok=True)

    def path(self, project_id):
        return self.root/(str(UUID(project_id))+'.json')

    def history(self, project_id):
        path=self.path(project_id)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    def save(self, project_id, rows):
        path=self.path(project_id);temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

    def send(self, project, payload, model):
        if model is None:raise ValueError('请先在模型设置中保存密钥并启用模型')
        text=payload.get('message');request_id=str(UUID(str(payload.get('request_id'))))
        if not isinstance(text,str) or not text.strip() or len(text)>6000:raise ValueError('消息需为1至6000个字符')
        rows=self.history(project['id'])
        existing=next((r for r in rows if r['id']==request_id),None)
        if existing:
            if existing['message']!=text.strip():raise ValueError('同一消息编号不能用于不同内容')
            return {'messages':rows,'reused':True}
        row={'id':request_id,'message':text.strip(),'status':'pending','created_at':datetime.now(timezone.utc).isoformat(),'project_revision':project['revision']}
        rows.append(row);self.save(project['id'],rows)
        artifacts=project.get('artifacts',{})
        summary={'description':project['description'][-12000:],'status':project['status'],'revision':project['revision'],
                 'stage':project.get('stage'),'available_artifacts':sorted(artifacts),
                 'verification':project.get('verification',{}),
                 'delivery_recorded':bool(artifacts.get('delivery')),
                 'recent_events':[{k:e.get(k) for k in ('action','outcome','message','reason')} for e in project.get('events',[])[-5:]],
                 'tool_results':{k:{'status':v.get('status'),'reason':v.get('reason'),'log_tail':str(v.get('log',''))[-2000:]} for k in ('keil_build','firmware_build','draft_verification','build','verification') if isinstance((v:=artifacts.get(k)),dict)}}
        try:
            answer=model.generate(role='project_chat',instruction='用简短自然中文直接回答使用者，遵守用户要求的回答长度，不主动罗列内部字段名、版本号或状态码。根据当前项目快照与对话区分事实、建议和未验证项；缺失字段只表示此快照未提供，不代表交付物为空；软件测试通过不等于硬件通过。这次只交流，不执行编译、联网、修改需求或确认。需要修改项目时提示用户使用“同时作为需求补充”或相应操作按钮。不要展示内部思维过程，只给简要依据。',
                                  context={'project':summary,'conversation':[{'user':r['message'],'assistant':r.get('reply','')[-3000:],'status':r['status']} for r in rows[-12:]]})
            reply=answer.get('reply') if isinstance(answer,dict) else None
            if not isinstance(reply,str) or not reply.strip() or len(reply)>30000:raise ValueError('模型未返回有效的对话内容；本次调用已按用量计费')
            row.update(reply=reply.strip(),status='answered')
        except Exception as exc:
            row.update(status='failed',error=str(exc) if isinstance(exc,ValueError) else '对话请求异常，请检查预算和模型设置；不会自动重试')
        finally:
            key=getattr(model,'last_call_id',None)
            if key:row['usage']=model.budget.receipt(key)
            self.save(project['id'],rows)
        return {'messages':rows,'reused':False}

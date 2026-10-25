'use strict';
const $ = id => document.getElementById(id);
const labels = {ready_keil_build:'可构建 Keil 工程',keil_build_failed:'Keil 构建失败',awaiting_analysis:'等待分析',needs_input:'等待需求确认',awaiting_selection:'等待方案选择',awaiting_implementation:'等待代码',awaiting_mcu_implementation:'等待 MCU 源码',awaiting_firmware_implementation:'等待固件源码',ready_build:'可编译',ready_mcu_build:'可编译 MCU 模块',ready_firmware_build:'可构建固件',ready_test:'可运行测试',ready_delivery:'可生成交付包',documents_delivered:'已交付',build_failed:'编译失败',test_failed:'测试失败',mcu_build_failed:'MCU 编译失败',firmware_build_failed:'固件构建失败',awaiting_decision:'等待决策',ready_action:'待执行',executing:'执行中',waiting_input:'等待补充',complete:'本轮完成',repair_limit:'达到修复上限',budget_exhausted:'步骤预算耗尽',interrupted_unknown:'中断，需核查',passed:'通过',failed:'失败',not_run:'未执行',unsupported:'能力未配置'};
const actionLabels={discover_hardware:'自动发现硬件接口',hardware_capture:'采集授权串口日志',keil_build:'构建 Keil 工程',keil_edit:'修改 Keil 副本源码',read_keil_source:'读取 Keil 源码',analysis:'提交分析',implementation:'提交主机代码',build:'主机编译检查',test:'运行主机测试',execute:'生成交付包',ask:'提出问题',finish:'结束本轮',mcu_implementation:'提交 MCU 源码',mcu_build:'编译 MCU 模块',firmware_implementation:'提交固件源码',firmware_build:'完整固件构建'};
Object.assign(actionLabels,{record_parameter:'Agent自行核对并登记原文参数'});
Object.assign(actionLabels,{record_fact:'Agent核对并登记引脚等原文关系'});
Object.assign(actionLabels,{research_documents:'本地不足时联网补充原厂资料',fetch_document:'下载并入库原厂资料'});
Object.assign(actionLabels,{search_documents:'检索官方资料',read_document_page:'读取原文页面',read_parameter:'读取审核参数'});
Object.assign(labels,{selection_needs_evidence:'选型待补证据',selection_failed:'选型约束不满足',selection_checked:'选型检查通过'});
Object.assign(labels,{preliminary_design:'初步设计（保留待验证项）',estimated_meets:'估算满足，待实测',estimated_shortfall:'估算存在缺口',insufficient_data:'关键估值不完整'});
Object.assign(actionLabels,{power_estimate:'估算整机功耗与续航'});
Object.assign(labels,{design_researching:'方案研究中',design_needs_evidence:'候选待补证据',design_has_feasible:'存在通过声明约束的方案',design_no_feasible:'候选约束不满足',needs_evidence:'待补证据',unknown:'未知'});
Object.assign(actionLabels,{design_plan:'提出或调整候选方案',design_research:'执行方案资料检索',design_evaluate:'检查并比较全部候选',design_recommend:'记录有依据的推荐'});
Object.assign(labels,{draft_in_progress:'图纸与代码草案生成中',draft_ready:'等待编译与行为测试',draft_verified:'编译与主机测试已通过，硬件待验证',draft_verification_failed:'编译或测试失败，等待智能体修复'});
Object.assign(actionLabels,{draft_artifacts:'保存图纸与代码草案',draft_verify:'编译MCU源码并执行主机行为测试',draft_edit:'按失败日志逐文件修复源码',draft_patch:'按真实源码最小替换修复'});
Object.assign(actionLabels,{selection_check:'选型与约束检查'});
let project=null, context=null, analysisBase=null, busy=false;
const node=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
function notify(message,error=false){$('notice').hidden=false;$('notice').textContent=message;$('notice').className=error?'error':'';}
async function api(path,payload){const options=payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)};const response=await fetch(path,options);const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');return data;}
async function guarded(fn){if(busy)return;busy=true;document.body.setAttribute('aria-busy','true');try{await fn();}catch(e){notify(e.message,true);}finally{busy=false;document.body.removeAttribute('aria-busy');}}
function tab(name){for(const key of ['user','analyst','history','knowledge','design','power','readiness'])$(key+'-panel').hidden=key!==name;$('selection-evidence-panel').hidden=name!=='knowledge';document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));}
async function listProjects(){const data=await api('/projects');$('projects').replaceChildren();for(const item of data.projects){const b=node('button',undefined,'project-item'+(project?.id===item.id?' active':''));b.append(node('span',item.description.split('\n')[0].slice(0,42)),node('small',labels[item.status]||item.status));b.onclick=()=>guarded(()=>openProject(item.id));$('projects').append(b);}if(!data.projects.length)$('projects').append(node('p','尚无项目，创建后将保存在这里。','muted small'));}
async function openProject(id){document.body.classList.remove('sidebar-open');const switching=project?.id!==id;project=await api('/projects/'+id);if(switching){$('analysis-json').value='';$('analysis-file').value='';$('arguments').value='{}';$('decision-rationale').value='';$('expected').value='';context=null;$('run-select').value='';}localStorage.setItem('embedded-project',id);$('welcome').hidden=true;$('workspace').hidden=false;renderProject();if(switching||!$('analysis-json').value.trim())analysisBase={id:project.id,revision:project.revision};$('analysis-version').textContent='提交依据：项目版本 '+analysisBase.revision+(analysisBase.revision!==project.revision?'（已过期，请重新读取上下文并导入分析）':'');await listProjects();await listRuns();await refreshConversation(id);if(!$('readiness-panel').hidden)await renderReadiness();}
function renderProject(){renderHardware();renderKeil();renderDesign();renderPower();const a=project.artifacts;$('heading').textContent=project.description.split('\n')[0].slice(0,48);$('description-view').textContent=project.description;$('project-title').textContent='当前项目';$('status').textContent=project.status==='documents_delivered'&&a.preliminary_acceptance?(a.engineering_draft?(a.draft_verification?.status==='passed'?'软件验证草案包已导出，硬件未验证':'草案包已导出，软件验证待完成'):'研究资料已导出，图纸与源码待生成'):(labels[project.status]||project.status);$('revision').textContent='版本 '+project.revision;
 const steps=['需求','设计','选型','实现','构建','调试','验证','交付'];const complete=[a.requirements?.status==='confirmed',!!a.selected_plan,false,!!(a.implementation||a.mcu_implementation||a.firmware_implementation||a.engineering_draft?.firmware),[a.build,a.mcu_build,a.firmware_build,a.draft_verification?.mcu_compile].some(r=>r?.status==='passed'),project.events.some(e=>['implementation_superseded','mcu_superseded','firmware_superseded'].includes(e.action)),a.verification?.status==='passed',!!a.delivery];$('progress').replaceChildren(...steps.map((s,i)=>node('div',s,'step'+(complete[i]?' done':i===project.stage_index?' current':''))));$('submit-analysis').disabled=!['awaiting_analysis','needs_input'].includes(project.status);
 $('requirements').replaceChildren();for(const req of a.requirements?.requirements||[]){const d=node('div',undefined,'requirement');d.append(node('b',req.id+' · '+req.description),node('p','验收：'+req.acceptance),node('small',req.origin==='proposed'?'分析者建议，需确认':'从用户描述提取','muted'));$('requirements').append(d);}if(!a.requirements)$('requirements').append(node('p','需求已保存，等待分析者提取功能、约束和验收标准。','muted'));
 for(const c of a.requirements?.constraints||[])$('requirements').append(node('p',c.name+'：'+c.value,'muted small'));
 $('questions').replaceChildren();for(const q of a.requirements?.questions||[])$('questions').append(node('div',(q.blocking?'需先解决：':'待明确：')+q.question,'question'));
 $('confirm').disabled=project.status!=='needs_input'||(a.requirements?.questions||[]).some(q=>q.blocking);
 $('candidates').replaceChildren();for(const c of a.comparison?.candidates||[]){const box=node('div',undefined,'candidate');box.append(node('h3',c.name),node('p',c.architecture),node('p','取舍：'+c.tradeoffs.join('；'),'muted'),node('p','适用条件：'+c.conditions.join('；'),'muted'),node('p','风险：'+c.risks.join('；'),'muted'));if(a.selected_plan?.id===c.id)box.append(node('span','已选择','badge'));const b=node('button','选择此方案','quiet');b.disabled=project.status!=='awaiting_selection';b.onclick=()=>guarded(()=>projectAction('select',{candidate_id:c.id}));box.append(b);$('candidates').append(box);}if(!a.comparison)$('candidates').append(node('p','方案分析完成后将在这里展示。','muted'));
 $('next-step').textContent=project.status==='awaiting_analysis'?'分析者需要读取需求并提交分析。':project.status==='needs_input'?'检查待确认事项，补充信息或确认当前需求。':project.status==='awaiting_selection'?'比较候选方案，并选择本轮实施方向。':project.status==='ready_delivery'?'执行已确认范围内的交付生成。':project.status==='documents_delivered'?'交付包已生成，可以下载。新增需求将使旧结果失效。':'由分析者根据工具结果判断下一步，并通过决策运行执行。';
 $('deliver').disabled=!['ready_delivery','preliminary_design','draft_verified'].includes(project.status);$('download').hidden=project.status!=='documents_delivered';$('download').href='/projects/'+project.id+'/download';if(project.status==='preliminary_design')$('next-step').textContent='可继续初步设计并生成带估算与未解决事项的文档；预算、续航及实机尚未通过验证。';
 $('verification').replaceChildren();for(const [k,v] of Object.entries(project.verification)){const names={keil_build:'Keil 工程构建',firmware_build:'完整固件构建',hardware:'实机验证',host_tests:'主机测试',mcu_object_compilation:'MCU 模块编译'};const row=node('div',undefined,'verification-line');row.append(node('span',names[k]||k),node('b',labels[v]||v));$('verification').append(row);}
 $('rationale').textContent=a.decision?.rationale||'分析者尚未提交方案判断。';$('history').replaceChildren();for(const e of [...project.events].reverse()){const d=node('details',undefined,'history-item');d.append(node('summary',(e.action||e.stage||'记录')+(e.outcome?' · '+e.outcome:'')+(e.source_revision!==undefined?' · 来源版本 '+e.source_revision:'')),node('pre',JSON.stringify(e,null,2)));$('history').append(d);}for(const name of ['build','verification','mcu_build','firmware_build'])if(a[name]){const d=node('details',undefined,'history-item');d.append(node('summary',name+' · '+(labels[a[name].status]||a[name].status)),node('pre',a[name].log||JSON.stringify(a[name].image_checks||{},null,2)));$('history').prepend(d);}}
async function projectAction(action,args={}){await api('/projects/'+project.id+'/'+action,{...args,revision:project.revision});await openProject(project.id);notify('操作已完成，状态已更新。');}
async function listRuns(){const current=$('run-select').value;const data=await api('/projects/'+project.id+'/runs');$('run-select').replaceChildren(node('option','选择运行'));$('run-select').firstChild.value='';for(const run of data.runs){const option=node('option',run.id.slice(0,8)+' · '+(labels[run.status]||run.status));option.value=run.id;$('run-select').append(option);}const preferred=data.runs.find(r=>r.id===current)||data.runs[data.runs.length-1];if(preferred){$('run-select').value=preferred.id;await loadRun();}else{context=null;renderRun();}}
async function loadRun(){const id=$('run-select').value;context=id?await api('/runs/'+id):null;if(context?.run.status==='waiting_input'&&!context.run.pending&&context.project.status==='awaiting_analysis'&&context.run.project_revision!==context.project.revision){await api('/runs/'+id+'/refresh',{revision:context.run.revision});context=await api('/runs/'+id);notify('已同步补充需求，请点击“开始自动推进”继续分析。');}renderRun();}
function renderRun(){renderRunSummary();renderConversation();renderTaskPlan();const run=context?.run;$('run-status').textContent=run?(labels[run.status]||run.status)+' · 已执行 '+run.steps+'/'+run.max_steps+' 步 · 修复 '+run.repairs+'/'+run.max_repairs+' 次':'新建运行后，分析者可以提交下一步决策。';$('action').replaceChildren();for(const name of context?.allowed_actions||[]){const option=node('option',actionLabels[name]||name);option.value=name;$('action').append(option);}const last=run?.observations.at(-1);$('observation').textContent=last?JSON.stringify(last,null,2):'尚无执行结果。';$('submit-decision').disabled=autoRunning||!run||run.status!=='awaiting_decision';$('tick').disabled=!run||!['ready_action','executing'].includes(run.status);$('refresh-run').disabled=!run||!!run.pending||!['awaiting_decision','waiting_input'].includes(run.status);$('copy-context').disabled=!run;}
async function copy(value){const data=JSON.stringify(value,null,2);try{await navigator.clipboard.writeText(data);notify('上下文已复制。');}catch{const blob=new Blob([data],{type:'application/json'}),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download='task-context.json';a.click();URL.revokeObjectURL(url);notify('浏览器未允许复制，已下载上下文文件。');}}
$('create-form').onsubmit=e=>{e.preventDefault();guarded(async()=>{const p=await api('/projects',{description:$('description').value});await openProject(p.id);tab('user');notify('项目已创建，等待分析。');});};
$('new-project').onclick=()=>{project=null;context=null;$('welcome').hidden=false;$('workspace').hidden=true;$('notice').hidden=true;$('project-title').textContent='开始一个项目';localStorage.removeItem('embedded-project');$('description').focus();};
$('refresh').onclick=()=>guarded(async()=>{if(project)await openProject(project.id);else await listProjects();notify('已刷新。');});
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>tab(b.dataset.tab));$('open-analyst').onclick=()=>tab('analyst');
$('confirm').onclick=()=>guarded(()=>projectAction('confirm',{confirmed:true}));$('deliver').onclick=()=>guarded(()=>projectAction('execute'));
$('supplement-form').onsubmit=e=>{e.preventDefault();guarded(async()=>{await projectAction('supplement',{message:$('supplement').value});$('supplement').value='';});};
$('copy-project').onclick=()=>guarded(async()=>{await copy(project);analysisBase={id:project.id,revision:project.revision};$('analysis-version').textContent='提交依据：项目版本 '+analysisBase.revision;});$('copy-context').onclick=()=>guarded(()=>copy(context));
$('analysis-file').onchange=()=>guarded(async()=>{const file=$('analysis-file').files[0];if(!file)return;if(file.size>190000)throw new Error('分析文件过大');const content=await file.text();JSON.parse(content);$('analysis-json').value=content;analysisBase={id:project.id,revision:project.revision};$('analysis-version').textContent='提交依据：项目版本 '+analysisBase.revision;notify('文件已载入，尚未提交。');});
$('submit-analysis').onclick=()=>guarded(async()=>{if(!analysisBase||analysisBase.id!==project.id||analysisBase.revision!==project.revision)throw new Error('分析对应的项目版本已改变，请重新读取上下文。');const payload=JSON.parse($('analysis-json').value);await api('/projects/'+project.id+'/analysis',{...payload,revision:analysisBase.revision});await openProject(project.id);notify('分析已通过校验，等待用户确认。');});
$('create-run').onclick=()=>guarded(async()=>{const run=await api('/runs',{project_id:project.id});await listRuns();$('run-select').value=run.id;await loadRun();notify('运行已创建，等待决策。');});$('run-select').onchange=()=>guarded(loadRun);
$('refresh-run').onclick=()=>guarded(async()=>{await api('/runs/'+context.run.id+'/refresh',{revision:context.run.revision});await loadRun();notify('已同步项目上下文，请重新判断下一步。');});
$('submit-decision').onclick=()=>guarded(async()=>{const d={id:crypto.randomUUID(),task_id:$('task-choice').value||undefined,project_revision:context.project.revision,action:$('action').value,arguments:JSON.parse($('arguments').value),rationale:$('decision-rationale').value,expected:$('expected').value,source:$('analyst-source').value};await api('/runs/'+context.run.id+'/decisions',{revision:context.run.revision,decision:d});await loadRun();notify('决策已提交，尚未执行。');});
$('tick').onclick=()=>guarded(async()=>{const id=context.run.id;await api('/runs/'+id+'/tick',{});await openProject(project.id);$('run-select').value=id;await loadRun();notify('已读取执行结果，请据此判断下一步。');});
const taskPanel=node('section',undefined,'panel');
taskPanel.append(node('h2','通用任务计划'),node('p','由分析者规划，系统检查依赖与真实回执。尚未接入自动决策模型。','muted'));
const taskRows=node('div');taskRows.id='task-rows';
const taskChoice=node('select');taskChoice.id='task-choice';
const taskEditor=node('textarea');taskEditor.id='task-plan-json';taskEditor.rows=12;taskEditor.placeholder='粘贴分析者提供的任务计划 JSON';
const taskLoad=node('button','载入当前计划 / 示例','quiet');
const taskSave=node('button','保存任务计划','quiet');
let taskBase=null;
taskLoad.onclick=()=>{if(!context)return;taskBase={id:context.run.id,revision:context.run.revision};taskEditor.value=JSON.stringify(context.run.task_plan||{goal:project.description,rationale:'根据当前需求制定任务与完成条件',source:'local_analyst',tasks:[{id:'research',title:'检索与需求相关的官方资料',action:'search_documents',depends_on:[],completion:{status:'executed','tool_result.status':'passed'}}]},null,2);};
taskSave.onclick=()=>guarded(async()=>{if(!context||!taskBase||taskBase.id!==context.run.id||taskBase.revision!==context.run.revision)throw new Error('请先载入最新运行计划，再提交');context=await api('/runs/'+context.run.id+'/plan',{revision:context.run.revision,plan:JSON.parse(taskEditor.value)});renderRun();taskBase=null;notify('计划已保存，完成状态由真实执行回执决定。');});
taskPanel.append(taskRows,node('label','下一条决策关联的任务'),taskChoice,taskLoad,taskEditor,taskSave);$('analyst-panel').append(taskPanel);
function renderTaskPlan(){taskRows.replaceChildren();taskChoice.replaceChildren();const p=context?.task_progress;if(!p){taskRows.append(node('p','尚未建立任务计划；已有运行仍可沿用原决策入口。','muted'));return;}taskRows.append(node('h3',p.goal),node('p',`第 ${p.version} 版 · 已完成 ${p.completed}/${p.total}`));const names={ready:'可执行',blocked:'等待前置条件',completed:'已完成',needs_review:'待分析结果',needs_input:'待用户补充',stale:'上下文已变化'};for(const t of p.tasks){taskRows.append(node('p',t.title+' · '+names[t.status]),node('p',t.reason+(t.receipt_id?' · 回执 '+t.receipt_id:''),'muted'));if(t.status==='ready'){const o=node('option',t.title);o.value=t.id;taskChoice.append(o);}}}
const readinessPanel=node('div');readinessPanel.id='readiness-panel';readinessPanel.hidden=true;
const readinessSummary=node('section',undefined,'panel'),capabilityRows=node('section',undefined,'panel');
const trainingSummary=node('section',undefined,'panel');
readinessPanel.append(readinessSummary,capabilityRows,trainingSummary);$('workspace').append(readinessPanel);
const readinessTab=node('button','能力与交付检查','tab');readinessTab.dataset.tab='readiness';
readinessTab.onclick=()=>guarded(async()=>{tab('readiness');await renderReadiness();});document.querySelector('.tabs').append(readinessTab);
async function renderReadiness(){if(!project)return;await renderTrainingSummary();const [report,caps]=await Promise.all([api('/projects/'+project.id+'/readiness'),api('/capabilities')]);readinessSummary.replaceChildren(node('h2','离线交付完整性'),node('p',report.offline_status==='needs_work'?'当前交付范围仍有必需环节待完成':'当前声明范围的离线材料已具备'),node('p','开发板烧录与实机验证留待后续，不阻断离线设计交付。','muted'));const names={passed:'已通过',pending:'待完成',not_run:'尚未执行',failed:'未通过',needs_evidence:'待补证据',estimated:'已有估算，待实测',deferred:'留待后续',available:'可用',needs_configuration:'待配置',configured_unverified:'已配置，待调用验证',not_connected:'未接入',not_implemented:'待实现',receive_only_available:'设备发现和只接收日志可用',logs_collected_unverified:'已采集日志，待验收核对',unsupported:'当前不支持'};for(const row of report.checks){const box=node('div',undefined,'candidate');box.append(node('b',row.title+' · '+(names[row.status]||row.status)),node('p',row.reason,'muted'),node('p',row.next_step));readinessSummary.append(box);}capabilityRows.replaceChildren(node('h2','当前 Agent 能力'));const capabilityNames={planning:'任务规划',document_search:'本地资料检索',constraint_check:'约束检查',host_validation:'主机原型验证',armcc_build:'MCU 编译工具',autonomous_decision:'自主决策模型',online_documents:'原厂联网检索与入库',shopping_quotes:'采购报价',hardware_execution:'实物连接与日志'};for(const c of caps.items)capabilityRows.append(node('p',(capabilityNames[c.id]||c.id)+' · '+(names[c.status]||c.status)),node('p',c.detail,'muted'));}
async function renderTrainingSummary(){
 trainingSummary.replaceChildren(node('h2','无开发板阶段训练与检查'));
 try{
  const report=await api('/training/status');
  trainingSummary.append(node('p',report.current_code?'当前版本的离线检查结果':'尚无当前版本检查结果；历史记录仅作参考','muted'));
  for(const stage of report.stages||[])trainingSummary.append(node('p',stage.title+' · '+(stage.status==='passed'?'通过':'未通过')+' · '+stage.tests+'项，跳过'+stage.skipped+'项'));
  if(report.model_holdout)trainingSummary.append(node('p','历史模型迁移测试：'+(report.model_holdout.passed?'单个案例通过':'单个案例未通过')+'；不能据此认定通用独立排错能力。','muted'));
  trainingSummary.append(node('p','本页仅查看报告，不启动模型。开发板、烧录、实机功能与续航实测均未执行。','muted'));
 }catch{trainingSummary.append(node('p','暂时无法读取训练报告，不影响查看项目实际验证记录。','muted'));}
}
let autoRunning=false,autoRunId=null;
const autoPanel=node('section',undefined,'panel');autoPanel.append(node('h2','Agent 自动推进'),node('p','Agent 根据需求和执行结果决定下一步；关键确认时才需要你参与。未接入模型时不会假装自动分析。','muted'));
const autoStart=node('button','开始自动推进','primary'),autoStop=node('button','停止自动推进','quiet'),autoMessage=node('p','点击开始后自动使用当前运行；没有运行时会自动创建。','muted');autoStop.disabled=true;autoPanel.append(autoStart,autoStop,autoMessage);$('user-panel').prepend(autoPanel);
autoStop.onclick=()=>{autoRunning=false;autoStop.disabled=true;autoMessage.textContent='已请求停止；当前正在执行的步骤结束后停止，不重复执行。';};
autoStart.onclick=async()=>{if(autoRunning)return;if(!project)return;if(!context){try{const run=await api('/runs',{project_id:project.id});await listRuns();$('run-select').value=run.id;await loadRun();}catch(e){notify(e.message,true);return;}}autoRunning=true;autoRunId=context.run.id;autoStart.disabled=true;autoStop.disabled=false;startLiveProgress(autoRunId);try{while(autoRunning){autoMessage.textContent='Agent 正在判断或执行，请稍候……';liveStart=Date.now();const result=await api('/runs/'+autoRunId+'/auto',{});autoMessage.textContent=result.message;await refreshModelSettings();if(result.status==='budget_paused'||result.status==='paused')notify(result.message,true);if(context?.run.id===autoRunId){context=result.context;renderRun();}if(result.status!=='continue'){autoRunning=false;break;}if(project?.id!==result.context.project.id||context?.run.id!==autoRunId){autoRunning=false;break;}await new Promise(resolve=>setTimeout(resolve,300));}if(project)await openProject(project.id);}catch{autoMessage.textContent='自动推进连接中断，请刷新查看实际记录；不要重复提交未知执行结果。';}finally{stopLiveProgress();autoRunning=false;autoStart.disabled=false;autoStop.disabled=true;renderRunSummary();}};
const conversation=node('section',undefined,'panel'),conversationQuestion=node('p'),conversationAnswer=node('textarea'),conversationSend=node('button','发送回答并继续','primary'),conversationConfirm=node('button','确认需求并继续','primary'),conversationStatus=node('p',undefined,'muted');
const preliminaryChoice=node('button','按标注假设继续初步设计','quiet');preliminaryChoice.onclick=()=>{conversationAnswer.value='允许按明确标注的假设继续初步设计和文档，复用已有分析与检索结果，不重复已完成且资料未变化的检索。缺失参数列为待核实；原预算和续航目标保留，不得标为已验证；硬件验证保持未执行。';conversationAnswer.focus();};
conversationAnswer.rows=3;conversationAnswer.placeholder='用自然语言回答即可，无需填写 JSON';conversation.append(node('h2','需要你参与的事项'),conversationQuestion,preliminaryChoice,conversationAnswer,conversationSend,conversationConfirm,conversationStatus);$('user-panel').prepend(conversation);
function renderConversation(){const run=context?.run,waiting=!!run&&run.status==='waiting_input'&&!run.pending&&!autoRunning,needsConfirm=project?.status==='needs_input'&&!(project.artifacts.requirements?.questions||[]).some(q=>q.blocking);conversation.hidden=!project;renderPreliminaryChoices();conversationQuestion.textContent=waiting?(run.pause_question||run.observations.at(-1)?.message||'请补充下面的问题。'):'补充需求或回答问题，只需在这里填写一次。';preliminaryChoice.hidden=!waiting;conversationAnswer.hidden=false;conversationSend.hidden=false;conversationSend.disabled=autoRunning;conversationAnswer.setAttribute('aria-label','需求补充与问题回答');conversationSend.textContent=waiting?'提交回答并继续':'提交补充并重新分析';conversationConfirm.hidden=!needsConfirm||waiting;conversationStatus.hidden=false;conversationStatus.textContent='只填写一次即可；提交后同步运行状态。继续分析会使用模型预算，确认需求和选择方案仍由你决定。';$('supplement-form').hidden=true;}
let submittingAnswer=false;
conversationSend.onclick=()=>guarded(async()=>{if(!project||submittingAnswer)return;const message=conversationAnswer.value.trim();if(!message)throw new Error('请先填写补充内容或回答');submittingAnswer=true;conversationSend.disabled=true;try{if(context?.run.status==='waiting_input'&&!context.run.pending){context=await api('/runs/'+context.run.id+'/reply',{revision:context.run.revision,message});conversationAnswer.value='';renderRun();}else{await projectAction('supplement',{message});conversationAnswer.value='';}autoStart.click();}finally{submittingAnswer=false;conversationSend.disabled=false;}});
conversationConfirm.onclick=()=>guarded(async()=>{await projectAction('confirm',{confirmed:true});autoStart.click();});

const preliminaryActions=node('div');conversation.append(preliminaryActions);
function renderPreliminaryChoices(){
 preliminaryActions.replaceChildren();
 if(project?.artifacts.engineering_draft?.firmware)renderSuiteControls(preliminaryActions);
 const diagnostic=project?.artifacts.draft_verification?.host_tests?.assertion_diagnostic;
 if(diagnostic?.actual_values){
  const detail=node('details'),summary=node('summary','最近测试失败的实际读数');detail.append(summary,node('p',diagnostic.file+' 第 '+diagnostic.line+' 行；原断言：'+diagnostic.expression,'muted'));
  const list=node('ul');for(const [name,value] of Object.entries(diagnostic.actual_values))list.append(node('li',name+'：实际 '+value));
  if(diagnostic.call_trace?.length){const trace=node('ul');for(const item of diagnostic.call_trace)trace.append(node('li',item.caller+' → '+item.callback+'：'+item.count+'次（'+item.file+':'+item.line+'）'));detail.append(node('p','输出调用来源','muted'),trace);}
  detail.append(list,node('p','来自独立诊断重放，原测试与失败结果保持不变。','muted'));preliminaryActions.append(detail);
 }
 if(project?.status==='preliminary_design'){
  preliminaryActions.append(node('p','已进入初步设计，现有证据和未解决事项已保留。可以直接生成文档包，无需再调用模型分析。','muted'));
  const exportDraft=node('button','生成现有初步设计文档包（不调用模型）','primary');
  exportDraft.onclick=()=>guarded(async()=>{await projectAction('execute');tab('user');notify('初步设计文档包已生成，请点击下载项目交付包。未生成的源码或图纸不会标为已完成。');});
  preliminaryActions.append(exportDraft);return;
 }
 if(project?.artifacts.preliminary_acceptance&&['documents_delivered','draft_in_progress','draft_ready','draft_verified','draft_verification_failed'].includes(project.status)){
  const draft=project.artifacts.engineering_draft;
  preliminaryActions.append(node('p','工程草案：'+(draft?['interfaces','circuit','firmware'].map(k=>({interfaces:'接口表',circuit:'连接图',firmware:'C源码'}[k])+': '+(draft[k]?'文件已保存':'待生成')).join('；'):'尚未生成接口表、连接图和源码。已有下载包仅含研究资料。'),'muted'));
  if(project.status==='documents_delivered'&&draft?.interfaces&&draft?.circuit&&draft?.firmware){
   preliminaryActions.append(node('p',project.artifacts.product_documents?'交付包包含详细产品设计、制作说明、元件清单、图纸与代码草案。电气审查与实机验证未执行。':'图纸与代码草案已打包。软件结果见下方验证范围；电气审查与硬件验证未执行。','muted'));
   const download=node('a',project.artifacts.product_documents?'下载完整设计与代码交付包 ↓':'下载图纸与代码草案包 ↓','download');download.href='/projects/'+project.id+'/download';preliminaryActions.append(download);
   if(project.artifacts.product_documents){const preview=node('a','查看产品设计与元件清单','download');preview.href='/projects/'+project.id+'/product-design';preview.target='_blank';preview.rel='noopener';preliminaryActions.append(preview);}
   if(project.artifacts.draft_verification?.status!=='passed'){
    const verify=node('button','让智能体编译、测试并修复（计入预算）','primary');
    verify.onclick=()=>guarded(async()=>{await projectAction('start_draft',{confirmed:true});const run=await api('/runs',{project_id:project.id,max_steps:10,max_repairs:3});await listRuns();$('run-select').value=run.id;await loadRun();autoStart.click();});preliminaryActions.append(verify);
   }
   return;
  }
  if(project.status==='documents_delivered'){
   const start=node('button','继续生成图纸与代码草案（保留现有方案）','primary');
   start.onclick=()=>guarded(async()=>{await projectAction('start_draft',{confirmed:true});if(context)context=await api('/runs/'+context.run.id+'/refresh',{revision:context.run.revision}).then(()=>api('/runs/'+context.run.id));renderRun();notify('工程草案流程已开启。点击开始自动推进将调用模型并计入每日预算。');});preliminaryActions.append(start);
  }
  if(project.status==='draft_verified'){
   const pack=node('button','打包已生成的图纸与代码（不调用模型）','primary');pack.onclick=()=>guarded(()=>projectAction('execute'));preliminaryActions.append(pack);
  }
  return;
 }
 const round=project?.artifacts.design_loop?.rounds?.at(-1);
 const candidates=round?.plan?.candidates|| (project?.artifacts.selected_plan?[project.artifacts.selected_plan]:[]);
 const options=candidates.filter(c=>project.artifacts.power_estimates?.[c.id]);
 if(!options.length)return;
 preliminaryActions.append(node('p','正式进入初步设计：选择已有估算的方案。预算、续航、资源与硬件验证保持原结果；只接受带待核实项的初步设计，不代表验收通过。','question'));
 for(const c of options){
  const saved=project.artifacts.power_estimates[c.id];
  const choose=node('button','保留待验证项，按「'+(c.name||c.id)+'」进入初步设计（不调用模型）','quiet');
  choose.onclick=()=>guarded(async()=>{
   await projectAction('proceed_estimated_design',{candidate_id:c.id,confirmed:true,accept_open_items:true,rationale:'用户通过明确的初步设计入口选择此候选；接受已保存估算中的假设、缺口与未解决事项。保持原验收目标，不声明预算、续航、资源或硬件已通过。'});
   renderConversation();notify('已进入初步设计，原检索和估算保留；可直接生成现有文档包。');
  });
  preliminaryActions.append(node('p',(c.name||c.id)+' · '+(labels[saved.report?.status]||saved.report?.status||'已保存估算'),'muted'),choose);
 }
}

function renderSuiteControls(container){
 const id=project.id,a=project.artifacts,suite=a.draft_test_suite,check=a.draft_verification;
 const panel=node('div');panel.append(node('h3','软件验证与修复'));
 panel.append(node('p',suite?`已冻结 ${Object.keys(suite.cases).length} 类扩展测试；交付必须同时通过原测试及扩展测试。`:'当前仅检查原测试；可关联本项目已有的扩展边界用例。','muted'));
 if(check){const original=check.original_host_tests||check.host_tests;
  panel.append(node('p','MCU 编译：'+(labels[check.mcu_compile?.status]||'未执行')+' · 原测试：'+(labels[original?.status]||'未执行')+' · 扩展测试：'+(suite?(labels[check.supplemental_tests?.status]||'未执行'):'未关联'),'muted'));
 }
 const cpu=node('select');cpu.setAttribute('aria-label','编译目标CPU');cpu.append(node('option','选择已确定的芯片内核'));cpu.firstChild.value='';
 for(const name of ['Cortex-M0','Cortex-M0plus','Cortex-M3','Cortex-M4']){const option=node('option',name);option.value=name;cpu.append(option);}
 cpu.value=a.draft_validation_cpu||check?.mcu_compile?.cpu||'';
 const verify=node('button','运行全部测试（不调用模型）','quiet');
 verify.onclick=()=>guarded(async()=>{if(!cpu.value)throw new Error('请先选择与芯片一致的CPU内核');const chosen=cpu.value;
  if(['documents_delivered','draft_verified'].includes(project.status))await projectAction('start_draft',{confirmed:true});
  autoMessage.textContent='正在本地编译并运行原测试及已关联扩展测试，不调用模型。';
  await projectAction('draft_verify',{cpu:chosen});autoMessage.textContent=project.status==='draft_verified'?'全部已关联软件检查通过，可打包。':'测试未通过，具体错误已保存；可让智能体定向修复。';
 });
 panel.append(cpu,verify);
 if(project.status==='draft_verification_failed'){
  const repair=node('button','让智能体修复并复测（计入预算）','primary');
  repair.onclick=()=>guarded(async()=>{const run=await api('/runs',{project_id:id,max_steps:20,max_repairs:3});await listRuns();$('run-select').value=run.id;await loadRun();autoStart.click();});panel.append(repair);
 }
 container.append(panel);
 if(!suite)api('/projects/'+id+'/test_suites').then(result=>{
  if(project?.id!==id||!panel.isConnected)return;
  const candidate=result.suites?.[0];if(!candidate)return;
  const attach=node('button',`关联已有 ${candidate.count} 类扩展测试`,'quiet');
  attach.onclick=()=>guarded(async()=>{await projectAction('draft_tests',{suite_id:candidate.id,confirmed:true});notify('扩展用例已冻结，旧验证结果已失效。请运行全部测试；关联本身不调用模型。');});panel.append(attach);
 }).catch(()=>{if(panel.isConnected)panel.append(node('p','已有扩展用例列表暂不可读，未自动忽略或替换测试。','muted'));});
}

const keilPanel=node('section',undefined,'panel'),keilPath=node('input'),keilTarget=node('input'),keilAck=node('input'),keilImport=node('button','导入副本并构建','primary'),keilRebuild=node('button','重新构建','quiet'),keilResult=node('div');
keilPath.placeholder='当前工作空间内 .uvprojx 或 .uvproj 文件的完整路径';keilTarget.placeholder='单目标可留空；多目标需填写 Target 名称';keilAck.type='checkbox';const keilLabel=node('label');keilLabel.append(keilAck,document.createTextNode(' 我确认这是可信本地工程，允许复制并调用 Keil 构建；仅修改副本'));
keilPanel.append(node('h2','现有 Keil 工程'),node('p','无需开发板。构建与错误修复使用独立副本，原始工程保持不变。','muted'),keilPath,keilTarget,keilLabel,keilImport,keilRebuild,keilResult);$('user-panel').append(keilPanel);
keilImport.onclick=()=>guarded(async()=>{if(!keilAck.checked)throw new Error('请先确认可信工程与构建副本授权');await projectAction('keil_import',{file:keilPath.value.trim(),target:keilTarget.value.trim()||null,confirmed:true});keilAck.checked=false;await projectAction('keil_build');});
keilRebuild.onclick=()=>guarded(()=>projectAction('keil_build'));
function renderKeil(){if(!project)return;const info=project.artifacts.keil_project,result=project.artifacts.keil_build;keilRebuild.disabled=!info||!['ready_keil_build','keil_build_failed'].includes(project.status);keilResult.replaceChildren();if(!info)return;keilResult.append(node('p','目标：'+info.target+' · 器件：'+(info.device||'未标明')),node('p','可读取和修改的源码：'+Object.keys(info.editable).length+' 个；未执行烧录或实机运行。','muted'));if(result){keilResult.append(node('h3',labels[result.status]||result.status));if(result.reason)keilResult.append(node('p',result.reason,'question'));for(const d of result.diagnostics||[])keilResult.append(node('p',d.file+':'+d.line+' · '+d.severity+' · '+d.message));const detail=node('details');detail.append(node('summary','完整构建日志'),node('pre',result.log||result.reason||'暂无日志','log'));keilResult.append(detail);}}
let hardwareDevices=[];
const hardwarePanel=node('section',undefined,'panel'),hardwareScan=node('button','自动识别连接设备','quiet'),hardwareNotice=node('p','自动读取端口和USB信息；不会打开串口。','muted'),hardwareSelect=node('select'),hardwareBaud=node('input'),hardwareLabel=node('input'),hardwareAck=node('input'),hardwareBind=node('button','授权此端口只接收日志','primary'),hardwareRead=node('button','采集3秒日志','quiet'),hardwareReport=node('div');
hardwareBaud.type='number';hardwareBaud.value='115200';hardwareBaud.min=300;hardwareBaud.max=3000000;hardwareLabel.placeholder='板卡型号备注（可选，不视为已核实）';hardwareAck.type='checkbox';const hardwareConsent=node('label');hardwareConsent.append(hardwareAck,document.createTextNode(' 允许打开选定串口只接收日志；部分板卡打开串口时可能复位'));
hardwarePanel.append(node('h2','实物连接'),hardwareScan,hardwareNotice,hardwareSelect,node('label','波特率（需与板上程序一致，当前建议值115200）'),hardwareBaud,hardwareLabel,hardwareConsent,hardwareBind,hardwareRead,hardwareReport);$('user-panel').append(hardwarePanel);
hardwareScan.onclick=()=>guarded(async()=>{const found=await api('/hardware/devices');hardwareDevices=found.ports||[];hardwareSelect.replaceChildren();for(const p of hardwareDevices){const option=node('option',p.device+' · '+(p.description||'无描述'));option.value=p.fingerprint;hardwareSelect.append(option);}hardwareNotice.textContent=found.reason+'；USB枚举：'+(found.usb.status==='passed'?found.usb.devices.length+'项（含电脑自带设备，不等于开发板）':found.usb.reason)+'。型号库不完整，主控与板卡尚未核实。';hardwareReport.replaceChildren();const details=node('details');details.append(node('summary','查看自动检测依据'),node('pre',JSON.stringify(found,null,2),'log'));hardwareReport.append(details);});
hardwareBind.onclick=()=>guarded(async()=>{if(!hardwareAck.checked)throw new Error('请确认选定端口和只接收权限');const selected=hardwareDevices.find(p=>p.fingerprint===hardwareSelect.value);if(!selected)throw new Error('请先自动识别并选择串口');await projectAction('hardware_bind',{port:selected.device,fingerprint:selected.fingerprint,baudrate:Number(hardwareBaud.value),board_label:hardwareLabel.value,confirmed:true});hardwareAck.checked=false;});
hardwareRead.onclick=()=>guarded(()=>projectAction('hardware_capture',{seconds:3}));
function renderHardware(){if(!project)return;const binding=project.artifacts.hardware_binding,captures=project.artifacts.hardware_captures||[];hardwareRead.disabled=!binding;hardwareReport.replaceChildren();if(binding)hardwareReport.append(node('p','已授权：'+binding.port.device+' · '+binding.baudrate+' baud · 只接收；板卡型号未核实。'));const last=captures.at(-1);if(last)hardwareReport.append(node('p',last.status==='captured'?'收到 '+last.bytes+' 字节；仅日志采集，不代表功能验收通过。':last.status==='no_data'?'本次未收到数据；不能据此判断程序是否正常。':last.error,'question'),node('pre',last.text||'（无文本数据）','log'),node('p','原始字节 SHA-256：'+last.sha256,'muted'));}
let selectedPage=null;
let powerBase=null,powerProject=null;
const powerTab=node('button','功耗估算','tab');powerTab.dataset.tab='power';powerTab.onclick=()=>{tab('power');renderPower();};document.querySelector('.tabs').append(powerTab);
function loadPowerModel(){if(!project)return;const cid=$('power-candidate').value,saved=project.artifacts.power_estimates?.[cid];$('power-json').value=JSON.stringify(saved?.model||{},null,2);powerBase={id:project.id,revision:project.revision,candidate_id:cid};$('power-ack').checked=false;renderPowerReport();}
function renderPower(){if(!project)return;const list=project.artifacts.design_loop?.rounds.at(-1).plan.candidates||(project.artifacts.selected_plan?[project.artifacts.selected_plan]:[]),old=$('power-candidate').value,switched=powerProject!==project.id;$('power-candidate').replaceChildren(...list.map(c=>{const o=node('option',c.name);o.value=c.id;return o;}));if(!switched&&list.some(c=>c.id===old))$('power-candidate').value=old;if(switched){powerProject=project.id;loadPowerModel();}else renderPowerReport();}
function renderPowerReport(){const cid=$('power-candidate').value,saved=project?.artifacts.power_estimates?.[cid],area=$('power-report');area.replaceChildren();$('power-proceed').disabled=!saved||saved.report.status==='insufficient_data';if(!saved){area.append(node('p','尚未保存该候选的估算，由分析者提供工况和功率范围。','muted'));return;}const report=saved.report;area.append(node('h3',labels[report.status]||report.status),node('p','目标 '+report.target_hours+' 小时 · 预算待核价 · 实机未测试','question'),node('p',saved.model.scope,'muted'),node('p','工况依据：'+saved.model.schedule_basis,'muted'),node('p','电池依据：'+saved.model.battery.basis,'muted'));for(const key of ['typical','conservative']){const s=report.scenarios[key],box=node('section',undefined,'candidate');box.append(node('h3',(key==='typical'?'典型情景':'保守情景')+' · '+(labels[s.status]||s.status)));if(s.required_wh!==undefined)box.append(node('p',`预计续航：${s.estimated_hours??'无法给出有限值'} 小时；电池侧平均功率：${s.average_battery_mw} mW`),node('p',`可用能量 ${s.available_wh} Wh / 目标耗能 ${s.required_wh} Wh / 余量 ${s.margin_wh} Wh`,'muted'));for(const row of s.states)box.append(node('p',`${row.name}：${row.load_mw??'未知'} mW，${row.seconds??'未知'} 秒；依据：${row.basis}`,'muted'));area.append(box);}area.append(node('p','峰值供电：'+(labels[report.peak.status]||report.peak.status)+'；'+report.peak.basis,'question'));if(report.missing_inputs.length)area.append(node('p','待补估值：'+report.missing_inputs.join('、'),'muted'));area.append(node('p','估算基于声明的假设与平均工况，不是续航实测。峰值、机构与引脚须另行验证。','muted'));}
$('power-candidate').onchange=loadPowerModel;$('power-load').onclick=loadPowerModel;
$('power-copy').onclick=()=>guarded(()=>copy(project.artifacts.power_estimates?.[$('power-candidate').value]||{note:'尚无估算'}));
$('power-save').onclick=()=>guarded(async()=>{if(!powerBase||powerBase.id!==project.id||powerBase.revision!==project.revision)throw new Error('项目版本变化，请载入当前估算后重新编辑');await projectAction('power_estimate',{candidate_id:$('power-candidate').value,model:JSON.parse($('power-json').value)});loadPowerModel();notify('估算已保存，结果未标记为实测。');});
$('power-proceed').onclick=()=>guarded(async()=>{if(!$('power-ack').checked)throw new Error('请明确接受报告中的未解决事项');const cid=$('power-candidate').value,saved=project.artifacts.power_estimates?.[cid];if(JSON.stringify(JSON.parse($('power-json').value))!==JSON.stringify(saved?.model))throw new Error('估算输入尚未保存，请先计算');await projectAction('proceed_estimated_design',{candidate_id:cid,confirmed:true,accept_open_items:true,rationale:$('power-reason').value});loadPowerModel();notify('已记录初步设计范围；预算与实测仍待验证。');});
let designBase=null,designProjectId=null;
const designTab=node('button','方案推演','tab');designTab.dataset.tab='design';designTab.onclick=()=>{tab('design');renderDesign();};document.querySelector('.tabs').append(designTab);
function renderDesign(){if(!project)return;if(designProjectId!==project.id){$('design-json').value='';designBase=null;designProjectId=project.id;}const loop=project.artifacts.design_loop,r=loop?.rounds.at(-1);$('design-summary').textContent=r?`第 ${r.number} 轮 · ${r.plan.scope} · 分析来源：${r.plan.analyst}\n判断：${r.plan.rationale}`:'尚未提出本轮候选。由分析者拆解约束，提出至少两种方案并安排研究任务。';for(const id of ['design-options','design-tasks','design-history','design-gaps','design-recommendation'])$(id).replaceChildren();$('design-search-next').disabled=!r||r.status==='accepted'||r.research_results.length===r.plan.tasks.length;$('design-evaluate').disabled=!r||r.status==='accepted'||!r.research_results.length;if(!r)return;
 if(r.recommendation){const rec=r.recommendation;$('design-recommendation').append(node('b',(rec.status==='conditional'?'条件式研究建议：':'通过声明约束后的建议：')+rec.candidate_id),node('p',rec.rationale),node('p','依据：'+rec.observation_ids.join('、'),'muted'));}
 for(const c of r.plan.candidates){const e=r.evaluations.find(e=>e.candidate_id===c.id),box=node('section',undefined,'panel');box.append(node('h2',c.name+' · '+(e?(labels[e.report.status]||e.report.status):'尚未检查')),node('p',c.architecture),node('p','组件：'+c.components.map(x=>x.role+'＝'+(x.model||'待定')).join('；'),'muted'),node('p','取舍：'+c.tradeoffs.join('；'),'muted'),node('p','风险：'+c.risks.join('；'),'muted'),node('p','假设：'+c.assumptions.join('；'),'question'));for(const check of e?.report.checks||[]){const detail=node('details');detail.append(node('summary',check.objective_id+' · '+(labels[check.status]||check.status)+' · 情景计算：'+(labels[check.calculation_status]||check.calculation_status)),node('p',check.observation_id,'muted'),node('pre',JSON.stringify({detail:check.detail,missing_inputs:check.missing_inputs,binding_errors:check.binding_errors},null,2),'log'));box.append(detail);}if(e?.uncovered_requirements.length)box.append(node('p','未覆盖需求：'+e.uncovered_requirements.join('、'),'question'));const select=node('button',r.accepted_candidate===c.id?'已确认此方案':'确认此方案','quiet');select.disabled=!e?.eligible||r.status==='accepted';select.onclick=()=>guarded(()=>projectAction('design_accept',{candidate_id:c.id,confirmed:true}));box.append(select);$('design-options').append(box);}
 for(const gap of r.gaps||[]){const d=node('div',undefined,'question');d.append(node('b',gap.candidate_id+' / '+gap.objective_id+' · '+gap.observation_id),node('p',gap.suggested_next),node('p','缺失输入：'+(gap.missing_inputs.join('、')||'无')+'；未绑定参数：'+gap.binding_errors.map(x=>x.field).join('、')));if(gap.note)d.append(node('p',gap.note));$('design-gaps').append(d);}if(!r.gaps?.length)$('design-gaps').append(node('p',r.evaluations.length?'声明约束暂无缺口，仍需核对功能覆盖和实机验证。':'执行检索和比较后会列出证据缺口。','muted'));
 for(const t of r.plan.tasks){const result=r.research_results.find(x=>x.task_id===t.id),d=node('div',undefined,'candidate');d.append(node('b',t.question),node('p','检索词：'+t.query+'；原因：'+t.why,'muted'),node('p',result?(result.status==='references_found'?'找到来源，参数仍待审核':'没有命中，应调整检索或补充资料')+' · '+result.observation_id:'待检索'));for(const m of result?.matches||[]){const link=node('a',m.citation+' · '+m.title);link.href=m.file_url;link.target='_blank';link.rel='noopener';d.append(link,node('p',m.excerpt.slice(0,450),'muted'));}$('design-tasks').append(d);}
 for(const old of loop.rounds){const d=node('details',undefined,'history-item');d.append(node('summary','第 '+old.number+' 轮 · '+old.status),node('p',old.plan.rationale));for(const change of old.plan.changes||[])d.append(node('p',change.candidate_id+'：'+change.reason+'；依据：'+change.observation_ids.join('、')));$('design-history').append(d);}}
$('design-copy').onclick=()=>guarded(async()=>{await copy({project,contract:'plan: analyst,scope,rationale,objectives[{id,kind,description,requirement_ids,fixed_inputs}],candidates[{id,name,architecture,covers,components,tradeoffs,risks,assumptions,proposal}],tasks[{id,question,query,why,candidate_ids}]；调整追加 changes、response_to'});designBase={id:project.id,revision:project.revision};});
$('design-json').oninput=()=>{if(!designBase)designBase={id:project.id,revision:project.revision};};
$('design-submit').onclick=()=>guarded(async()=>{if(!designBase||designBase.id!==project.id||designBase.revision!==project.revision)throw new Error('请先复制最新上下文，再根据当前观察提交候选');await projectAction('design_plan',{plan:JSON.parse($('design-json').value)});designBase=null;$('design-json').value='';notify('候选已保存，等待真实检索与检查。');});
$('design-search-next').onclick=()=>guarded(async()=>{const r=project.artifacts.design_loop.rounds.at(-1),task=r.plan.tasks.find(t=>!r.research_results.some(x=>x.task_id===t.id));if(task)await projectAction('design_research',{task_id:task.id});});
$('design-evaluate').onclick=()=>guarded(()=>projectAction('design_evaluate'));
$('check-selection').onclick=()=>guarded(async()=>{if(!project)throw new Error('请先创建或选择项目');const p=await api('/projects/'+project.id+'/selection_check',{revision:project.revision,proposal:JSON.parse($('selection-proposal').value)});await openProject(p.id);$('selection-evidence-result').textContent=JSON.stringify(p.artifacts.selection_check,null,2);notify('选型检查已保存：'+(labels[p.status]||p.status));});
$('continue-selection').onclick=()=>guarded(async()=>{if(!project||project.status!=='selection_checked')throw new Error('请先通过当前方案的选型检查');const p=await api('/projects/'+project.id+'/continue_selection',{revision:project.revision,confirmed:true});await openProject(p.id);notify('已确认选型，进入下一阶段。');});
const knowledgeTab=node('button','资料与证据','tab');knowledgeTab.dataset.tab='knowledge';
knowledgeTab.onclick=()=>guarded(async()=>{tab('knowledge');const status=await api('/knowledge/status');$('library-status').textContent=status.ready?`${status.documents} 份资料 · ${status.chunks} 个页面片段${status.catalog_current?'':' · 目录已变更，需重建索引'}`:'尚未建立索引';await refreshParameters();await refreshWebResearch();});
document.querySelector('.tabs').append(knowledgeTab);
async function refreshParameters(){const data=await api('/knowledge/parameters');$('parameter-list').replaceChildren();for(const p of data.parameters){const item=node('div',undefined,'candidate');item.append(node('b',p.valid?`${p.model} · ${p.parameter} = ${p.value} ${p.unit}`:p.id+' · 来源失效'),node('p',p.valid?`${p.citation} · ${p.conditions} · 审核：${p.reviewer}`:p.reason,'muted'));if(p.valid){const b=node('button','复制选型绑定','quiet');b.onclick=()=>guarded(()=>copy({parameter_id:p.id,model:p.model,conditions:p.conditions}));item.append(b);} $('parameter-list').append(item);}if(data.facts?.length)$('parameter-list').append(node('h3','已核对的原文关系'));for(const f of data.facts||[]){const item=node('div',undefined,'candidate');item.append(node('b',f.valid?`${f.model} · ${f.subject} → ${f.predicate} → ${f.object}`:f.id+' · 来源失效'),node('p',`${f.document_id} p.${f.page} · ${f.conditions} · 原文关系核对，不代表封装引出、完整分配或实机通过`,'muted'));$('parameter-list').append(item);}}
$('knowledge-search').onsubmit=e=>{e.preventDefault();guarded(async()=>{const data=await api('/knowledge/search',{query:$('knowledge-query').value,document_id:$('knowledge-document').value.trim()||null});$('knowledge-results').replaceChildren();if(!data.matches.length)$('knowledge-results').append(node('p','没有匹配。试用具体型号和较短的关键词；英文资料也可用英文检索。','muted'));for(const m of data.matches){const item=node('div',undefined,'candidate');item.append(node('b',m.title),node('p',m.citation+' · 未审核','muted'),node('p',m.excerpt.slice(0,1000)));const b=node('button','读取此页','quiet');b.onclick=()=>guarded(async()=>{selectedPage=await api('/knowledge/page',{document_id:m.document_id,page:m.page});$('knowledge-citation').textContent=selectedPage.citation+' · SHA-256 '+selectedPage.sha256;$('knowledge-page').textContent=selectedPage.text;$('knowledge-original').href=selectedPage.file_url;$('knowledge-original').hidden=false;$('parameter-quote').value='';$('parameter-confirmed').checked=false;});item.append(b);$('knowledge-results').append(item);}});};
$('parameter-review').onsubmit=e=>{e.preventDefault();guarded(async()=>{if(!selectedPage)throw new Error('请先读取原文页面');const record=await api('/knowledge/parameters',{document_id:selectedPage.document_id,page:selectedPage.page,model:$('parameter-model').value,parameter:$('parameter-name').value,value:Number($('parameter-value').value),unit:$('parameter-unit').value,conditions:$('parameter-conditions').value,quote:$('parameter-quote').value,reviewer:$('parameter-reviewer').value,rationale:$('parameter-rationale').value,confirmed:$('parameter-confirmed').checked});await refreshParameters();$('parameter-confirmed').checked=false;notify('审核记录已保存：'+record.id+'。尚未执行选型检查。');});};
guarded(async()=>{await listProjects();const remembered=localStorage.getItem('embedded-project');if(remembered){try{await openProject(remembered);}catch{localStorage.removeItem('embedded-project');notify('原项目无法读取，请从列表选择。',true);}}});
async function refreshModelSettings(fill=false){
  const data=await api('/model/settings');
  if(data.online){document.querySelector('#model-settings-panel p').textContent='使用你自己的DeepSeek API。密钥经HTTPS发送至在线服务，仅在当前服务会话内存使用；退出、到期或重启后需重新填写。保存不调用模型，发送对话、测试连接和自动推进会产生费用。当前仅支持DeepSeek官方地址；编译与硬件操作需本机或隔离执行器。';$('model-clear').textContent='清除当前会话 API';$('model-endpoint').readOnly=true;}
  if(fill){$('model-choice').value=data.custom?'custom':data.model;$('model-enabled').checked=data.enabled;$('model-endpoint').value=data.endpoint;$('model-custom-name').value=data.model;for(const k of ['hit','input','output'])$('model-price-'+k).value=data.prices[k];$('model-output-limit').value=data.output_limit;showCustomModel();}
  $('model-connection-status').textContent=(data.enabled?'已启用 · ':'未启用 · ')+(data.key_saved?(data.online?'密钥仅保存在当前服务会话内存':'密钥已加密保存'):'尚未填写密钥')+' · '+data.model;
  const b=data.budget;const resume=$('model-resume');if(resume)resume.hidden=!b.uncertain;
  $('model-budget-status').textContent=`今日 ${b.date} · 保守计费 ¥${b.accounted_cny.toFixed(4)} / ¥10 · 剩余 ¥${b.remaining_cny.toFixed(4)} · 输入 ${b.prompt_tokens} / 输出 ${b.completion_tokens} token · 已调用 ${b.completed_calls} 次 · 最近输入 ${b.last_prompt_tokens} token`+(b.reserved_cny?` · 含预留 ¥${b.reserved_cny.toFixed(4)}`:'')+(b.paused?' · 已暂停模型调用':'');
  $('model-budget-status').textContent+=' · 缓存命中 '+(b.cache_hit_ratio==null?'尚无新统计':(b.cache_hit_ratio*100).toFixed(1)+'%')+'（仅统计升级后 '+(b.cache_measured_calls||0)+' 次请求）';
  $('model-budget-status').className=b.paused?'question':'';
  const p=data.custom?data.prices:(data.models[$('model-choice').value]||data.prices);
  $('model-prices').textContent=`每百万token：缓存命中 ¥${p.hit}，未命中输入 ¥${p.input}，输出 ¥${p.output}（自定义服务按填写价格估算；DeepSeek按高峰价）。每次最多输出 ${data.output_limit} token。`;
  const footer=document.querySelector('.sidebar-footer');
  footer.textContent=data.online?'在线工作台 · 自备 API':(data.enabled?'本地Agent · 模型已配置':'本地分析者协作模式');
  footer.append(node('small',data.online?'当前访客会话独立计费 · 请及时下载交付物':'每日10元测试预算 · 项目保存在本机'));
  if(data.online&&!$('online-session-note')){const note=node('p','在线版：项目与其他访客隔离；密钥仅在服务会话内存保留，会话8小时有效。编译、烧录与实机测试需本机工具或隔离执行器。请在退出前下载交付物。','mode-note');note.id='online-session-note';document.querySelector('main').prepend(note);const leave=node('button','退出在线会话','quiet');leave.type='button';leave.onclick=()=>guarded(async()=>{await api('/session/logout',{});localStorage.removeItem('embedded-project');location.reload();});const draftDownload=node('button','下载当前项目草案（未验证）','quiet');draftDownload.type='button';draftDownload.onclick=()=>{if(project)location.href='/projects/'+project.id+'/source-download';else notify('请先打开一个项目。',true);};footer.append(draftDownload,leave);}
  document.querySelector('#analyst-panel .mode-note').textContent=data.enabled?'已启用模型自动决策，可在项目操作中开始自动推进；仍可手动提交分析。':'尚未启用自主模型；可手动提交分析或在模型设置中接入。';
  return data;
}
$('model-settings-form').onsubmit=e=>{e.preventDefault();guarded(async()=>{try{await api('/model/settings',modelPayload());}finally{$('model-key').value='';}await refreshModelSettings(true);notify('模型配置已保存，尚未发起付费调用。进入项目后点击“开始自动推进”。');});};
$('model-choice').onchange=()=>{showCustomModel();if($('model-choice').value!=='custom')$('model-endpoint').value='https://api.deepseek.com/chat/completions';};
$('model-endpoint').oninput=()=>{if($('model-endpoint').value!=='https://api.deepseek.com/chat/completions'){$('model-choice').value='custom';showCustomModel();}};
$('model-test').onclick=()=>guarded(async()=>{try{const data=await api('/model/test',{});notify(data.message);}finally{await refreshModelSettings();}});
$('model-clear').onclick=()=>guarded(async()=>{await api('/model/settings',{clear_key:true});$('model-key').value='';await refreshModelSettings(true);notify('本机密钥已移除；预算记录保留。');});
refreshModelSettings(true).catch(e=>notify(e.message,true));

const liveProgress=node('p','尚未开始执行。','muted');liveProgress.setAttribute('role','status');
const liveHistory=node('div');const liveDetails=node('details');liveDetails.append(node('summary','查看最近运行过程'),liveHistory);
const continueRound=node('button','保留项目，开始新一轮','quiet');
const researchAgain=node('button','重新自主查资料（保留现有成果）','quiet');researchAgain.id='research-again';
const researchOptions=node('details');researchOptions.append(node('summary','更多操作'),researchAgain);
const updateProductDocs=node('button','更新设计文档与元件清单（计入预算）','quiet');
researchOptions.append(updateProductDocs);
updateProductDocs.onclick=()=>guarded(async()=>{
 if(autoRunning)return;
 updateProductDocs.disabled=true;
 try{notify('Agent 正在根据现有工程编写设计文档与元件清单，请等待；不修改源码或验收。');await projectAction('product_documents',{});await refreshModelSettings();notify('设计文档与元件清单已加入交付包，可从上方下载。');}
 finally{updateProductDocs.disabled=false;}
});
const researchReport=node('section');researchReport.setAttribute('aria-label','PWM专项报告');
autoPanel.append(researchReport,liveProgress,liveDetails,continueRound,researchOptions);
let liveTimer=null,livePolling=false,liveSequence=-1,liveStart=0;
function renderRunSummary(){
 const ended=context?.run.status==='complete';
 autoStart.hidden=ended&&!autoRunning;autoStop.hidden=!autoRunning;
 liveProgress.hidden=!autoRunning&&ended;researchOptions.hidden=project?.status!=='documents_delivered';
 updateProductDocs.disabled=autoRunning;
 researchReport.replaceChildren();const report=context?.run.research_report;
 if(report){
  researchReport.append(node('h3',report.status==='passed'?'接线证据检查通过':'接线证据仍有缺口'),node('p','实机验证未执行。','muted'));
  const wiring=node('details');wiring.append(node('summary','查看接线与证据'));
  for(const [title,rows] of [['PWM',report.mappings],['语音UART',report.voice_pins]])for(const m of rows||[])wiring.append(node('p',`${title} · ${m.pin}（${report.package} 第${m.physical_pin||'待核对'}脚） → ${m.af} → ${m.signal}`));
  wiring.append(node('p',report.scope,'muted'));researchReport.append(wiring);
  for(const gap of report.gaps||[])researchReport.append(node('p',gap,'question'));
  const later=node('details');later.append(node('summary','后续待验证事项'));
  for(const item of [...(report.deferred||[]),...(report.model_concerns||[])])later.append(node('p',item,'muted'));researchReport.append(later);
 }

 researchAgain.hidden=project?.status!=='documents_delivered';researchAgain.disabled=autoRunning;
 if(context?.run.status==='complete'&&context?.run.evidence_completion){autoMessage.textContent=context.run.evidence_completion.status==='verified'?'本轮取证目标已验证，原工程与硬件验收状态不变。':'本轮取证已结束，目标仍有证据缺口；未标为验证通过。已有工程成果保留。';autoStart.disabled=true;continueRound.hidden=true;return;}
 if(project?.status==='documents_delivered'&&!(context?.run.scope==='research_only'&&context?.run.status!=='complete')){autoMessage.textContent=report?'本轮已结束，结果见下方。':'本轮已完成。可下载交付包；要测试自主取证，请点击“重新自主查资料”。调用计入每日10元预算。';autoStart.disabled=true;continueRound.hidden=true;return;}
 autoStart.disabled=autoRunning;

  if(!context)return;
  const r=context.run;continueRound.hidden=!(r.steps>=r.max_steps||(r.auto_errors||0)>=3||['complete','budget_exhausted','repair_limit'].includes(r.status));
  if(!autoRunning&&r.steps>=r.max_steps)autoMessage.textContent=`本轮已执行 ${r.steps}/${r.max_steps} 步，达到步骤上限。可保留项目开始新一轮；费用额度不重置。`;
  else if(!autoRunning&&(r.auto_errors||0)>=3)autoMessage.textContent='连续三次提交未通过校验，已暂停避免继续花费。最近原因：'+(r.auto_feedback?.message||'请查看执行记录');
}
async function pollLiveProgress(){
  if(livePolling||!autoRunId)return;livePolling=true;
  try{const p=await api('/runs/'+autoRunId+'/progress');
    const phase={reading:'整理上下文',model:'等待模型响应',validating:'校验参数',tool:'执行工具',planning:'校验计划',ready:'准备下一步',paused:'已暂停',idle:'等待请求开始'}[p.phase]||p.phase;
    const elapsed=Math.floor(p.elapsed_seconds||0);
    liveProgress.textContent=`${phase} · 本次请求已等待 ${elapsed} 秒`+(p.action?' · '+(actionLabels[p.action]||p.action):'')+' · '+p.detail+(p.phase==='model'&&elapsed>30?'（尚未收到模型响应，不代表已卡死；模型请求设有90秒超时）':'');
    if(p.sequence!==liveSequence){liveSequence=p.sequence;liveHistory.replaceChildren();for(const h of p.history||[]){liveHistory.append(node('p',new Date(h.updated_at*1000).toLocaleTimeString()+' · '+(h.action?(actionLabels[h.action]||h.action)+' · ':'')+h.detail+(h.rationale?'；简要依据：'+h.rationale:'')));}}
  }catch{liveProgress.textContent='暂时无法读取服务进度；当前请求结果未确认，请勿重复提交。';}
  finally{livePolling=false;}
}
function startLiveProgress(id){autoRunId=id;liveStart=Date.now();liveSequence=-1;liveProgress.textContent='请求已发送，正在等待服务开始处理……';liveTimer=setInterval(pollLiveProgress,1000);pollLiveProgress();}
function stopLiveProgress(){if(liveTimer)clearInterval(liveTimer);liveTimer=null;liveProgress.textContent='当前没有正在执行的步骤；结果与下一步见上方。';}
continueRound.onclick=()=>guarded(async()=>{
  if(autoRunning)throw new Error('请等待当前请求结束');
  const run=await api('/runs',{project_id:project.id,max_steps:30,max_repairs:3});
  await listRuns();$('run-select').value=run.id;await loadRun();renderRunSummary();
  notify('已保留现有项目并建立新一轮，未清除费用记录。');autoStart.click();
});
researchAgain.onclick=()=>guarded(async()=>{
 if(autoRunning)return;
 const run=await api('/runs',{project_id:project.id,max_steps:8,max_repairs:0,scope:'research_only'});
 await listRuns();$('run-select').value=run.id;await loadRun();autoStart.click();
});


const resumeBudget=node('button','保留预留费用后继续（不退款、不自动重试）','quiet');resumeBudget.id='model-resume';resumeBudget.hidden=true;$('model-settings-form').append(resumeBudget);resumeBudget.type='button';
resumeBudget.onclick=()=>guarded(async()=>{await api('/model/resume',{confirmed:true});await refreshModelSettings();notify('费用未确认的请求仍按全额预留占用今日额度。已解除异常暂停；需要手动点击开始自动推进，不会重试未知结果。');});

const webPanel=node('section',undefined,'panel'),webEnabled=node('input'),webDomains=node('textarea'),webSave=node('button','保存联网设置','quiet'),webQuery=node('input'),webMissing=node('input'),webSearch=node('button','本地查找，缺资料再联网','primary'),webUrl=node('input'),webFetch=node('button','导入原厂链接','quiet'),webRetry=node('button','允许重新尝试失败项（次数不清零）','quiet'),webStatus=node('p',undefined,'muted'),webResults=node('div'),webHistory=node('details');
webEnabled.type='checkbox';const webEnableLabel=node('label');webEnableLabel.append(webEnabled,document.createTextNode(' 允许 Agent 在本地资料不足时联网补充原厂资料'));
webDomains.rows=2;webDomains.setAttribute('aria-label','允许的原厂资料域名');webDomains.placeholder='原厂域名，用空格或逗号分隔';
webQuery.placeholder='型号 + 数据手册或资料关键词';webQuery.setAttribute('aria-label','联网资料查询');webQuery.maxLength=200;
webMissing.placeholder='可选：已有文档但缺少哪个字段';webMissing.maxLength=100;
webUrl.placeholder='https:// 原厂资料 URL';webUrl.setAttribute('aria-label','原厂资料链接');
webHistory.append(node('summary','查看联网检索与入库记录'));
webPanel.append(node('h2','Agent 自主资料补充'),node('p','自动推进时，Agent会自行查资料、下载并读取原文、核对和引用参数。你无需操作检索或填写审核表；无法查实的内容保留为缺口，不冒充通过。模型核对仍受每日预算保护。','muted'),webStatus,webResults,webHistory);const optionalResearch=node('details');optionalResearch.append(node('summary','高级设置与手动检索（可选）'),webEnableLabel,webDomains,webSave,webQuery,webMissing,webSearch,webUrl,webFetch,webRetry);webPanel.append(optionalResearch);
$('knowledge-panel').prepend(webPanel);
async function refreshWebResearch(){
 const cfg=await api('/knowledge/web/settings');webEnabled.checked=cfg.enabled;webDomains.value=cfg.domains.join(', ');webStatus.textContent=cfg.enabled?'原厂联网补充已启用。每项目最多10次搜索、10次下载，相同查询默认复用已有结果。':'原厂联网补充未启用；仍可使用本地资料。';
 if(!project)return;const history=await api('/projects/'+project.id+'/web_research');webHistory.replaceChildren(node('summary','查看联网检索与入库记录'));
 for(const r of history.searches.slice(-10))webHistory.append(node('p',r.query+' · '+webResultLabel(r.status)+(r.reason?' · '+r.reason:''),'muted'));
 for(const r of history.documents.slice(-10))webHistory.append(node('p',(r.title||r.url)+' · '+webResultLabel(r.status)+(r.reason?' · '+r.reason:''),'muted'));
}
webSave.onclick=()=>guarded(async()=>{await api('/knowledge/web/settings',{enabled:webEnabled.checked,domains:webDomains.value.split(/[\s,，]+/).filter(Boolean),confirmed:true});await refreshWebResearch();notify('联网设置已保存；不会仅因开启设置就发出联网请求。');});
function webResultLabel(status){return ({references_found:'找到候选来源',no_matches:'没有找到允许的原厂来源',catalog_sources_available:'改查已有原厂链接',network_unavailable:'公开搜索暂不可用',not_configured:'尚未启用联网',limit_reached:'已达到检索或下载上限',imported:'已入库，参数待审核',import_failed:'导入失败',stale_source:'原资料已变化，需要核对',pending:'上次执行结果待核对',needs_external_evidence:'仍需补充资料'})[status]||status;}
function showWebResearch(result){
 webResults.replaceChildren();const online=result.online;const imports=result.imports||[result];
 webResults.append(node('p',result.network_used===false?'本次使用本地资料，没有联网。':online?.cached?'本次复用已有检索记录，不重复搜索。':'检索或下载已结束。','muted'));
 if(online)webResults.append(node('p','联网结果：'+webResultLabel(online.status)+(online.reason?' · '+online.reason:''),'muted'));
 if(result.next_step)webResults.append(node('p',result.next_step,'muted'));
 for(const record of imports){if(!record.document_id){if(record.status)webResults.append(node('p','结果：'+webResultLabel(record.status)+(record.reason?' · '+record.reason:''),'muted'));continue;}
  const box=node('div',undefined,'candidate');box.append(node('b',record.title||record.document_id),node('p','已入库，参数未审核 · SHA-256 '+record.sha256,'muted'));
  const read=node('button','读取原文并核对参数','quiet');read.onclick=()=>guarded(async()=>{selectedPage=await api('/knowledge/page',{document_id:record.document_id,page:record.pages?1:null});$('knowledge-citation').textContent=selectedPage.citation+' · SHA-256 '+selectedPage.sha256;$('knowledge-page').textContent=selectedPage.text;$('knowledge-original').href=selectedPage.file_url;$('knowledge-original').hidden=false;$('parameter-confirmed').checked=false;showRelatedPdfLinks(selectedPage);});box.append(read);webResults.append(box);
 }
 if(result.matches?.length)webResults.append(node('p','当前本地命中 '+result.matches.length+' 个片段；可在下方本地检索中读取具体页面。','muted'));
}
webSearch.onclick=()=>guarded(async()=>{if(!project)throw new Error('请先选择项目');webStatus.textContent='正在检索与补充资料，请稍候；不会调用模型。';const result=await api('/knowledge/web/research',{project_id:project.id,query:webQuery.value,missing_field:webMissing.value.trim()||null});showWebResearch(result);await refreshWebResearch();});
webFetch.onclick=()=>guarded(async()=>{if(!project)throw new Error('请先选择项目');webStatus.textContent='正在下载并建立索引，请稍候；不会调用模型。';const result=await api('/knowledge/web/fetch',{project_id:project.id,url:webUrl.value.trim()});showWebResearch(result);await refreshWebResearch();});
webRetry.onclick=()=>guarded(async()=>{if(!project)throw new Error('请先选择项目');const result=await api('/knowledge/web/retry',{project_id:project.id,confirmed:true});await refreshWebResearch();notify('已允许重新尝试 '+result.retry_enabled_for+' 项；检索与下载次数未清零，不会自动重试。');});

function showRelatedPdfLinks(page){
 const links=page.related_pdf_urls||[];if(!links.length)return;
 const section=node('details');section.append(node('summary','原网页中的PDF资料链接（仍需核对）'));
 for(const url of links){const link=node('a',url);link.href=url;link.target='_blank';link.rel='noopener';const button=node('button','导入此PDF','quiet');button.onclick=()=>guarded(async()=>{if(!project)throw new Error('请先选择项目');showWebResearch(await api('/knowledge/web/fetch',{project_id:project.id,url}));await refreshWebResearch();});section.append(link,button);}
 webResults.append(section);
}

function showCustomModel(){$('custom-model-fields').hidden=$('model-choice').value!=='custom';}
function modelPayload(){const custom=$('model-choice').value==='custom';const p={model:custom?$('model-custom-name').value.trim():$('model-choice').value,endpoint:$('model-endpoint').value.trim(),enabled:$('model-enabled').checked,api_key:$('model-key').value};if(custom){p.prices=Object.fromEntries(['hit','input','output'].map(k=>[k,Number($('model-price-'+k).value)]));p.output_limit=Number($('model-output-limit').value);}return p;}
const chatPanel=node('section',undefined,'panel conversation-panel');chatPanel.id='project-chat';
const chatHead=node('div',undefined,'section-head');chatHead.append(node('h2','与智能体交流'));
const apiShortcut=node('button','修改模型 / API','quiet');apiShortcut.type='button';apiShortcut.onclick=()=>{$('model-settings-details').open=true;$('model-settings-panel').scrollIntoView({behavior:'smooth'});$('model-choice').focus();};chatHead.append(apiShortcut);
const chatLog=node('div');chatLog.id='chat-messages';chatLog.setAttribute('role','log');chatLog.setAttribute('aria-live','polite');
const chatForm=node('form');const chatLabel=node('label','消息');chatLabel.htmlFor='chat-input';const chatInput=node('textarea');chatInput.id='chat-input';chatInput.rows=3;chatInput.maxLength=6000;chatInput.required=true;chatInput.placeholder='补充想法、问进度，或告诉智能体你遇到的问题……';
const applyLabel=node('label',undefined,'muted small');const applyInput=node('input');applyInput.type='checkbox';applyInput.id='chat-apply';applyLabel.append(applyInput,document.createTextNode(' 同时作为需求补充（会更新项目并使旧分析失效）'));
const chatStatus=node('p',undefined,'muted small');chatStatus.setAttribute('role','status');
const chatSend=node('button','发送（计入模型预算）','primary');chatSend.type='submit';
chatForm.append(chatLabel,chatInput,applyLabel,chatSend,chatStatus);chatPanel.append(chatHead,node('p','对话按项目保存。普通聊天不会自动编译或修改项目；需要执行时请使用项目操作。','muted small'),chatLog,chatForm);document.querySelector('#workspace .tabs').before(chatPanel);
function drawConversation(messages){chatLog.replaceChildren();if(!messages.length)chatLog.append(node('p','可以先问：“当前项目到哪一步了？下一步做什么？”','muted'));for(const row of messages){chatLog.append(node('div',row.message,'chat-bubble chat-user'));chatLog.append(node('div',row.reply||(row.status==='pending'?'该请求尚未完成；刷新查看，不会自动重试。':row.error||'未收到回复'),'chat-bubble chat-agent'));}chatLog.scrollTop=chatLog.scrollHeight;}
async function refreshConversation(id){const data=await api('/projects/'+id+'/chat');if(project?.id===id)drawConversation(data.messages);}
let chatBusy=false;
chatForm.onsubmit=async e=>{e.preventDefault();if(!project||chatBusy)return;const id=project.id;const message=chatInput.value.trim();if(!message)return;chatBusy=true;chatSend.disabled=true;chatInput.disabled=true;chatStatus.textContent='正在发送并等待模型回复；工程执行中时可能需要排队，请勿重复发送。';try{if(applyInput.checked){const current=await api('/projects/'+id);await api('/projects/'+id+'/supplement',{message,revision:current.revision});applyInput.checked=false;chatStatus.textContent='需求补充已保存，正在等待回复。';}const data=await api('/projects/'+id+'/chat',{message,request_id:crypto.randomUUID()});if(project?.id===id){drawConversation(data.messages);chatInput.value='';chatStatus.textContent=data.messages.at(-1)?.status==='answered'?'回复已保存。':'请求未完成，请查看对话中的错误；不会自动重试。';}await refreshModelSettings();}catch(err){chatStatus.textContent=err.message+'；如连接中断，请刷新查看实际记录后再决定是否重发。';}finally{chatBusy=false;chatSend.disabled=false;chatInput.disabled=false;if(project?.id===id)await openProject(id);}};
chatInput.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();chatForm.requestSubmit();}};

// Restore the full work area alongside the conversation.
const workArea=node('section');workArea.id='engineering-area';
for(const child of [...$('workspace').children])if(child!==chatPanel)workArea.append(child);
const resizeHandle=node('div');resizeHandle.id='workspace-resizer';resizeHandle.tabIndex=0;resizeHandle.setAttribute('role','separator');resizeHandle.setAttribute('aria-orientation','vertical');resizeHandle.setAttribute('aria-label','调整工作区与聊天区宽度');resizeHandle.setAttribute('aria-valuemin','30');resizeHandle.setAttribute('aria-valuemax','80');
$('workspace').append(workArea,resizeHandle,chatPanel);
let splitRatio=Number(localStorage.getItem('workspace-split'))||66;
function setSplit(value){splitRatio=Math.max(30,Math.min(80,value));$('workspace').style.setProperty('--work-share',splitRatio+'%');resizeHandle.setAttribute('aria-valuenow',String(Math.round(splitRatio)));localStorage.setItem('workspace-split',String(splitRatio));}
setSplit(splitRatio);
resizeHandle.onpointerdown=e=>{if(e.button!==0)return;resizeHandle.setPointerCapture(e.pointerId);resizeHandle.classList.add('dragging');};
resizeHandle.onpointermove=e=>{if(!resizeHandle.hasPointerCapture(e.pointerId))return;const box=$('workspace').getBoundingClientRect();setSplit((e.clientX-box.left)/box.width*100);};
resizeHandle.onpointerup=e=>{if(resizeHandle.hasPointerCapture(e.pointerId))resizeHandle.releasePointerCapture(e.pointerId);resizeHandle.classList.remove('dragging');};resizeHandle.onpointercancel=()=>resizeHandle.classList.remove('dragging');
resizeHandle.ondblclick=()=>setSplit(66);resizeHandle.onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();setSplit(splitRatio+(e.key==='ArrowLeft'?-2:2));}else if(e.key==='Home'){e.preventDefault();setSplit(66);}};
const settingsDialog=node('dialog');settingsDialog.id='api-dialog';const closeSettings=node('button','关闭','quiet');closeSettings.type='button';closeSettings.onclick=()=>settingsDialog.close();settingsDialog.append(closeSettings,$('model-settings-panel'));document.body.append(settingsDialog);
apiShortcut.onclick=()=>{settingsDialog.showModal();$('model-settings-details').open=true;};
const sidebarSettings=node('button','模型与 API 设置','quiet');sidebarSettings.type='button';sidebarSettings.onclick=apiShortcut.onclick;document.querySelector('.sidebar').append(sidebarSettings);
chatHead.querySelector('h2').textContent='Agent';chatLabel.hidden=true;chatInput.placeholder='和 Agent 聊聊你的想法，或询问项目进度…';chatSend.textContent='发送 ↑';
chatForm.classList.add('chat-composer');chatPanel.querySelector('p.muted.small').textContent='对话自动保存 · Ctrl / ⌘ + Enter 发送';
chatInput.rows=2;

chatInput.setAttribute('aria-label','消息');
const mobileProjects=node('button','☰ 项目','quiet mobile-project-toggle');mobileProjects.type='button';mobileProjects.onclick=()=>document.body.classList.toggle('sidebar-open');document.querySelector('header').prepend(mobileProjects);
const closeProjects=node('button','收起项目列表','quiet mobile-project-toggle');closeProjects.type='button';closeProjects.onclick=()=>document.body.classList.remove('sidebar-open');document.querySelector('.sidebar').prepend(closeProjects);

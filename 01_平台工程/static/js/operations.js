import {api,node,button,form,panel,dataTable,badge,money,stat,notice,toast,modal,navigate,refresh,state} from './core.js';

const list = (value, key = 'rows') => Array.isArray(value) ? value : value?.[key] || [];
const staff = user => ['admin','settlement'].includes(user.role);
const option = (row, label) => ({value:row.id, label:label ? label(row) : `${row.name || row.login || row.model || '记录'} #${row.id}`});
const actions = (...children) => node('div',{className:'actions'},...children);
const d = value => {
  if (!value) return '—';
  const time=new Date(value);
  return Number.isNaN(time.valueOf()) ? String(value) : time.toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});
};
const periodLabel = value => /^\d{4}-\d{2}/.test(String(value || '')) ? String(value).slice(0,7) : d(value).split(' ')[0];
const amountColumn = (key,label) => ({key,label,className:'numeric',render:r=>money(r[key])});
const routeId = (params,key) => /^\d+$/.test(params.get(key) || '') ? Number(params.get(key)) : null;
const nowLocal = (value=undefined) => (value ? new Date(value) : new Date()).toLocaleString('sv-SE',{timeZone:'Asia/Shanghai'}).replace(' ','T');
const beijingInput = value => `${value}+08:00`;
const amountField = (label,name,value='') => ({label,name,type:'number',value,min:'0.01',step:'0.01',required:true});

function confirmAction(title, description, action, label = '确认操作') {
  const content = node('div',{},notice(description,'warning'));
  const close = modal(title,content);
  content.append(actions(button(label, async () => { await action(); close(); toast('操作已保存'); refresh(); })));
}

function workState(work) {
  return work.closed_at ? 'closed' : work.repaired_at ? '已修复' : work.arrived_at ? '已到场' : work.accepted_at ? '已接单' : '待接单';
}

function workTimeline(work) {
  return node('ol',{className:'timeline'},[
    ['已派单',work.assigned_at],['接单',work.accepted_at],['到场',work.arrived_at],
    ['维修完成',work.repaired_at],['工单关闭',work.closed_at]
  ].map(([label,value])=>node('li',{className:`timeline-item ${value ? 'done' : ''}`},node('strong',{},label),node('span',{className:'muted'},value ? d(value) : '尚未完成'))));
}

async function showWork(ctx,id) {
  const detail = await api(`/work/${id}`);
  const work = detail.work;
  const candidates = [
    ['accept','接单',!work.accepted_at],
    ['arrive','登记到场',!!work.accepted_at && !work.arrived_at],
    ['repair','登记修复',!!work.arrived_at && !work.repaired_at],
    ['close','关闭工单',!!work.repaired_at && !work.closed_at]
  ];
  const next = candidates.find(x=>x[2]);
  const workflow = panel(`工单 #${work.id}`,actions(button('返回告警与工单',()=>navigate('monitor'),'secondary'),button(`查看关联告警 #${work.alarm_id}`,()=>navigate('monitor',{alarm:work.alarm_id}),'secondary'),badge(workState(work))),workTimeline(work),node('p',{},`关联告警 #${work.alarm_id} · 维修人员 #${work.technician_id}`),node('p',{className:'muted'},`处理结论：${work.result || '暂无'}`));
  if (next) workflow.append(form([
    {label:'维修/处理说明',name:'result',type:'textarea',value:work.result || '',required:next[0]==='close',maxLength:255,placeholder:'关闭工单必须填写处理结论'}
  ],async values=>{
    const result=values.result.trim();
    if(next[0]==='close'&&!result)throw new Error('关闭工单必须填写处理结论。');
    await api(`/work/${id}/step`,{method:'POST',body:{step:next[0],result:result || null}});toast('工单节点已保存');refresh();
  },next[1]));
  else workflow.append(notice('工单已经关闭，历史节点保留。告警恢复还需通过设备正常采样与心跳检查。'));
  const parts = panel('维修备件',dataTable([{key:'part',label:'备件名称'},{key:'quantity',label:'数量'}],detail.parts));
  if (!work.closed_at) parts.append(form([
    {label:'备件名称',name:'part',required:true,maxLength:255},
    {label:'数量',name:'quantity',type:'number',value:1,min:1,max:10000,step:1,required:true}
  ],async values=>{
    if(!values.part.trim())throw new Error('请填写备件名称。');
    await api(`/work/${id}/parts`,{method:'POST',body:{part:values.part.trim(),quantity:Number(values.quantity)}});toast('备件已保存');refresh();
  },'保存备件数量'));
  ctx.root.replaceChildren(workflow,parts);
}

function telemetryChart(rows) {
  const chronological = [...rows].filter(r=>r.kw !== null && r.kw !== undefined && Number.isFinite(Number(r.kw))).sort((a,b)=>new Date(a.sampled_at)-new Date(b.sampled_at)).slice(-24);
  if (!chronological.length) return notice('所选设备尚无可绘制的功率采样。');
  const max = Math.max(1,...chronological.map(r=>Number(r.kw)));
  const chart = node('div',{className:'telemetry-chart',role:'img','aria-label':`最近${chronological.length}条实际桩级功率采样；最高${max}千瓦`});
  chart.style.cssText='display:flex;align-items:flex-end;gap:5px;height:120px;padding:12px 0;margin-bottom:20px;border-bottom:1px solid #dce6e5';
  for (const row of chronological) {
    const bar = node('div',{title:`${d(row.sampled_at)} · ${row.kw} kW`});
    bar.style.cssText=`flex:1;min-width:3px;height:${Math.max(2,Number(row.kw)/max*100)}%;background:#148773;border-radius:4px 4px 0 0`;
    chart.append(bar);
  }
  return chart;
}

export async function renderMonitor(ctx) {
  const workId = routeId(ctx.params,'work');
  if (workId) return showWork(ctx,workId);
  const [alarmData,workData,lookups] = await Promise.all([api('/alarms'),api('/work'),api('/ui/api/lookups')]);
  const alarms = list(alarmData), works = list(workData);
  const selectedAlarm = routeId(ctx.params,'alarm');
  let selected = alarms.find(a=>a.id===selectedAlarm);
  if (selectedAlarm && !selected) selected = await api(`/alarms/${selectedAlarm}`);
  const alarmColumns = [
    {key:'id',label:'告警',render:r=>button(`#${r.id}`,()=>navigate('monitor',{alarm:r.id}),'ghost small')},
    {key:'station_id',label:'场站',render:r=>`#${r.station_id}`},
    {key:'charger_id',label:'桩 / 来源枪',render:r=>`桩 #${r.charger_id}${r.connector_id ? ` · 枪 #${r.connector_id}` : ' · 桩级'}`},
    {key:'code',label:'故障码'},{key:'severity',label:'级别',render:r=>`L${r.severity}`},
    {key:'deadline',label:'响应截止',render:r=>d(r.deadline)},
    {key:'escalated_at',label:'升级',render:r=>r.escalated_at ? badge('已升级') : '未升级'}
  ];
  const header = node('div',{className:'stats-grid'},stat('活动告警',alarms.length,'当前权限内，最多100条'),stat('待接单',works.filter(w=>!w.accepted_at).length,'最近30条可见工单'),stat('维修处理中',works.filter(w=>w.accepted_at && !w.closed_at).length,'按工单真实节点统计'));
  const content = [header,panel('告警响应',actions(button('刷新',refresh,'secondary')),dataTable(alarmColumns,alarms))];
  if (selected) {
    const alarm = selected;
    const detail = panel(`告警 #${alarm.id} · ${alarm.code}`,node('div',{className:'stats-grid'},stat('级别',`L${alarm.severity}`),stat('发生时间',d(alarm.opened_at)),stat('响应截止',d(alarm.deadline))),notice(alarm.restored_at ? `已恢复：${d(alarm.restored_at)}` : '恢复必须先完成维修，并满足修复后连续正常采样与在线观察条件。'));
    if (ctx.user.role==='admin' && !alarm.restored_at) {
      const technicians = list(lookups.technicians).filter(t=>t.station_id===alarm.station_id);
      if (technicians.length) detail.append(form([{label:'本站维修人员',name:'technician',type:'select',required:true,options:technicians.map(t=>option(t,r=>`${r.login} #${r.id}`))}],async values=>{
        const result = await api(`/alarms/${alarm.id}/assign`,{method:'POST',body:{technician:Number(values.technician)}});toast(`已派单 #${result.id}`);navigate('monitor',{work:result.id});
      },'派发工单'));
      else detail.append(notice('本站没有可选维修人员，需先配置人员归属。','warning'));
      detail.append(button('检查恢复条件并恢复',()=>confirmAction('恢复告警',`将检查告警 #${alarm.id} 的全部工单、正常采样、设备和枪状态；条件不足会被数据库拒绝。`,()=>api(`/alarms/${alarm.id}/recover`,{method:'POST',body:{}})),'secondary'));
    }
    content.splice(1,0,detail);
  }
  const offset=Math.max(0,Number.parseInt(ctx.params.get('offset')||'0',10)||0);
  const pageWorks = offset ? list(await api(`/work?offset=${offset}`)) : works;
  content.push(panel('维修工单',dataTable([
    {key:'id',label:'工单',render:r=>button(`#${r.id}`,()=>navigate('monitor',{work:r.id}),'ghost small')},
    {key:'alarm_id',label:'告警',render:r=>`#${r.alarm_id}`},{key:'technician_id',label:'维修人员',render:r=>`#${r.technician_id}`},
    {key:'assigned_at',label:'派单时间',render:r=>d(r.assigned_at)},
    {key:'state',label:'当前节点',render:r=>badge(workState(r))},{key:'result',label:'处理结论'}
  ],pageWorks),actions(button('上一页',()=>navigate('monitor',{offset:Math.max(0,offset-30)}),'secondary'),node('span',{className:'muted'},`第 ${Math.floor(offset/30)+1} 页 · 每页30条`),button('下一页',()=>navigate('monitor',{offset:offset+30}),'secondary'))));
  const chargers=list(lookups.chargers);
  const requestedCharger=routeId(ctx.params,'charger');
  const selectedCharger=chargers.find(c=>c.id===requestedCharger)?.id || chargers[0]?.id;
  if (chargers.length) {
    const telemetry = selectedCharger ? list(await api(`/ui/api/telemetry?charger=${selectedCharger}&limit=100`)) : [];
    content.push(panel('桩级运行采样',notice('显示整桩遥测。这里的功率不会平均分配为每一把枪的充电功率。'),form([{label:'选择设备',name:'charger',type:'select',value:selectedCharger,options:chargers.map(c=>option(c,r=>`桩 #${r.id} · ${r.model || ''} · 场站 #${r.station_id}`))}],values=>navigate('monitor',{charger:values.charger}),'查看采样',{inline:true}),telemetryChart(telemetry),dataTable([
      {key:'sampled_at',label:'采样时间',render:r=>d(r.sampled_at)},{key:'volts',label:'电压 V'},{key:'amps',label:'电流 A'},
      {key:'kw',label:'桩功率 kW'},{key:'temperature',label:'温度 ℃'},{key:'offline_seconds',label:'离线秒数'},{key:'fault_code',label:'故障码',render:r=>r.fault_code || '无'}
    ],telemetry)));
  }
  ctx.root.replaceChildren(...content);
}

function csvRows(text) {
  const rows=[];let row=[],field='',quoted=false,closed=false,started=false;
  const pushField=()=>{row.push(field);field='';closed=false;};
  const pushRow=()=>{
    if(started||row.length||field.length){pushField();rows.push(row);}
    row=[];field='';closed=false;started=false;
  };
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(quoted){
      if(c==='"'){if(text[i+1]==='"'){field+='"';i++;}else{quoted=false;closed=true;}}
      else field+=c;
      continue;
    }
    if(closed&&!['\n','\r',','].includes(c))throw new Error('CSV引号关闭后只能跟逗号或换行。');
    if(c==='"'){
      if(field)throw new Error('CSV字段内部的引号必须转义，且字段整体用引号包围。');
      quoted=true;started=true;
    }
    else if(c===','){pushField();started=true;}
    else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;pushRow();}
    else{field+=c;started=true;}
  }
  if(quoted)throw new Error('CSV存在未闭合的引号。');
  pushRow();
  if(!rows.length)throw new Error('CSV内容为空。');
  const header=rows.shift().map((s,i)=>i===0?s.replace(/^\uFEFF/,''):s);
  const required=['order_id','kwh','amount','paid'];
  if(required.some(c=>!header.includes(c)))throw new Error('表头必须包含 order_id,kwh,amount,paid。');
  if(new Set(header).size!==header.length)throw new Error('CSV表头存在重复列。');
  if(rows.length>10000)throw new Error('单次导入不能超过10000行。');
  const seenOrders=new Set();
  return rows.map((values,i)=>{
    if(values.length!==header.length)throw new Error(`CSV第${i+2}行列数不一致。`);
    const record=Object.fromEntries(header.map((k,n)=>[k,values[n]]));
    const decimal=/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
    if(!/^[1-9]\d*$/.test(record.order_id) || !decimal.test(record.kwh) || !Number.isFinite(Number(record.kwh)) || Number(record.kwh)<0 || !decimal.test(record.amount) || !Number.isFinite(Number(record.amount)) || !['true','false'].includes(record.paid))throw new Error(`CSV第${i+2}行的订单号、电量、金额或paid不合法。paid必须小写true/false。`);
    if(seenOrders.has(record.order_id))throw new Error(`CSV订单 #${record.order_id} 重复；每批每单只能有一行。`);
    seenOrders.add(record.order_id);
    return record;
  });
}

function importPanel(id) {
  const area=node('textarea',{rows:8,placeholder:'order_id,kwh,amount,paid\n请粘贴外部账单真实行，或选择CSV文件。','aria-label':'外部账单CSV'});
  const input=node('input',{type:'file',accept:'.csv,text/csv','aria-label':'选择外部账单CSV文件'});
  const batch=node('input',{value:`web-${crypto.randomUUID()}`,'aria-label':'导入批次',maxLength:255});
  const result=node('div');
  let validatedText=null;
  const showPreview=()=>{
    area.value=area.value.replace(/^\uFEFF/,'');
    if(new Blob([area.value]).size>2*1024*1024)throw new Error('文件内容超过2MB。');
    const rows=csvRows(area.value);
    result.replaceChildren(notice(`已检查${rows.length}行，以下预览前8行。缺单、多单、金额差异与批次完整性由后端在导入时核对。`),dataTable([{key:'order_id',label:'订单号'},{key:'kwh',label:'外部电量 kWh'},amountColumn('amount','外部金额'),{key:'paid',label:'外部付款状态'}],rows.slice(0,8)));
    validatedText=area.value;
  };
  input.addEventListener('change',async()=>{
    const file=input.files[0];if(!file)return;
    try{if(file.size>2*1024*1024)throw new Error('文件不能超过2MB。');area.value=(await file.text()).replace(/^\uFEFF/,'');showPreview();}catch(e){validatedText=null;result.replaceChildren(notice(e.message,'error'));}
  });
  area.addEventListener('input',()=>{validatedText=null;});
  return panel('外部账单导入',notice('仅导入当前结算单的完整外账，不自动生成“看起来一致”的付款数据。CSV保留原始文本发送；成功后请查看差异明细。'),node('label',{className:'form-field'},node('span',{},'导入批次'),batch),input,area,result,actions(button('检查并预览',showPreview,'secondary'),button('导入并生成差异',async()=>{
    if(validatedText!==area.value)throw new Error('请先检查并预览当前CSV内容。');
    if(!batch.value.trim())throw new Error('请填写批次名称。');
    await api(`/settlements/${id}/import?batch=${encodeURIComponent(batch.value)}`,{method:'POST',headers:{'Content-Type':'text/csv;charset=utf-8'},body:area.value});toast('账单已导入，差异已重新计算');refresh();
  })));
}

async function showSettlement(ctx,id) {
  const [detail,evidence]=await Promise.all([api(`/settlements/${id}`),api(`/ui/api/settlements/${id}/evidence`)]);
  const s=detail.settlement;
  const ownSide=ctx.user.role==='operator'?'operator':'platform';
  const signatures=list(evidence.signatures);
  const signed=signatures.some(r=>r.side===ownSide);
  const completeBatch=list(evidence.imports).some(r=>r.state==='complete');
  const unresolved=list(detail.differences).some(r=>!r.conclusion || (r.conclusion==='accept'&&!r.automatic_allowed));
  const reversed=new Set(list(detail.invoices).map(r=>r.original_id).filter(Boolean));
  const summary=panel(`结算单 #${id}`,actions(button('返回结算列表',()=>navigate('settlements'),'secondary'),badge(s.state)),node('p',{className:'muted'},`运营商 #${s.operator_id} · 场站 #${s.station_id} · 账期 ${periodLabel(s.period)}`),node('div',{className:'stats-grid'},stat('应结金额',`¥ ${money(s.due)}`),stat('电量',`${s.kwh} kWh`),stat('净开票额',`¥ ${money(s.invoiced)}`),stat('可开票额',`¥ ${money(s.remaining)}`)));
  const signPanel=panel('双方签字',notice('平台与运营商必须分别使用本人账号签字。单方签字不会自动确认整单；普通浏览器标签页共享登录会话。'),dataTable([{key:'side',label:'签字方',render:r=>r.side==='operator'?'运营商':'平台'},{key:'actor',label:'签字账号',render:r=>`${r.login || '账号'} #${r.actor}`},{key:'confirmed_at',label:'签字时间',render:r=>d(r.confirmed_at)}],signatures));
  if(s.state==='draft' && !signed && completeBatch && !unresolved)signPanel.append(button(`以${ownSide==='operator'?'运营商':'平台'}身份确认账单`,()=>confirmAction('确认结算账单',`确认本人已核对结算单 #${id}、完整外账及全部差异。当前应结金额 ¥${money(s.due)}；双方确认后账单冻结。`,()=>api(`/settlements/${id}/confirm`,{method:'POST',body:{}}),'签署本方意见')));
  else signPanel.append(notice(s.state!=='draft'?'该结算单已经完成确认。':signed?'本方已签字。':!completeBatch?'请先导入完整外部账单，再进行双方确认。':'请先完成全部差异的双方一致意见，再签署整单。'));
  const diffTable=dataTable([
    {key:'id',label:'差异号'},{key:'order_id',label:'订单'},{key:'kind',label:'差异类型',render:r=>({energy:'电量',price:'金额',payment:'付款状态',missing:'缺单',extra:'多单'}[r.kind]||r.kind)},
    {key:'expected_kwh',label:'平台电量'},{key:'actual_kwh',label:'外部电量'},amountColumn('expected_amount','平台金额'),amountColumn('actual_amount','外部金额'),
    {key:'conclusion',label:'最终结论',render:r=>r.conclusion?badge(r.conclusion):badge('pending')},
    {key:'actions',label:'本方意见',render:r=>s.state==='draft'?actions(button('接受',()=>confirmAction('提交差异意见',`对差异 #${r.id} 提交本方“接受”意见。${r.automatic_allowed?'':'这类差异禁止自动接受，后端可能要求拒绝后重新导入。'}`,()=>api(`/differences/${r.id}/confirm`,{method:'POST',body:{conclusion:'accept'}})),'secondary small'),button('拒绝',()=>confirmAction('提交差异意见',`对差异 #${r.id} 提交本方“拒绝”意见。`,()=>api(`/differences/${r.id}/confirm`,{method:'POST',body:{conclusion:'reject'}})),'secondary small')):'已冻结'}
  ],detail.differences);
  const differencePanel=panel('逐单对账差异',notice('修改差异意见会清除已有整单签字；双方意见一致后仍需重新签署整单。'),diffTable,dataTable([{key:'diff_id',label:'差异号'},{key:'side',label:'意见方',render:r=>r.side==='operator'?'运营商':'平台'},{key:'conclusion',label:'意见',render:r=>badge(r.conclusion)},{key:'actor',label:'账号',render:r=>`${r.login || '账号'} #${r.actor}`},{key:'confirmed_at',label:'时间',render:r=>d(r.confirmed_at)}],evidence.opinions));
  const ledger=panel('平台结算快照',notice('金额来自生成结算时冻结的订单分成快照及跨期调整，不以当前费率重新计算历史。'),dataTable([
    {key:'order_id',label:'订单号'},{key:'source_period',label:'归属账期',render:r=>periodLabel(r.source_period)},{key:'kwh',label:'电量 kWh'},
    amountColumn('energy_share','电费分成'),amountColumn('service_share','服务费分成'),amountColumn('platform_fee','平台费'),amountColumn('net_received','客户净实收')
  ],evidence.items),node('h3',{},'跨期/对账调整'),dataTable([{key:'id',label:'调整号'},{key:'order_id',label:'订单'},amountColumn('amount','调整金额'),{key:'reason',label:'原因'}],evidence.adjustments));
  const external=panel('外部账单与批次',dataTable([{key:'batch',label:'批次'},{key:'expected_rows',label:'声明行数'},{key:'state',label:'导入状态',render:r=>badge(r.state)},{key:'completed_at',label:'完成时间',render:r=>d(r.completed_at)}],evidence.imports),dataTable([{key:'order_id',label:'订单'},{key:'kwh',label:'电量 kWh'},amountColumn('amount','外部金额'),{key:'paid',label:'付款',render:r=>r.paid?'已付':'未付'}],evidence.external));
  const invoices=panel('运营商结算票据',notice('课程模拟票据记录。蓝票和红票均保留；红冲必须等额关联原票。'),dataTable([
    {key:'id',label:'票据号'},{key:'title',label:'抬头'},amountColumn('amount','票面金额'),{key:'original_id',label:'类型',render:r=>r.original_id?`红票 · 原票 #${r.original_id}`:'蓝票'},
    {key:'issued_at',label:'签发时间',render:r=>d(r.issued_at)},
    {key:'action',label:'操作',render:r=>staff(ctx.user)&&!r.original_id&&!reversed.has(r.id)?button('全额红冲',()=>confirmAction('红冲结算票据',`对蓝票 #${r.id} 等额红冲 ¥${money(r.amount)}，原票将保留。`,()=>api(`/settlements/${id}/invoice`,{method:'POST',body:{title:r.title,tax_id:r.tax_id,amount:r.amount,original:r.id}})),'danger small'):'—'}
  ],detail.invoices));
  if(staff(ctx.user)&&s.state!=='draft'&&Number(s.remaining)>0)invoices.append(form([
    {label:'开票抬头',name:'title',required:true,maxLength:255},{label:'税号',name:'tax_id',required:true,maxLength:255},amountField('票面金额','amount',s.remaining)
  ],async v=>{await api(`/settlements/${id}/invoice`,{method:'POST',body:v});toast('结算蓝票已签发');refresh();},'签发结算蓝票'));
  const children=[summary,signPanel,differencePanel,ledger,external,invoices];
  if(staff(ctx.user)&&s.state==='draft'){
    if(!list(evidence.imports).length)children.splice(2,0,importPanel(id));
    else children.splice(2,0,panel('重新导入外部账单',notice('当前批次已经存在。纠错前需要重置整批外账，同时清除该批次差异、双方意见和整单签字；结算快照保留。','warning'),button('重置当前外账批次',()=>confirmAction('重置外账及确认意见',`将清除结算单 #${id} 的导入批次、外账行、差异及对应调整、双方差异意见和整单签字，保留平台结算快照。请核对后重新导入完整账单。`,()=>api(`/ui/api/settlements/${id}/reset-import`,{method:'POST',body:{confirmed:true}}),'确认重置批次'),'danger')));
  }
  ctx.root.replaceChildren(...children);
}

export async function renderSettlements(ctx) {
  const id=routeId(ctx.params,'id');if(id)return showSettlement(ctx,id);
  const rows=list(await api('/settlements'));
  const content=[node('div',{className:'stats-grid'},stat('可见结算单',rows.length,'最近100条，按角色归属过滤'),stat('待确认',rows.filter(r=>r.state==='draft').length),stat('已确认 / 已付',rows.filter(r=>r.state!=='draft').length))];
  if(staff(ctx.user)) {
    const lookups=await api('/ui/api/lookups');
    const stations=list(lookups.stations);
    if(stations.length)content.push(panel('生成月结账单',form([
      {label:'场站',name:'station',type:'select',required:true,options:stations.map(s=>option(s))},
      {label:'账期月份',name:'period',type:'month',value:nowLocal(state.serverTime).slice(0,7),required:true}
    ],async v=>{await api('/settlements',{method:'POST',body:{station:Number(v.station),period:v.period+'-01'}});toast('结算单已生成或更新，请从列表查看');refresh();},'生成 / 更新草稿',{description:'仅处理可结算订单。已确认结算单不能重新覆盖。'})));
  }
  content.push(panel('结算与对账',actions(button('刷新列表',refresh,'secondary')),dataTable([
    {key:'id',label:'结算单',render:r=>button(`#${r.id}`,()=>navigate('settlements',{id:r.id}),'ghost small')},
    {key:'operator_id',label:'运营商',render:r=>`#${r.operator_id}`},{key:'station_id',label:'场站',render:r=>`#${r.station_id}`},
    {key:'period',label:'账期',render:r=>periodLabel(r.period)},{key:'state',label:'状态',render:r=>badge(r.state)},
    amountColumn('due','应结金额'),amountColumn('invoiced','净开票额'),amountColumn('remaining','可开票额')
  ],rows)));
  ctx.root.replaceChildren(...content);
}

export async function renderInvoices(ctx) {
  const requests=list(await api('/ui/api/invoice-requests'),'requests');
  const selectedOrder=routeId(ctx.params,'order');
  const content=[notice('消费票据和运营商结算票据分别管理。这里按消费开票申请签发课程模拟票据，不向税务机构发送指令。'),panel('消费开票申请',dataTable([
    {key:'id',label:'申请号'},{key:'order_id',label:'订单',render:r=>button(`#${r.order_id}`,()=>navigate('invoices',{order:r.order_id}),'ghost small')},
    {key:'login',label:'车主账号'},{key:'title',label:'抬头'},{key:'state',label:'状态',render:r=>badge(r.state)},amountColumn('remaining','当前可开金额'),
    {key:'requested_at',label:'申请时间',render:r=>d(r.requested_at)},
    {key:'action',label:'操作',render:r=>r.state!=='rejected'&&Number(r.remaining)>0?button('签发蓝票',()=>{
      let close;
      close=modal(`申请 #${r.id} · 签发消费票`,form([{label:'开票抬头',name:'title',value:r.title,readOnly:true},{label:'税号',name:'tax_id',required:true,maxLength:255},amountField('签发金额','amount',r.remaining)],async v=>{
        await api(`/invoice-requests/${r.id}/issue`,{method:'POST',body:{tax_id:v.tax_id,amount:v.amount}});close();toast('消费蓝票已签发');navigate('invoices',{order:r.order_id});refresh();
      },'确认签发',{description:'额度同时受客户净实付和净应付限制，不能超额开票。'}));
    },'secondary small'):'—'}
  ],requests))];
  if(selectedOrder) {
    const detail=await api(`/orders/${selectedOrder}/invoices`);
    const reversed=new Set(list(detail.invoices).map(r=>r.original_id).filter(Boolean));
    content.push(panel(`订单 #${selectedOrder} 的消费票据`,dataTable([
      {key:'id',label:'票据号'},{key:'request_id',label:'申请号'},{key:'title',label:'抬头'},amountColumn('amount','票面金额'),
      {key:'original_id',label:'类型',render:r=>r.original_id?`红票 · 原票 #${r.original_id}`:'蓝票'},
      {key:'issued_at',label:'签发时间',render:r=>d(r.issued_at)},
      {key:'action',label:'操作',render:r=>!r.original_id&&!reversed.has(r.id)?button('全额红冲',()=>confirmAction('红冲消费票据',`对消费蓝票 #${r.id} 等额红冲 ¥${money(r.amount)}，原票保留。`,()=>api(`/consumer-invoices/${r.id}/reverse`,{method:'POST',body:{}})),'danger small'):'—'}
    ],detail.invoices)));
  }
  ctx.root.replaceChildren(...content);
}

function numeric(value) {return value===''?null:Number(value);}

export async function renderDemo(ctx) {
  const [lookups,orderData,session]=await Promise.all([api('/ui/api/lookups'),api('/ui/api/orders?state=charging'),api('/ui/session')]);
  const initialAt=nowLocal(session.server_time);
  const chargers=list(lookups.chargers), connectors=list(lookups.connectors), orders=list(orderData).filter(r=>r.state==='charging');
  const rules=list(lookups.alarm_rules);
  const content=[notice('管理员模拟控制：本页输入明确作为合成设备、计量和支付流程的演示数据，经正式接口与数据库规则处理。不会自动重置场站、历史订单或全局时钟。','warning')];
  if(chargers.length) {
    const chargerOptions=chargers.map(c=>option(c,r=>`桩 #${r.id} · 场站 #${r.station_id} · ${r.model || ''}`));
    content.push(panel('模拟设备心跳与状态',form([
      {label:'充电桩',name:'charger',type:'select',options:chargerOptions,required:true},
      {label:'设备状态',name:'state',type:'select',options:[{value:'idle',label:'在线 / 正常心跳'},{value:'offline',label:'模拟离线'},{value:'fault',label:'模拟故障'}],required:true}
    ],async v=>{await api(`/demo/chargers/${v.charger}/state`,{method:'POST',body:{state:v.state}});toast('模拟状态与心跳已写入');},'提交模拟状态',{description:'离线或故障可能中断当前充电并触发复核；请先确认所选设备。在线状态不替代告警恢复条件。'})));
    const ruleFields=rules.length?[{label:'已配置故障规则',name:'code',type:'select',options:rules.map(r=>({value:r.code,label:`${r.code} · L${r.severity} · ${r.response_minutes}分钟响应`})),required:true}]:[{label:'故障码（须已配置规则）',name:'code',required:true,maxLength:255}];
    const alarmForm=form([
      {label:'充电桩',name:'charger',type:'select',options:chargerOptions,required:true},
      {label:'来源枪',name:'connector',type:'select',value:'',options:[{value:'',label:'桩级告警 / 未指定来源枪'},...connectors.map(c=>option(c,r=>`枪 #${r.id} · 所属桩 #${r.charger_id}`))]},...ruleFields
    ],async v=>{
      const gun=v.connector?connectors.find(c=>String(c.id)===v.connector):null;
      if(gun && String(gun.charger_id)!==v.charger)throw new Error('来源枪必须属于所选充电桩。');
      const result=await api(`/demo/chargers/${v.charger}/alarms`,{method:'POST',body:{code:v.code,connector_id:v.connector?Number(v.connector):null}});toast(`模拟告警 #${result.id} 已生成（重复同源告警会复用原记录）`);navigate('monitor',{alarm:result.id});
    },'注入模拟告警');
    const chargerSelect=alarmForm.elements.namedItem('charger'), connectorSelect=alarmForm.elements.namedItem('connector');
    const filterGuns=()=>{for(const opt of connectorSelect.options){const gun=connectors.find(c=>String(c.id)===opt.value);opt.hidden=!!gun&&String(gun.charger_id)!==chargerSelect.value;opt.disabled=opt.hidden;}if(connectorSelect.selectedOptions[0]?.disabled)connectorSelect.value='';};
    chargerSelect.addEventListener('change',filterGuns);filterGuns();
    content.push(panel('模拟告警来源',alarmForm));
    content.push(panel('模拟桩级遥测',form([
      {label:'充电桩',name:'charger',type:'select',options:chargerOptions,required:true},
      {label:'采样时刻（北京时间）',name:'at',type:'datetime-local',step:'0.001',value:initialAt,required:true},
      {label:'电压 V',name:'volts',type:'number',value:220,min:0,step:'0.01'},
      {label:'电流 A',name:'amps',type:'number',value:0,min:0,step:'0.01'},
      {label:'整桩功率 kW',name:'kw',type:'number',value:0,min:0,step:'0.01'},
      {label:'温度 ℃',name:'temperature',type:'number',value:25,step:'0.01'},
      {label:'离线秒数',name:'offline_seconds',type:'number',value:0,min:0,step:1},
      {label:'故障码',name:'fault_code',type:'select',value:'',options:[{value:'',label:'正常采样 · 无故障码'},...rules.map(r=>({value:r.code,label:r.code}))]}
    ],async v=>{await api(`/demo/chargers/${v.charger}/telemetry`,{method:'POST',body:{samples:[{at:beijingInput(v.at),volts:numeric(v.volts),amps:numeric(v.amps),kw:numeric(v.kw),temperature:numeric(v.temperature),offline_seconds:numeric(v.offline_seconds),fault_code:v.fault_code||null}]}});toast('桩级遥测已写入');},'写入一条模拟遥测',{description:'默认时刻取打开页面时的服务器北京时间。修复恢复需要修复后最近3条正常样本、90—180秒观察跨度与新鲜心跳，请按实际观察时间调整采样。'})));
  } else content.push(notice('尚无可模拟的设备，请先在设施管理中登记设备。'));
  if(orders.length) {
    const orderOptions=orders.map(o=>option(o,r=>`订单 #${r.id} · 枪 #${r.connector_id} · 开始 ${d(r.started_at)}`));
    const meterInfo=node('div');
    const readingsForm=form([
      {label:'充电中订单',name:'order',type:'select',options:orderOptions,required:true},
      {label:'采样时刻来源',name:'kind',type:'select',value:'start',options:[{value:'start',label:'起始读数 · 精确使用订单开始时刻'},{value:'current',label:'常规 / 结束读数 · 使用服务器当前时刻'},{value:'custom',label:'自选北京时间 · 使用下方时刻'}]},
      {label:'自选采样时刻（仅自选模式使用）',name:'at',type:'datetime-local',step:'0.001',value:initialAt,required:true},
      {label:'累计电表读数 kWh',name:'reading',type:'number',min:0,step:'0.0001',required:true}
    ],async v=>{
      let at;
      if(v.kind==='start'){
        const orderDetail=await api(`/ui/api/orders/${v.order}`);
        if(orderDetail.latest_meter)throw new Error('订单已有读数，请改用常规/结束读数；重复起始时刻不会覆盖原记录。');
        at=orderDetail.order.started_at;
      }else if(v.kind==='current')at=(await api('/ui/session')).server_time;
      else at=beijingInput(v.at);
      const result=await api(`/demo/order/${v.order}/readings`,{method:'POST',body:{samples:[{at,reading:v.reading}]}});
      readingsForm.elements.namedItem('kind').value='current';
      meterInfo.replaceChildren(notice(`已写入订单 #${v.order}：${at}，累计 ${v.reading} kWh。${result.order?.budget_exceeded?'已触发预算处理。':''}`));
      toast('模拟读数已保存；下一条默认采用服务器当前时刻');
    },'写入模拟读数');
    const showMeter=async()=>{
      const selected=readingsForm.elements.namedItem('order').value;
      const detail=await api(`/ui/api/orders/${selected}`);
      if(readingsForm.elements.namedItem('order').value!==selected)return;
      readingsForm.elements.namedItem('kind').value=detail.latest_meter?'current':'start';
      meterInfo.replaceChildren(notice(detail.latest_meter?`最新有效读数：${detail.latest_meter.reading_kwh} kWh，时刻 ${detail.latest_meter.sampled_at}。`:`订单开始时刻：${detail.order.started_at}；请先写一条起始累计读数。`));
    };
    readingsForm.elements.namedItem('order').addEventListener('change',()=>showMeter().catch(e=>toast(e.message,'error')));
    await showMeter();
    content.push(panel('模拟枪级累计电表',notice('第一条选“起始读数”，服务器原始开始时刻的微秒精度会完整保留；第二条选“常规/结束读数”，填写更大的累计值。此为合成设备输入，不会将整桩遥测平均给枪。'),meterInfo,readingsForm));
    content.push(panel('模拟设备结束充电',form([
      {label:'充电中订单',name:'order',type:'select',options:orderOptions,required:true},
      {label:'结束时刻来源',name:'kind',type:'select',value:'latest',options:[{value:'latest',label:'使用订单最新有效读数时刻（推荐）'},{value:'custom',label:'使用下方自选北京时间'}]},
      {label:'自选结束时刻（须有可信读数）',name:'at',type:'datetime-local',step:'0.001',value:initialAt,required:true},
      {label:'模拟异常断连',name:'disconnect',type:'checkbox',value:false}
    ],async v=>{
      let at=beijingInput(v.at);
      if(v.kind==='latest'){
        const detail=await api(`/ui/api/orders/${v.order}`);
        if(!detail.latest_meter||new Date(detail.latest_meter.sampled_at)<=new Date(detail.order.started_at))throw new Error('请先写起始读数，再写一条晚于开始时刻的常规/结束读数。');
        at=detail.latest_meter.sampled_at;
      }
      await api(`/demo/order/${v.order}/finish`,{method:'POST',body:{at,disconnect:v.disconnect}});toast('设备结束已处理，请核对订单费用和状态');navigate('orders',{id:v.order});
    },'结束并执行服务端核价',{description:'默认结束时刻直接使用后端最新有效读数，避免手填时间丢失微秒或超出采样范围。费用仍由数据库按时段核价。'})));
  } else content.push(panel('模拟订单计量',notice('最近订单中暂无充电中的订单。请先用车主账号开单，再用管理员账号回到本页刷新。'),button('刷新可模拟订单',refresh,'secondary')));
  content.push(panel('单次业务扫描',notice('手动检查离线、告警超时升级和各场站叫号。本按钮只执行一次，不代表已经配置持续后台调度。'),button('执行一次扫描与叫号',async()=>{await api('/admin/tick',{method:'POST',body:{}});toast('本次扫描已完成，相关状态请刷新查看');},'secondary')));
  ctx.root.replaceChildren(...content);
}

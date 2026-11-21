import {api,node,button,form,panel,dataTable,badge,money,stat,notice,toast,modal,navigate,refresh} from './core.js';

const time = v => {
  if(!v)return '—';
  const d=new Date(v);
  return Number.isNaN(d.valueOf())?String(v):new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d);
};
const rate = v => v === null || v === undefined ? '—' : Number(v).toFixed(4);
const reference = prefix => `${prefix}-${crypto.randomUUID()}`;
function pendingReference(key,prefix) {
  try {const current=sessionStorage.getItem(key);if(current)return current;const created=reference(prefix);sessionStorage.setItem(key,created);return created;}
  catch {return reference(prefix);}
}
function pendingPayload(key) {try {const v=JSON.parse(sessionStorage.getItem(`${key}:payload`)||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:{};}catch {return {};}}
function rememberPayload(key,value) {try {sessionStorage.setItem(`${key}:payload`,JSON.stringify(value));}catch {}}
function clearReference(key) {try {sessionStorage.removeItem(key);sessionStorage.removeItem(`${key}:payload`);}catch {}}
const staff = user => ['admin','settlement'].includes(user.role);
const opts = (items,label) => items.map(x=>({value:x.id,label:label(x)}));
const numberField = (name,label,value='',extra={}) => ({name,label,value,type:'number',required:true,min:0,step:'0.01',...extra});
const detailLine = (label,value) => [node('dt',{},label),node('dd',{},value ?? '—')];
function confirmAction(title,message,action) {
  let close;
  close=modal(title,node('div',{className:'stack'},notice(message,'warning'),button('确认操作',async()=>{await action();close();toast('操作成功');refresh();},'danger')));
}
function openForm(title,fields,path,transform=x=>x,submit='确认提交',description='',onSuccess=()=>{}) {
  let close;
  const body=form(fields,async values=>{await api(path,{method:'POST',body:transform(values)});onSuccess();close();toast('操作已保存');refresh();},submit,{description});
  close=modal(title,body);
}

export async function renderOrders({root,user,params}) {
  const key=params.get('id');
  if (key) return renderOrderDetail({root,user,params},key);
  const marker=location.hash;
  const offset=Math.max(0,Number(params.get('offset'))||0);
  const filter=params.get('state')||'';
  const orders=await api(`/ui/api/orders?offset=${offset}&state=${encodeURIComponent(filter)}`);
  if(location.hash!==marker)return;
  const visible=orders;
  root.append(node('div',{className:'toolbar'},node('div',{},node('h2',{},user.role==='driver'?'我的充电订单':'充电订单'),node('p',{className:'muted'},'查看计量、账单和资金流水，金额以实际核价为准。')),button('刷新',refresh,'secondary')));
  const controls=form([
    {name:'state',label:'订单状态',type:'select',value:filter,options:[{value:'',label:'全部状态'},{value:'charging',label:'充电中'},{value:'review',label:'待复核'},{value:'billed',label:'待付款'},{value:'paid',label:'已付清'},{value:'cancelled',label:'已取消'}]},
    {name:'id',label:'按订单号打开',type:'number',min:1,placeholder:'输入订单编号'}
  ],v=>{navigate('orders',v.id?{id:v.id}:{offset:0,state:v.state});},'查询');
  root.append(panel('订单查询',controls));
  root.append(panel(`订单明细 · 本页 ${visible.length} 条`,
    dataTable([
      {key:'id',label:'订单',render:r=>button(`#${r.id}`,()=>navigate('orders',{id:r.id}),'link')},
      {key:'state',label:'状态',render:r=>badge(r.state)},
      {key:'station_id',label:'场站',render:r=>`#${r.station_id}`},
      {key:'started_at',label:'开始时间',render:r=>time(r.started_at)},
      {key:'kwh',label:'电量 / kWh',render:r=>r.kwh??'待采样'},
      {key:'gross',label:'原价 / 元',render:r=>money(r.gross)},
      {key:'discount',label:'优惠 / 元',render:r=>money(r.discount)},
      {key:'received',label:'已收 / 元',render:r=>money(r.received)},
      {key:'outstanding',label:'待付 / 元',render:r=>money(r.outstanding)}
    ],visible),
    node('div',{className:'toolbar'},button('上一页',()=>navigate('orders',{offset:Math.max(0,offset-30),state:filter}),'secondary'),node('span',{className:'muted'},`第 ${Math.floor(offset/30)+1} 页 · 每页最多 30 条`),button('下一页',()=>navigate('orders',{offset:offset+30,state:filter}),'secondary'))
  ));
  if(!orders.length)root.append(notice('当前页没有订单。车主可从“找站充电”选择车辆与充电枪开始；已有历史订单可通过编号查询。'));
}

async function renderOrderDetail({root,user},key) {
  const marker=location.hash;
  const result=await api(`/ui/api/orders/${encodeURIComponent(key)}`);
  if(location.hash!==marker)return;
  const o=result.order;
  const p=result.progress||{};
  const active=['starting','charging','finishing'].includes(o.state);
  root.append(node('div',{className:'toolbar'},node('div',{},button('← 返回订单',()=>navigate('orders'),'link'),node('h2',{},`充电订单 #${o.id}`),node('p',{className:'muted'},`场站 #${o.station_id} · 枪 #${o.connector_id} · 车辆 #${o.vehicle_id}`)),node('div',{className:'toolbar'},badge(o.state),button('刷新状态',refresh,'secondary'))));
  root.append(node('div',{className:'stats-grid'},stat('原价 / 元',money(o.gross),'按正式费用分段核价'),stat('优惠 / 元',money(o.discount)),stat('客户应付 / 元',money(o.net_due)),stat('当前待付 / 元',money(o.outstanding))));
  const quality={awaiting_meter:'等待计量采样',missing_start_reading:'缺少起始读数',non_monotonic:'读数发生回退',measured:'已获得可信计量'};
  const progress=node('div',{className:'stack'},
    node('div',{className:'stats-grid'},stat('可信电量 / kWh',p.metered_kwh??'—'),stat(active?'费用预估 / 元':'已核定原价 / 元',money(p.estimated_gross),active?'预估不等于最终账单':'未扣除优惠与退款'),stat('授权总额 / 元',money(o.authorized_amount)),stat('冻结 / 元',money(o.fleet_card_id?o.fleet_hold:o.wallet_hold))),
    notice(quality[p.data_quality]||'计量状态待确认',p.data_quality==='measured'?'success':'warning'),
    node('dl',{className:'detail-list'},detailLine('开始',time(o.started_at)),detailLine('结束',time(o.ended_at)),detailLine('最新读数时间',time(result.latest_meter?.sampled_at)),detailLine('累计电表值 / kWh',result.latest_meter?.reading_kwh??'—'),detailLine('停止请求',time(o.stop_requested_at)),detailLine('采样状态',active&&p.stale?'采样已过期，请等待设备或运维处理':'以服务器计量结果为准'))
  );
  if(o.budget_exceeded)progress.append(notice('计量费用超过授权额度，请处理预算和复核。原始读数已保留。','warning'));
  root.append(panel('充电进度与计量证据',progress));

  const actions=node('div',{className:'toolbar'});
  if(user.role==='driver'&&['starting','charging'].includes(o.state)) {
    actions.append(button(o.stop_requested_at?'已请求停止':'请求停止充电',()=>confirmAction('停止充电', '将向设备记录停止请求。最终电量与账单需等待设备采样和结束核价。',()=>api(`/ui/api/orders/${o.id}/stop`,{method:'POST',body:{}})),o.stop_requested_at?'secondary':'primary'));
    actions.append(button('取消无能耗订单',()=>confirmAction('取消订单','仅尚未产生能耗的订单可以取消；已有计量电量会被拒绝。',()=>api(`/orders/${o.id}/cancel`,{method:'POST',body:{}})),'secondary'));
  }
  if(['driver','fleet','admin','settlement'].includes(user.role)&&['starting','charging','finishing','review'].includes(o.state)) {
    actions.append(button('追加授权额度',()=>openForm('调整授权总额',[numberField('total_budget','新的授权总额 / 元',o.authorized_amount,{min:'0.01'})],`/orders/${o.id}/authorize`,v=>({total_budget:v.total_budget}),'确认授权','填写调整后的总额，并非本次追加差额。冻结和可用余额由服务器核验。'),'secondary'));
  }
  if(staff(user)&&o.state==='review') {
    actions.append(button('人工复核',()=>openForm('复核充电账单',[
      numberField('adjustment','金额调整 / 元','0.00',{min:undefined}),
      {name:'conclusion',label:'复核结论',type:'textarea',required:true,placeholder:'说明计量、异常原因及调整依据'}
    ],`/orders/${o.id}/review`,v=>v,'确认复核')));
  }
  if(actions.childNodes.length)root.append(panel('当前可用操作',actions));

  if(user.role==='driver'&&o.state==='billed') {
    const me=await api('/me');
    if(location.hash!==marker)return;
    const available=me.coupons||[];
    const couponPanel=Number(o.discount)>0?notice('本订单已有优惠，金额已体现在账单中。'):available.length?form([{name:'coupon',label:'选择优惠券',type:'select',required:true,options:opts(available,x=>`${x.name} · ¥${money(x.face)} · 满¥${money(x.minimum)}可用`)}],async v=>{await api(`/orders/${o.id}/coupon`,{method:'POST',body:{coupon:Number(v.coupon)}});toast('优惠已核销');refresh();},'使用优惠券'):notice('暂无可用优惠券。可到个人中心查看活动；服务端会核验活动场站、有效期及门槛。');
    const paymentKey=`charge-ui:${user.id}:payment:${o.id}`;
    const paymentRef=pendingReference(paymentKey,'pay');
    const paymentPayload=pendingPayload(paymentKey);
    const payPanel=form([
      numberField('amount','本次付款 / 元',paymentPayload.amount??o.outstanding,{min:'0.01'}),
      {name:'channel',label:'付款方式',type:'select',value:paymentPayload.channel||'wallet',options:[{value:'wallet',label:'钱包余额'},{value:'mock',label:'模拟支付（不扣银行卡）'}]},
      {name:'reference',label:'本次请求号',value:paymentRef,required:true,readOnly:true}
    ],async v=>{rememberPayload(paymentKey,{amount:v.amount,channel:v.channel});const res=await api(`/orders/${o.id}/pay`,{method:'POST',body:{...v}});clearReference(paymentKey);toast(`付款已记录 · 流水 #${res.payment_id}`);refresh();},'确认付款',{description:'本地演示不连接银行。网络失败后保留请求号和金额重试；刷新后仍沿用，改变金额前请先核对付款流水。'});
    root.append(node('div',{className:'grid-2'},panel('订单优惠',couponPanel),panel('支付账单',payPanel)));
  }
  if(result.samples?.length)root.append(panel('原始电表采样',dataTable([{key:'sampled_at',label:'采样时间',render:r=>time(r.sampled_at)},{key:'reading',label:'累计电表值 / kWh'}],result.samples)));
  root.append(panel('分时费用明细',dataTable([
    {key:'begins',label:'开始',render:r=>time(r.begins)}, {key:'ends',label:'结束',render:r=>time(r.ends)},
    {key:'label',label:'时段',render:r=>({peak:'峰',flat:'平',valley:'谷'}[r.label]||r.label)},
    {key:'kwh',label:'电量 / kWh'}, {key:'energy_rate',label:'电价 / 元',render:r=>rate(r.energy_rate)},
    {key:'energy',label:'电费 / 元',render:r=>money(r.energy)}, {key:'service',label:'服务费 / 元',render:r=>money(r.service)},
    {key:'estimated',label:'边界读数',render:r=>r.estimated?'插值，需核验':'原始采样'}
  ],result.segments||[]),notice('最终原价还可能包含最低收费和人工复核调整；分时明细保留各段计量与费用依据。')));
  if(result.review)root.append(panel('复核依据',node('dl',{className:'detail-list'},detailLine('复核原因',result.review.reason),detailLine('费用调整 / 元',money(result.review.adjustment)),detailLine('复核结论',result.review.conclusion),detailLine('复核时间',time(result.review.reviewed_at)))));
  root.append(panel('付款流水',dataTable([
    {key:'id',label:'流水号',render:r=>`#${r.id}`}, {key:'channel',label:'渠道',render:r=>({wallet:'钱包',mock:'模拟支付',fleet:'车队'}[r.channel]||r.channel)},
    {key:'amount',label:'金额 / 元',render:r=>money(r.amount)}, {key:'succeeded',label:'结果',render:r=>badge(r.succeeded?'paid':'failed')},
    {key:'reference',label:'请求号'},
    {key:'actions',label:'操作',render:r=>staff(user)&&r.succeeded?button('退款',()=>refundForm(r,user),'secondary'):'—'}
  ],result.payments||[])));
  if(result.refunds?.length)root.append(panel('退款记录',dataTable([
    {key:'id',label:'退款号'}, {key:'payment_id',label:'原付款'}, {key:'amount',label:'退款 / 元',render:r=>money(r.amount)},
    {key:'debt_reduction',label:'客户应付减少 / 元',render:r=>money(r.debt_reduction)}, {key:'reference',label:'请求号'}
  ],result.refunds)));
  if(result.invoices?.length||result.requests?.length)root.append(panel('消费开票记录',
    dataTable([{key:'id',label:'申请号'},{key:'title',label:'抬头'},{key:'state',label:'申请状态',render:r=>badge(r.state)}],result.requests||[]),
    dataTable([{key:'id',label:'票据号'},{key:'title',label:'抬头'},{key:'amount',label:'金额 / 元',render:r=>money(r.amount)},{key:'original_id',label:'类型',render:r=>r.original_id?`红冲原票 #${r.original_id}`:'蓝票'}],result.invoices||[])
  ));
  if(user.role==='driver') {
    const box=node('div',{className:'grid-2'});
    if(o.state==='paid'&&!(result.requests||[]).length)box.append(panel('申请消费发票',form([{name:'title',label:'发票抬头',required:true,placeholder:'个人或单位名称'}],async v=>{const r=await api(`/orders/${o.id}/invoice-request`,{method:'POST',body:v});toast(`申请已提交 #${r.id}`);refresh();},'提交申请')));
    else if(o.state==='paid')box.append(panel('消费发票申请',notice('本订单已有开票申请，请查看上方的申请和票据处理记录。')));
    box.append(panel('订单反馈',form([
      {name:'kind',label:'反馈类型',type:'select',value:'rating',options:[{value:'rating',label:'评价建议'},{value:'fault',label:'故障反馈'}]},
      {name:'content',label:'内容',type:'textarea',required:true,placeholder:'请简要说明，最多255字'}
    ],async v=>{if(v.content.length>255)throw new Error('反馈内容最多255字');await api(`/orders/${o.id}/feedback`,{method:'POST',body:v});toast('反馈已提交');},'提交反馈')));
    root.append(box);
  }
}

function refundForm(payment,user) {
  const key=`charge-ui:${user.id}:refund:${payment.id}`;
  const pending=pendingPayload(key);
  openForm(`退款 · 原付款 #${payment.id}`,[
    numberField('amount','本次退款 / 元',pending.amount??'',{min:'0.01'}),
    {name:'kind',label:'退款原因',type:'select',value:pending.kind||'price_adjustment',options:[{value:'price_adjustment',label:'调减客户应付（价格调整）'},{value:'payment_reversal',label:'撤销原付款（恢复欠款）'}]},
    {name:'reference',label:'退款请求号',value:pendingReference(key,'refund'),required:true,readOnly:true}
  ],`/payments/${payment.id}/refund`,v=>{rememberPayload(key,{amount:v.amount,kind:v.kind});return v;},'确认退款','两种退款对客户欠款的影响不同。失败后沿用原请求号重试，改变金额或原因前请先核对退款流水。',()=>clearReference(key));
}

function minuteLabel(v){const n=Number(v);return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;}
export async function renderTariffs({root,params}) {
  const marker=location.hash;
  const lookups=await api('/ui/api/lookups');
  if(location.hash!==marker)return;
  const selected=params.get('station')||'';
  const tariffs=(lookups.tariffs||[]).filter(x=>!selected||String(x.station_id)===selected);
  root.append(node('h2',{},'计费规则'),node('p',{className:'muted'},'按版本查看电价、服务费、免费时长、最低收费与预授权。已发生订单保留原费率依据。'));
  root.append(panel('选择场站',form([{name:'station',label:'场站',type:'select',value:selected,options:[{value:'',label:'全部场站'},...opts(lookups.stations||[],x=>`${x.name} · #${x.id}`)]}],v=>navigate('tariffs',{station:v.station}),'筛选')));
  if(!tariffs.length)root.append(notice('当前范围内没有费率版本。'));
  for(const t of tariffs)root.append(panel(`费率 #${t.id} · 场站 #${t.station_id}${t.fleet_id?` · 车队 #${t.fleet_id}`:' · 公共费率'}`,
    node('dl',{className:'detail-list'},detailLine('有效期',`${time(t.starts)} 至 ${time(t.ends)}`),detailLine('服务费方式',t.service_mode==='hour'?'按时长 / 元每小时':'按电量 / 元每kWh'),detailLine('免费服务时长',`${t.free_minutes} 分钟`),detailLine('最低收费',`¥ ${money(t.minimum)}`),detailLine('开单预授权',`¥ ${money(t.authorization_amount)}`)),
    dataTable([{key:'label',label:'时段',render:r=>({peak:'峰',flat:'平',valley:'谷'}[r.label]||r.label)},{key:'range',label:'每日区间',render:r=>`${minuteLabel(r.minute_from)} — ${minuteLabel(r.minute_to)}`},{key:'energy_rate',label:'电费 / 元每kWh',render:r=>rate(r.energy_rate)},{key:'service_rate',label:t.service_mode==='hour'?'服务费 / 元每小时':'服务费 / 元每kWh',render:r=>rate(r.service_rate)}],t.bands||[])
  ));
}

import {api,node,button,form,panel,dataTable,badge,money,stat,notice,toast,modal,navigate,refresh} from './core.js';

const time=v=>{
  if(!v)return '—';
  const d=new Date(v);
  return Number.isNaN(d.valueOf())?String(v):new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d);
};
const options=(rows,label)=>rows.map(r=>({value:r.id,label:label(r)}));
const ref=prefix=>`${prefix}-${crypto.randomUUID()}`;
function pendingReference(key,prefix) {
  try {const current=sessionStorage.getItem(key);if(current)return current;const created=ref(prefix);sessionStorage.setItem(key,created);return created;}
  catch {return ref(prefix);}
}
function pendingPayload(key) {try {const v=JSON.parse(sessionStorage.getItem(`${key}:payload`)||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:{};}catch {return {};}}
function rememberPayload(key,value) {try {sessionStorage.setItem(`${key}:payload`,JSON.stringify(value));}catch {}}
function clearReference(key) {try {sessionStorage.removeItem(key);sessionStorage.removeItem(`${key}:payload`);}catch {}}
const localInput=(days=0)=>{const d=new Date();d.setDate(d.getDate()+days);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;};
const field=(name,label,value='',extra={})=>({name,label,value,required:true,...extra});
function dialogForm(title,fields,save,label='保存',description='') {
  let close;
  const content=form(fields,async values=>{await save(values);close();toast('操作成功');refresh();},label,{description});
  close=modal(title,content);
}
function confirmAction(title,message,save) {
  let close;
  close=modal(title,node('div',{className:'stack'},notice(message,'warning'),button('确认',async()=>{await save();close();toast('操作成功');refresh();},'danger')));
}

export async function renderMembers(ctx) {
  if(ctx.user.role==='admin')return renderManagement(ctx);
  if(ctx.user.role==='fleet')return renderFleet(ctx);
  if(ctx.user.role!=='driver') {
    ctx.root.append(notice('当前身份可通过左侧菜单进入自己的业务工作区。'));
    return;
  }
  const {root}=ctx;
  const marker=location.hash;
  const [me,campaigns,summary]=await Promise.all([api('/me'),api('/ui/api/campaigns'),api('/ui/api/dashboard')]);
  if(location.hash!==marker)return;
  const account=me.account;
  const wallet=summary.wallet||{};
  root.append(node('div',{className:'toolbar'},node('div',{},node('h2',{},'我的账户'),node('p',{className:'muted'},`${account.login} · ${account.phone_mask||'未登记手机号'} · 账户 #${account.id}`)),badge(account.verified?'verified':'pending')));
  root.append(node('div',{className:'stats-grid'},stat('钱包余额 / 元',money(wallet.balance??account.balance)),stat('冻结金额 / 元',money(wallet.reserved_balance),'用于充电预授权'),stat('可用余额 / 元',money(wallet.available_balance)),stat('会员等级',({regular:'普通会员',silver:'银卡会员',gold:'金卡会员'}[account.tier]||account.tier))));
  if(!account.verified)root.append(notice('账户尚待管理员核验。核验完成后才能使用要求实名审核的充电业务。','warning'));
  const topupKey=`charge-ui:${account.id}:topup`;
  const topupPayload=pendingPayload(topupKey);
  const recharge=form([
    field('amount','模拟充值金额 / 元',topupPayload.amount??'100.00',{type:'number',min:'0.01',max:10000,step:'0.01'}),
    field('request_id','本次充值请求号',pendingReference(topupKey,'topup'),{readOnly:true})
  ],async v=>{rememberPayload(topupKey,{amount:v.amount});const r=await api('/wallet/mock-topups',{method:'POST',body:v});clearReference(topupKey);toast(`模拟充值成功 · 流水 #${r.wallet_entry_id}`);refresh();},'确认模拟充值',{description:'课程演示资金，不扣银行卡。失败后保留请求号和金额，刷新后仍沿用；改变金额前先核对流水，成功后才生成下一次请求号。'});
  root.append(node('div',{className:'grid-2'},panel('钱包充值',recharge),panel('资金流水 · 最近30条',dataTable([
    {key:'id',label:'流水'}, {key:'change',label:'变动 / 元',render:r=>money(r.change)},
    {key:'source',label:'来源',render:r=>r.topup_ref?'模拟充值':r.refund_id?`退款 #${r.refund_id}`:r.payment_id?`付款 #${r.payment_id}`:'资金记录'},
    {key:'happened_at',label:'时间',render:r=>time(r.happened_at)}
  ],me.wallet||[]))));
  root.append(panel('我的车辆',
    node('div',{className:'toolbar'},node('p',{className:'muted'},'车牌以脱敏形式展示。新增车辆同时建立本人的有效绑定。'),button('绑定新车辆',addVehicle)),
    dataTable([
      {key:'id',label:'车辆号',render:r=>`#${r.id}`},{key:'plate_mask',label:'脱敏车牌'},{key:'model',label:'车型'},
      {key:'actions',label:'操作',render:r=>button('解除绑定',()=>confirmAction('解除车辆绑定','存在进行中的充电订单时不能解绑。历史订单和车辆记录会继续保留。',()=>api(`/vehicles/${r.id}/binding`,{method:'DELETE'})),'secondary')}
    ],me.vehicles||[])
  ));
  root.append(panel('我的有效优惠券',dataTable([
    {key:'id',label:'券号'}, {key:'name',label:'活动'}, {key:'face',label:'面额 / 元',render:r=>money(r.face)},
    {key:'minimum',label:'消费门槛 / 元',render:r=>money(r.minimum)}, {key:'station_id',label:'适用场站',render:r=>r.station_id?`#${r.station_id}`:'所有场站'},
    {key:'expires',label:'到期',render:r=>time(r.expires)}
  ],me.coupons||[]),notice('在待付款订单详情中选择优惠券，活动条件与可抵扣金额由服务器核验。')));
  root.append(panel('会员活动',campaignTable(campaigns,true)));
  root.append(panel('发票与反馈',node('p',{className:'muted'},'打开本人订单可提交消费发票申请、查看蓝红票和反馈使用情况。'),button('进入我的订单',()=>navigate('orders'),'secondary')));
}

function addVehicle() {
  dialogForm('新增并绑定车辆',[
    field('plate','车牌号码','',{placeholder:'登记后以脱敏车牌展示'}),field('model','车型',''),
    field('capacity_kwh','电池容量 / kWh','60',{type:'number',min:'0.01',step:'0.01'}),
    field('max_kw','车辆最大充电功率 / kW','60',{type:'number',min:'0.01',step:'0.01'}),
    field('supports_dc','支持直流快充',true,{type:'checkbox',required:false}),
    field('interface','充电接口','GB/T')
  ],v=>api('/vehicles',{method:'POST',body:{...v,supports_dc:!!v.supports_dc}}),'绑定车辆');
}

function campaignTable(rows,canClaim) {
  return dataTable([
    {key:'name',label:'活动'}, {key:'face',label:'券额 / 元',render:r=>money(r.face)},
    {key:'minimum',label:'门槛 / 元',render:r=>money(r.minimum)},
    {key:'station_id',label:'场站',render:r=>r.station_id?`#${r.station_id}`:'全部'},
    {key:'expires',label:'结束时间',render:r=>time(r.expires)},
    {key:'issued',label:'已发 / 总量',render:r=>`${r.issued??'—'} / ${r.stock??'—'}`},
    {key:'action',label:canClaim?'领取':'会员条件',render:r=>!canClaim?(r.tier||'不限等级'):r.claimable?button('领取优惠券',async()=>{const x=await api(`/campaigns/${r.id}/claim`,{method:'POST',body:{}});toast(`领取成功 · 券 #${x.id}`);refresh();},'secondary'):(r.reason||(r.claimed?'已领取':'当前不可领取'))}
  ],rows||[]);
}

async function renderManagement({root,params}) {
  const marker=location.hash;
  const offset=Math.max(0,Number(params.get('offset'))||0);
  const keyword=params.get('name')||'';
  const [users,campaigns,lookups]=await Promise.all([api(`/ui/api/users?offset=${offset}&name=${encodeURIComponent(keyword)}`),api('/ui/api/campaigns'),api('/ui/api/lookups')]);
  if(location.hash!==marker)return;
  root.append(node('div',{className:'toolbar'},node('div',{},node('h2',{},'会员与活动'),node('p',{className:'muted'},'核验车主、管理车辆归属，并查看活动发放情况。')),button('刷新',refresh,'secondary')));
  root.append(panel('用户核验',form([{name:'name',label:'登录名搜索',value:keyword,placeholder:'按登录名搜索'}],v=>navigate('members',{name:v.name,offset:0}),'查询'),dataTable([
    {key:'id',label:'账号号'}, {key:'login',label:'登录名'}, {key:'role',label:'角色',render:r=>({driver:'车主',fleet:'车队负责人',admin:'管理员',maintenance:'维修',settlement:'结算人员',operator:'运营商'}[r.role]||r.role)},
    {key:'phone_mask',label:'脱敏手机'}, {key:'tier',label:'等级'},
    {key:'verified',label:'核验',render:r=>badge(r.verified?'verified':'pending')},
    {key:'action',label:'操作',render:r=>r.role==='driver'&&!r.verified?button('核验通过',()=>confirmAction('核验车主',`确认已核验账号 ${r.login} 的资料？`,()=>api(`/admin/users/${r.id}/verify`,{method:'POST',body:{}})),'secondary'):'—'}
  ],users),node('div',{className:'toolbar'},button('上一页',()=>navigate('members',{name:keyword,offset:Math.max(0,offset-50)}),'secondary'),node('span',{className:'muted'},`第 ${Math.floor(offset/50)+1} 页 · 每页最多50条`),button('下一页',()=>navigate('members',{name:keyword,offset:offset+50}),'secondary'))));
  root.append(panel('车辆与归属',
    dataTable([{key:'id',label:'车辆号'},{key:'plate_mask',label:'脱敏车牌'},{key:'model',label:'车型'},{key:'login',label:'当前车主',render:r=>r.login||r.account_id&&`#${r.account_id}`||'未绑定'},{key:'actions',label:'操作',render:r=>button('转移绑定',()=>transferVehicle(r,lookups.users||users),'secondary')}],lookups.vehicles||[]),
    notice('转移只允许已核验车主接收；正在充电的车辆不能转移，原绑定结束后保留历史。')
  ));
  root.append(panel('会员活动',node('div',{className:'toolbar'},button('创建活动',()=>newCampaign(lookups))),campaignTable(campaigns,false)));
  root.append(panel('车队业务',node('p',{className:'muted'},'车队、卡片额度与月账单在独立工作区维护。'),button('进入车队工作区',()=>navigate('fleet'),'secondary')));
}

function transferVehicle(vehicle,users) {
  const drivers=users.filter(x=>x.role==='driver'&&x.verified);
  if(!drivers.length){toast('没有已核验的车主可接收车辆','warning');return;}
  dialogForm(`转移车辆 #${vehicle.id}`, [{name:'account',label:'新车主',type:'select',required:true,options:options(drivers,x=>`${x.login} · #${x.id}`)}],v=>api(`/admin/vehicles/${vehicle.id}/transfer`,{method:'POST',body:{account:Number(v.account)}}),'确认转移');
}

function newCampaign(lookups) {
  dialogForm('创建会员活动',[
    field('name','活动名称'),field('face','优惠券面额 / 元','2.00',{type:'number',min:'0.01',step:'0.01'}),
    field('minimum','消费门槛 / 元','10.00',{type:'number',min:0,step:'0.01'}),
    field('station','适用场站','',{type:'select',required:false,options:[{value:'',label:'所有场站'},...options(lookups.stations||[],x=>`${x.name} · #${x.id}`)]}),
    field('tier','会员等级条件','',{required:false,placeholder:'留空表示不限；如 regular'}),
    field('starts','开始时间',localInput(),{type:'datetime-local'}),field('expires','结束时间',localInput(30),{type:'datetime-local'}),
    field('stock','总发行量','100',{type:'number',min:0,step:1})
  ],v=>api('/campaigns',{method:'POST',body:{...v,station:v.station?Number(v.station):null,tier:v.tier||null,stock:Number(v.stock)}}),'创建活动');
}

export async function renderFleet({root,user,params}) {
  const marker=location.hash;
  const [fleets,cards,lookups]=await Promise.all([api('/fleets'),api('/ui/api/fleet-cards'),api('/ui/api/lookups')]);
  if(location.hash!==marker)return;
  const selected=params.get('id')||'';
  const current=fleets.find(f=>String(f.id)===selected)||fleets[0];
  root.append(node('div',{className:'toolbar'},node('div',{},node('h2',{},'企业车队'),node('p',{className:'muted'},'按车队核对卡片、授权额度与月度消费。')),user.role==='admin'?button('创建车队',()=>newFleet(lookups)):button('刷新',refresh,'secondary')));
  if(!fleets.length){root.append(notice('当前账号没有可管理的车队。请由管理员创建车队并指定负责人。'));return;}
  root.append(panel('选择车队',form([{name:'id',label:'车队',type:'select',value:current.id,options:options(fleets,x=>`${x.name} · #${x.id}`)}],v=>navigate('fleet',{id:v.id}),'切换')));
  const ownCards=cards.filter(c=>Number(c.fleet_id)===Number(current.id));
  root.append(node('div',{className:'stats-grid'},stat('车队名称',current.name),stat('当前卡片',String(ownCards.length),'仅当前权限范围'),stat('负责人编号',`#${current.manager_id}`)));
  root.append(panel('车队卡与额度',
    node('div',{className:'toolbar'},button('新增车队卡',()=>addFleetCard(current,lookups)),button('查看所属订单',()=>navigate('orders'),'secondary')),
    dataTable([
      {key:'id',label:'卡号'}, {key:'vehicle_id',label:'车辆',render:r=>r.plate_mask||`#${r.vehicle_id}`},
      {key:'driver_id',label:'车主',render:r=>r.driver_login||r.login||`#${r.driver_id}`},
      {key:'credit_limit',label:'月额度 / 元',render:r=>money(r.credit_limit)}, {key:'reserved_amount',label:'冻结 / 元',render:r=>money(r.reserved_amount)},
      {key:'enabled',label:'状态',render:r=>badge(r.enabled?'enabled':'disabled')},
      {key:'action',label:'操作',render:r=>button('修改额度与状态',()=>editFleetCard(r),'secondary')}
    ],ownCards)
  ));
  const months=await api(`/fleets/${current.id}/months`);
  if(location.hash!==marker)return;
  root.append(panel('车队月账单',dataTable([
    {key:'period',label:'账期',render:r=>String(r.period).slice(0,10)}, {key:'orders',label:'订单数'},
    {key:'amount',label:'客户应付 / 元',render:r=>money(r.amount)}, {key:'paid',label:'实付 / 元',render:r=>money(r.paid)},
    {key:'outstanding',label:'欠款 / 元',render:r=>money(r.outstanding)}
  ],months)));
  root.append(notice('追加充电预算请进入对应订单；卡片月额度与单笔订单授权是不同约束。新车队首次发卡由管理员完成，负责人之后可在已有本企业车辆范围内管理。'));
}

function newFleet(lookups) {
  const managers=(lookups.users||[]).filter(x=>x.role==='fleet');
  if(!managers.length){toast('没有可选的车队负责人账号','warning');return;}
  dialogForm('创建企业车队',[field('name','车队名称'),field('manager','负责人','',{type:'select',options:options(managers,x=>`${x.login} · #${x.id}`)})],v=>api('/fleets',{method:'POST',body:{name:v.name,manager:Number(v.manager)}}),'创建车队');
}
function addFleetCard(fleet,lookups) {
  const vehicles=(lookups.vehicles||[]).filter(v=>v.account_id||v.owner_id);
  if(!vehicles.length){toast('当前没有可发卡的已绑定车辆。新车队首次发卡请由管理员办理。','warning');return;}
  dialogForm(`新增车队卡 · ${fleet.name}`, [
    field('vehicle','车辆及车主','',{type:'select',options:options(vehicles,x=>`${x.plate_mask||x.model} · ${x.login||`车主#${x.account_id||x.owner_id}`} · 车辆#${x.id}`)}),
    field('limit','月额度 / 元','500.00',{type:'number',min:0,step:'0.01'})
  ],v=>{const car=vehicles.find(x=>String(x.id)===String(v.vehicle));return api(`/fleets/${fleet.id}/cards`,{method:'POST',body:{vehicle:Number(v.vehicle),driver:Number(car.account_id||car.owner_id),limit:v.limit}});},'发放车队卡');
}
function editFleetCard(card) {
  dialogForm(`编辑车队卡 #${card.id}`,[field('credit_limit','月额度 / 元',card.credit_limit,{type:'number',min:0,step:'0.01'}),field('enabled','启用卡片',!!card.enabled,{type:'checkbox',required:false})],v=>api(`/ui/api/fleet-cards/${card.id}`,{method:'PATCH',body:{credit_limit:v.credit_limit,enabled:!!v.enabled}}),'保存卡片','新限额不能低于已用及冻结额度，服务器会执行最终校验。');
}

import {api,node,button,panel,dataTable,badge,money,stat,notice,navigate,refresh,loadSession,roleName,state,dateTime} from './core.js';
import {renderStations,renderQueue,renderFacilities} from './assets.js';
import {renderOrders,renderTariffs} from './orders.js';
import {renderMembers,renderFleet} from './members.js';
import {renderMonitor,renderSettlements,renderInvoices,renderDemo} from './operations.js';

const pages={
  dashboard:{title:'运营总览',eyebrow:'WORKSPACE OVERVIEW',description:'查看真实业务状态，继续处理当前工作。',icon:'◫',roles:['admin','driver','maintenance','settlement','operator','fleet'],render:renderDashboard},
  stations:{title:'查找充电场站',eyebrow:'STATIONS & CHARGING',description:'查看设备可用状态，选择车辆估价并开始充电。',icon:'⌖',roles:['admin','driver'],render:renderStations},
  queue:{title:'我的到站排队',eyebrow:'ARRIVAL QUEUE',description:'查看叫号进度与留枪截止时间。',icon:'☷',roles:['driver'],render:renderQueue},
  orders:{title:'充电订单',eyebrow:'ORDERS & BILLING',description:'从计量证据到分段费用，查看每笔订单的资金变化。',icon:'▤',roles:['admin','driver','settlement','fleet'],render:renderOrders},
  facilities:{title:'场站与设施',eyebrow:'ASSET MANAGEMENT',description:'维护运营商、场站、桩枪档案与设备投运验收。',icon:'▥',roles:['admin'],render:renderFacilities},
  monitor:{title:'设备监控与工单',eyebrow:'MONITORING & MAINTENANCE',description:'跟进告警、维修节点及恢复依据。',icon:'⌁',roles:['admin','maintenance'],render:renderMonitor},
  members:{title:'用户与会员',eyebrow:'MEMBERS & WALLET',description:'管理车辆、账户、钱包、活动与会员权益。',icon:'♧',roles:['admin','driver'],render:renderMembers},
  fleet:{title:'企业车队',eyebrow:'FLEET OPERATIONS',description:'查看本企业的用车卡、授权额度与月度账单。',icon:'▱',roles:['admin','fleet'],render:renderFleet},
  settlements:{title:'结算与对账',eyebrow:'SETTLEMENT & RECONCILIATION',description:'核对账期、外部账单及平台与运营商的确认意见。',icon:'▦',roles:['admin','settlement','operator'],render:renderSettlements},
  invoices:{title:'票据工作区',eyebrow:'INVOICES',description:'处理消费开票申请，保留原票与红冲记录。',icon:'▧',roles:['admin','settlement'],render:renderInvoices},
  tariffs:{title:'计费规则',eyebrow:'PRICING RULES',description:'查看真实费率版本、分时电价和服务费规则。',icon:'◷',roles:['admin','driver','settlement','fleet','operator'],render:renderTariffs},
  demo:{title:'模拟控制台',eyebrow:'SIMULATION CONSOLE',description:'管理员专用 · 所有设备、支付与告警输入用于课程演示。',icon:'⚑',roles:['admin'],render:renderDemo},
};

const host=document.getElementById('view-content');
let generation=0;
async function renderRoute(){
  const [name='dashboard',query='']=location.hash.slice(1).split('?');
  const page=pages[name] || pages.dashboard;
  document.querySelectorAll('.nav-item').forEach(e=>e.classList.toggle('active',e.dataset.page===name));
  document.getElementById('page-title').textContent=name==='members'&&state.session.role==='driver'?'我的车辆与钱包':name==='dashboard'&&state.session.role==='driver'?'我的充电空间':page.title;
  document.getElementById('page-description').textContent=page.description;
  document.getElementById('page-eyebrow').textContent=page.eyebrow;
  document.getElementById('breadcrumb').textContent=page.title;
  document.title=page.title+' · 充电运营';
  const current=++generation;
  const root=node('div',{className:'view-body'});
  root.append(node('div',{className:'loading-state'},'正在读取业务数据…'));host.replaceChildren(root);
  if(!page.roles.includes(state.session.role)){root.replaceChildren(notice('当前角色没有此页面的访问权限。','error'));return;}
  try {
    const content=node('div',{});
    await page.render({root:content,user:state.session,params:new URLSearchParams(query)});
    if(current===generation)root.replaceChildren(content);
  } catch(e){if(current===generation)root.replaceChildren(notice(e.message || '读取失败，请重试','error'),button('重新加载',refresh,'secondary'));}
}

async function renderDashboard({root,user}){
  const data=await api('/ui/api/dashboard');
  root.append(node('div',{className:'hero-strip'},node('div',{},node('h2',{},`${roleName(user.role)}，欢迎回来。`),node('p',{},`当前账号 ${user.login} · 数据更新于 ${dateTime(data.server_time)}`)),node('span',{className:'hero-symbol','aria-hidden':'true'},'ϟ')));
  root.append(node('div',{className:'stats-grid'},(data.metrics || []).map(m=>stat(m.label,m.value,m.hint))));
  const shortcuts={admin:[['facilities','站桩档案'],['monitor','运维闭环'],['settlements','账期对账'],['demo','模拟输入']],driver:[['stations','开始一次充电'],['orders','查看我的账单'],['members','车辆与钱包'],['queue','到站排队']],maintenance:[['monitor','处理我的工单']],settlement:[['settlements','核对本期结算'],['orders','订单复核'],['invoices','处理开票申请']],operator:[['settlements','核对与签字']],fleet:[['fleet','管理企业用车'],['orders','查看企业订单']]};
  root.append(panel('快速进入',node('div',{className:'quick-grid'},(shortcuts[user.role] || []).map(([key,hint])=>node('button',{className:'quick-link',onClick:()=>navigate(key)},node('span',{className:'quick-icon','aria-hidden':'true'},pages[key].icon),node('span',{},pages[key].title,node('small',{},hint)))))));
  if(data.recent_orders?.length)root.append(panel(node('div',{className:'toolbar'},node('h2',{},'最近充电订单'),button('查看全部 →',()=>navigate('orders'),'ghost small')),dataTable([{label:'订单',render:r=>button(`#${r.id}`,()=>navigate('orders',{id:r.id}),'ghost small')},{key:'station_id',label:'场站'},{label:'状态',render:r=>badge(r.state)},{label:'原价 / 元',render:r=>money(r.gross)},{label:'已收 / 元',render:r=>money(r.received)},{label:'待付 / 元',render:r=>money(r.outstanding)},{label:'开始时间',render:r=>dateTime(r.started_at)}],data.recent_orders)));
  const sections=node('div',{className:'grid-2'});
  if(data.recent_alarms?.length)sections.append(panel('待跟进告警',dataTable([{key:'id',label:'编号'},{key:'charger_id',label:'充电桩'},{key:'code',label:'告警代码'},{key:'severity',label:'级别'},{label:'查看',render:r=>button('处理 →',()=>navigate('monitor',{alarm:r.id}),'ghost small')}],data.recent_alarms)));
  if(data.recent_settlements?.length)sections.append(panel('最近结算',dataTable([{key:'id',label:'结算号'},{key:'period',label:'账期'},{label:'状态',render:r=>badge(r.state)},{label:'应结 / 元',render:r=>money(r.due)},{label:'查看',render:r=>button('详情 →',()=>navigate('settlements',{id:r.id}),'ghost small')}],data.recent_settlements)));
  if(sections.childElementCount)root.append(sections);
  root.append(notice(user.role==='admin'?'历史案例与新操作共用真实数据库。订单 #1 可用于讲解跨时段账单；模拟设备输入请进入“模拟控制台”。':user.role==='driver'?'开始前请确认车辆已添加、钱包余额充足。设备心跳过期或场站暂停营业时，充电枪会如实显示不可用。':'页面仅展示当前账号允许访问的数据。请使用本人角色完成操作，确认后可在 MySQL Workbench 按业务编号核验。'));
}

try {
  const session=await loadSession();
  if(!session.authenticated)location.replace('/ui/login');
  else {
    document.getElementById('account-label').textContent=`${session.user.login} · ${roleName(session.user.role)}`;
    document.getElementById('account-button').textContent=roleName(session.user.role).slice(0,1);
    document.getElementById('navigation').append(node('div',{className:'nav-group-label'},'业务工作区'));
    Object.entries(pages).filter(([,p])=>p.roles.includes(session.user.role)).forEach(([key,p])=>{
      if(key==='demo')document.getElementById('navigation').append(node('div',{className:'nav-group-label'},'演示工具'));
      document.getElementById('navigation').append(node('a',{href:'#'+key,className:'nav-item',dataset:{page:key}},node('span',{className:'nav-icon','aria-hidden':'true'},p.icon),key==='members'&&session.user.role==='driver'?'车辆与钱包':p.title));
    });
    document.getElementById('logout-button').addEventListener('click',async()=>{try{await api('/auth/logout',{method:'POST'});location.replace('/ui/login');}catch(e){host.prepend(notice(e.message,'error'));}});
    document.getElementById('refresh-button').addEventListener('click',refresh);
    document.getElementById('account-button').addEventListener('click',()=>navigate(session.user.role==='driver'?'members':'dashboard'));
    window.addEventListener('hashchange',renderRoute);await renderRoute();
  }
} catch(e){host.replaceChildren(notice(e.message,'error'));}

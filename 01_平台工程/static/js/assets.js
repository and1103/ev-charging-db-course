import {api,node,button,form,panel,dataTable,badge,money,stat,notice,toast,modal,navigate,refresh,dateTime} from './core.js';

const opts = (rows,label) => rows.map(x=>({value:x.id,label:label(x)}));
const vehicleOptions = rows=>opts(rows,x=>`${x.plate_mask || '车辆 '+x.id} · ${x.model}`);
const idSelect = (label,name,options,value='')=>({label,name,type:'select',required:true,options,value});
function openCharging(gun,vehicles,cards=[]) {
  if(!vehicles.length) { toast('请先在会员中心添加车辆','error'); navigate('members'); return; }
  let close;
  const fields=[idSelect('充电车辆','vehicle',vehicleOptions(vehicles)),{label:'支付方式','name':'card',type:'select',options:[{value:'',label:'个人钱包'},...cards.map(x=>({value:x.id,label:`企业卡 #${x.id} · ${x.fleet_name || ''} · 车辆${x.vehicle_id}`}))]}];
  close=modal(`使用充电枪 #${gun}`,node('div',{},notice('开单时由服务端检查设备、排队资格与余额，并冻结本次预授权额度。请先确保钱包有足够余额。'),form(fields,async value=>{
    const result=await api('/orders',{method:'POST',body:{vehicle:Number(value.vehicle),gun:Number(gun),...(value.card?{card:Number(value.card)}:{})}});
    close();toast(`订单 #${result.id} 已创建`);navigate('orders',{id:result.id});
  },'确认开单')));
}

export async function renderStations({root,user,params}) {
  const term=params.get('q') || '', offset=Math.max(0,Number(params.get('offset')) || 0);
  const [stations,lookups,cards]=await Promise.all([api(`/stations?name=${encodeURIComponent(term)}&offset=${offset}`),api('/ui/api/lookups'),user.role==='driver'?api('/ui/api/fleet-cards'):Promise.resolve([])]);
  const vehicles=lookups.vehicles || [];
  const search=form([{label:'场站名称',name:'q',value:term,placeholder:'搜索场站名称'}],v=>navigate('stations',{q:v.q}),'查找场站',{inline:true});
  root.append(panel(null,search));
  const chosen=Number(params.get('id'));
  const list=node('div',{className:'station-grid'});
  stations.forEach(s=>{
    const record=lookups.stations.find(x=>x.id===s.id) || {};
    const card=node('article',{className:`station-card ${s.id===chosen?'active':''}`},
      node('div',{className:'station-title'},node('h2',{},s.name),badge(s.enabled?'active':'offline')),
      node('p',{className:'station-address'},s.address),
      node('div',{className:'station-meter'},node('span',{},node('strong',{},s.available),node('small',{},'可用充电枪')),node('span',{},node('strong',{},s.waiting),node('small',{},'正在排队'))),
      node('div',{className:'actions'},node('small',{className:'muted'},record.opens===record.closes?'全天营业':`${record.opens || '—'} — ${record.closes || '—'}`),button('查看充电枪 →',()=>navigate('stations',{q:term,id:s.id,offset}),'secondary small')));
    list.append(card);
  });
  if(stations.length) root.append(list); else root.append(panel('查询结果',dataTable([],[])));
  root.append(node('div',{className:'pager'},button('上一页',()=>navigate('stations',{q:term,offset:Math.max(0,offset-30)}),'secondary small'),`第 ${Math.floor(offset/30)+1} 页 · 本页 ${stations.length} 个场站`,button('下一页',()=>{if(stations.length===30)navigate('stations',{q:term,offset:offset+30});else toast('已经是最后一页');},'secondary small')));
  if(!chosen) {root.append(notice('设备可用量包含营业时间、投运、心跳和留枪检查。历史样例心跳过期时会显示不可用，管理员可在模拟控制中发送心跳。'));return;}
  const station=lookups.stations.find(x=>x.id===chosen);
  if(!station){root.append(notice('当前场站不存在或不在你的查询范围内','error'));return;}
  const guns=await api(`/stations/${chosen}/guns`);
  const detail=panel(`${station.name} · 充电枪`,node('p',{className:'muted'},station.parking_note || station.address),dataTable([
    {key:'id',label:'枪编号',render:g=>`#${g.id}`},{key:'kind',label:'枪型',render:g=>g.kind==='DC'?'直流快充':'交流慢充'},
    {key:'interface',label:'接口'},{key:'max_kw',label:'额定功率',render:g=>`${g.max_kw} kW`},
    {key:'state',label:'设备状态',render:g=>badge(g.state)},
    {label:'当前资格',render:g=>g.available?badge('idle'):node('span',{className:'muted'},'暂不可用 / 留枪中')},
    {label:'操作',render:g=>user.role==='driver'?node('div',{className:'actions'},button('费用估算',()=>estimate(g,vehicles,cards),'secondary small'),g.available?button('开始充电',()=>openCharging(g.id,vehicles,cards),'primary small'):null):button('设备管理',()=>navigate('facilities',{table:'connector'}),'secondary small')},
  ],guns));
  if(user.role==='driver') detail.append(node('div',{className:'toolbar'},button('到站取号排队',()=>{
    if(!vehicles.length){navigate('members');return;}
    let close;close=modal('到站取号',form([idSelect('我的车辆','vehicle',vehicleOptions(vehicles))],async v=>{
      const result=await api('/queue',{method:'POST',body:{vehicle:Number(v.vehicle),station:chosen}});close();toast(`排队号 #${result.id} 已生成`);navigate('queue');
    },'确认取号'));
  },'secondary')));
  root.append(detail);
}

function estimate(g,vehicles,cards) {
  if(!vehicles.length){toast('请先添加车辆','error');navigate('members');return;}
  const result=node('div',{});
  const now=new Date(Date.now()+8*3600000).toISOString().slice(0,16);
  modal(`费用估算 · 枪 #${g.id}`,node('div',{},notice('这是按所选车辆、SOC与时刻计算的报价。实际账单以计量记录及结束核价为准。'),form([
    idSelect('我的车辆','vehicle',vehicleOptions(vehicles)),{label:'计划到站时刻（北京时间）',name:'at',type:'datetime-local',value:now,required:true},
    {label:'当前电量 SOC（%）',name:'current_soc',type:'number',value:20,min:0,max:99,step:.1,required:true},
    {label:'目标电量 SOC（%）',name:'target_soc',type:'number',value:80,min:1,max:100,step:.1,required:true},
    {label:'计费身份',name:'card',type:'select',options:[{value:'',label:'个人充电'},...cards.map(x=>({value:x.id,label:`企业卡 #${x.id} · 车辆${x.vehicle_id}`}))]},
  ],async v=>{
    const data=await api('/estimate',{method:'POST',body:{...v,vehicle:Number(v.vehicle),gun:g.id,at:v.at+':00+08:00',current_soc:Number(v.current_soc),target_soc:Number(v.target_soc),...(v.card?{card:Number(v.card)}:{card:null})}});
    result.replaceChildren(node('div',{className:'stats-grid'},stat('预计补电',`${Number(data.kwh).toFixed(2)} kWh`),stat('预计时长',`${Math.ceil(Number(data.minutes))} 分钟`),stat('预计费用',`¥ ${money(data.amount)}`)));
  },'计算费用'),result));
}

export async function renderQueue({root,user}) {
  const [queue,lookups,cards]=await Promise.all([api('/queue'),api('/ui/api/lookups'),api('/ui/api/fleet-cards')]);
  const names=new Map(lookups.stations.map(x=>[x.id,x.name]));
  root.append(notice('叫号后请在服务端规定的截止时间前使用指定充电枪。取消后留枪由调度释放；可点击“刷新数据”查看最新结果。'));
  root.append(panel('我的到站排队',dataTable([
    {label:'排队号',render:r=>`#${r.id}`},{label:'场站',render:r=>names.get(r.station_id) || `场站${r.station_id}`},{key:'vehicle_id',label:'车辆编号'},
    {label:'状态',render:r=>badge(r.state)},{label:'取号时间',render:r=>dateTime(r.queued_at)},
    {label:'叫号枪 / 截止时间',render:r=>r.connector_id?node('div',{},`枪 #${r.connector_id}`,node('small',{className:'muted'},dateTime(r.deadline))):'等待叫号'},
    {label:'操作',render:r=>node('div',{className:'actions'},r.state==='called'?button('使用预留枪',()=>openCharging(r.connector_id,lookups.vehicles.filter(v=>v.id===r.vehicle_id),cards),'primary small'):null,['waiting','called'].includes(r.state)?button('取消排队',async()=>{await api(`/queue/${r.id}`,{method:'DELETE'});toast('排队已取消');refresh();},'secondary small'):null)},
  ],queue)),button('继续查找场站',()=>navigate('stations'),'secondary'));
}

const names={operator:'运营商',station:'充电场站',charger:'充电桩',connector:'充电枪'};
function assetFields(type,lookups,row={}) {
  if(type==='operator') return [{label:'运营商名称',name:'name',value:row.name || '',required:true}];
  if(type==='station') return [
    {label:'场站名称',name:'name',value:row.name || '',required:true},idSelect('所属运营商','operator_id',opts(lookups.operators,x=>x.name),row.operator_id),
    {label:'详细地址',name:'address',value:row.address || '',required:true},{label:'停车位数',name:'spaces',type:'number',min:0,step:1,value:row.spaces ?? 20,required:true},
    {label:'开始营业',name:'opens',type:'time',value:row.opens || '00:00',required:true},{label:'结束营业',name:'closes',type:'time',value:row.closes || '00:00',required:true},
    {label:'经度',name:'longitude',type:'number',step:.000001,value:row.longitude ?? ''},{label:'纬度',name:'latitude',type:'number',step:.000001,value:row.latitude ?? ''},
    {label:'停车说明',name:'parking_note',type:'textarea',value:row.parking_note || ''},{label:'场站启用',name:'enabled',type:'checkbox',value:row.enabled ?? true},
  ];
  if(type==='charger') return [idSelect('所属场站','station_id',opts(lookups.stations,x=>x.name),row.station_id),{label:'设备型号',name:'model',value:row.model || '',required:true},
    {label:'额定功率（kW）',name:'rated_kw',type:'number',step:.01,min:.01,value:row.rated_kw || 120,required:true},
    {label:'通信协议',name:'protocol',value:row.protocol || 'OCPP',required:true},{label:'质保截止日期',name:'warranty_until',type:'date',value:row.warranty_until || ''}];
  return [idSelect('所属充电桩','charger_id',opts(lookups.chargers,x=>`#${x.id} · ${x.model} · 场站${x.station_id}`),row.charger_id),
    {label:'枪位号',name:'gun_position',type:'number',value:row.gun_position || 1,min:1,step:1,required:true},
    {label:'枪型',name:'kind',type:'select',value:row.kind || 'DC',options:[{value:'DC',label:'直流 DC'},{value:'AC',label:'交流 AC'}],required:true},
    {label:'接口标准',name:'interface',value:row.interface || 'GB/T',required:true},
    {label:'最大功率（kW）',name:'max_kw',type:'number',value:row.max_kw || 60,min:.01,step:.01,required:true}];
}
function assetEditor(type,lookups,row) {
  let close;
  close=modal(`${row?'编辑':'新增'}${names[type]}${row?' #'+row.id:''}`,form(assetFields(type,lookups,row),async values=>{
    const numberFields=['operator_id','spaces','longitude','latitude','station_id','rated_kw','charger_id','gun_position','max_kw'];
    Object.keys(values).forEach(k=>{if(values[k]==='' && ['warranty_until','longitude','latitude'].includes(k)){values[k]=null;}else if(numberFields.includes(k))values[k]=Number(values[k]);});
    const result=await api(`/admin/assets/${type}${row?'/'+row.id:''}`,{method:row?'PATCH':'POST',body:values});
    close();toast(row?'档案已更新':`${names[type]} #${result.id} 已登记`);refresh();
  },row?'保存变更':'登记档案',{description:type==='charger'?'登记后还需要创建验收申请并通过核验才能投运。':type==='station'?'开始与结束时间相同表示全天营业。':''}));
}

export async function renderFacilities({root,params}) {
  const type=names[params.get('table')]?params.get('table'):'station',offset=Math.max(0,Number(params.get('offset')) || 0);
  const [rows,lookups,requests]=await Promise.all([api(`/admin/assets/${type}?offset=${offset}`),api('/ui/api/lookups'),api('/ui/api/asset-requests')]);
  root.append(node('div',{className:'tabbar'},Object.entries(names).map(([key,label])=>button(label,()=>navigate('facilities',{table:key}),`secondary ${key===type?'active':''}`))));
  const cols=[{key:'id',label:'编号',render:r=>`#${r.id}`}];
  if(type==='operator')cols.push({key:'name',label:'运营商名称'});
  if(type==='station')cols.push({key:'name',label:'场站名称'},{key:'operator_id',label:'运营商'},{key:'address',label:'地址'},{key:'spaces',label:'停车位'},{label:'状态',render:r=>badge(r.enabled?'enabled':'disabled')});
  if(type==='charger')cols.push({key:'model',label:'设备型号'},{key:'station_id',label:'场站'},{label:'额定功率',render:r=>`${r.rated_kw} kW`},{label:'投运日期',render:r=>r.commissioned_on || '待验收'},{label:'状态',render:r=>badge(r.state)});
  if(type==='connector')cols.push({key:'charger_id',label:'所属桩'},{key:'gun_position',label:'枪位'},{key:'kind',label:'枪型'},{key:'interface',label:'接口'},{label:'最大功率',render:r=>`${r.max_kw} kW`},{label:'状态',render:r=>badge(r.state)});
  cols.push({label:'操作',render:r=>node('div',{className:'actions'},button('编辑',()=>assetEditor(type,lookups,r),'secondary small'),type==='station'?button('设备与历史',()=>assetHistory(r),'ghost small'):null,button('删除',async()=>{
    if(!window.confirm(`确认删除${names[type]} #${r.id}？有业务引用的档案会被数据库拒绝删除。`))return;
    await api(`/admin/assets/${type}/${r.id}`,{method:'DELETE'});toast('未引用档案已删除');refresh();
  },'ghost small'))});
  root.append(panel(node('div',{className:'toolbar'},node('h2',{},`${names[type]}档案`),button(`＋ 新增${names[type]}`,()=>assetEditor(type,lookups),'primary')),dataTable(cols,rows),node('div',{className:'pager'},button('上一页',()=>navigate('facilities',{table:type,offset:Math.max(0,offset-30)}),'secondary small'),`第 ${Math.floor(offset/30)+1} 页 · ${rows.length} 条`,button('下一页',()=>{if(rows.length===30)navigate('facilities',{table:type,offset:offset+30});else toast('已经是最后一页');},'secondary small'))));
  root.append(panel('设备投运验收',notice('流程：登记充电桩 → 创建验收申请 → 核验投运。验收通过不代表设备在线，还需有效心跳。'),form([
    idSelect('待验收充电桩','charger_id',opts(lookups.chargers.filter(c=>!c.commissioned_on),c=>`#${c.id} · ${c.model} · 场站${c.station_id}`)),
  ],async v=>{const result=await api('/ui/api/asset-requests',{method:'POST',body:{charger_id:Number(v.charger_id),kind:'acceptance',payload:{}}});toast(`验收申请 #${result.id} 已创建`);refresh();},'创建验收申请'),dataTable([
    {label:'申请号',render:r=>`#${r.id}`},{key:'charger_id',label:'设备编号'},{key:'model',label:'型号'},{label:'申请类型',render:r=>badge(r.kind)},
    {label:'状态',render:r=>badge(r.state)},{label:'申请时间',render:r=>dateTime(r.created_at)},
    {label:'操作',render:r=>r.kind==='acceptance'&&r.state==='pending'?button('核验并投运',async()=>{if(!window.confirm(`确认设备 #${r.charger_id} 已完成验收？`))return;await api(`/admin/chargers/${r.charger_id}/commission`,{method:'POST',body:{request:r.id}});toast('验收通过，已记录投运日期');refresh();},'primary small'):'—'},
  ],requests)));
}

async function assetHistory(station) {
  const data=await api(`/admin/stations/${station.id}/assets`);
  modal(`${station.name} · 设备与状态历史`,node('div',{},dataTable([{key:'id',label:'桩号'},{key:'model',label:'型号'},{key:'rated_kw',label:'功率'},{label:'状态',render:r=>badge(r.state)}],data.chargers),node('h3',{},'最近状态变化'),dataTable([{key:'id',label:'记录号'},{key:'charger_id',label:'桩'},{key:'connector_id',label:'枪'},{label:'原状态',render:r=>badge(r.old_state)},{label:'新状态',render:r=>badge(r.new_state)},{label:'发生时间',render:r=>dateTime(r.happened_at)}],data.history)));
}

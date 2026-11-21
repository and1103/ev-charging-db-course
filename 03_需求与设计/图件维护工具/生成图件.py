"""Read MySQL DDL only; prepare PNG diagram render jobs and a schema inventory.

Does not import the app, connect to a database, or execute SQL. Render with render.mjs.
"""
from pathlib import Path
import hashlib
import html
import json
import re
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / '01_平台工程'))
from project_paths import SQL_ROOT, DESIGN_ROOT
ROOT = SQL_ROOT
OUT = Path(__file__).resolve().parent
PROCESS = DESIGN_ROOT
IMAGES = DESIGN_ROOT / '业务分线与图件'
FONT = "Microsoft YaHei"
MODULES = {
    "A": ("A_场站设施与排队/场站与充电设施", "场站与充电设施", "#dcebf8"),
    "Q": ("A_场站设施与排队/充电估算与到站排队", "充电估算与到站排队", "#e1f3f0"),
    "B": ("B_充电订单与计费/充电订单与计费", "充电订单与计费", "#e6e3f5"),
    "C": ("C_设备监控与故障工单/设备监控与故障工单", "设备监控与故障工单", "#ffefd7"),
    "D": ("D_用户与会员运营/用户与会员运营", "用户与会员运营", "#e7f1dd"),
    "E": ("E_结算与对账/结算与对账", "结算与对账", "#f8e1e8"),
}
NAMES = {
    "operator":"运营商", "station":"场站", "charger":"充电桩", "connector":"充电枪",
    "asset_history":"设备状态历史", "asset_request":"设备验收与变更申请",
    "queue_entry":"排队记录", "queue_call":"叫号记录", "gun_hold":"充电枪保留",
    "tariff":"计费规则版本", "tariff_band":"峰平谷费率时段", "charge_order":"充电订单",
    "meter_sample":"枪级电表读数", "fee_detail":"分段费用明细", "order_review":"异常订单复核",
    "payment":"支付记录", "refund":"退款记录", "telemetry":"运行遥测", "alarm_rule":"告警规则",
    "alarm":"告警", "work_order":"维修工单", "work_part":"工单备件", "alarm_notice":"告警通知",
    "account":"登录账户及会员", "vehicle":"车辆", "vehicle_binding":"车辆归属历史",
    "fleet":"企业车队", "fleet_card":"车队卡及额度", "campaign":"优惠活动", "coupon":"已发优惠券",
    "wallet_entry":"账户余额流水", "redemption":"优惠券核销", "consumer_invoice_request":"用户开票申请",
    "driver_feedback":"用户报障及评价", "settlement":"运营商结算单", "settlement_item":"结算订单快照",
    "external_bill":"运营商账单明细", "recon_diff":"对账差异", "diff_confirmation":"差异双方确认",
    "settlement_adjustment":"结算调整", "settlement_invoice":"结算发票及红冲",
    "settlement_payment":"结算付款", "settlement_payment_record":"结算付款记录",
    "price_request":"企业专属价申请", "fleet_price_request":"企业专属价申请",
    "revenue_agreement":"分成协议版本", "sharing_agreement":"分成协议版本",
    "campaign_station":"活动适用场站", "account_role":"账户角色", "role_permission":"角色权限",
    "audit_log":"操作审计", "schema_migration":"数据库迁移记录",
    "settlement_import":"对账导入批次", "settlement_confirmation":"结算双方确认",
    "consumer_invoice":"用户发票及红冲",
}
FIELDS = {
    "id":"编号", "name":"名称", "address":"地址", "state":"状态", "kind":"类别", "spaces":"车位总数",
    "operator_id":"运营商编号", "station_id":"场站编号", "charger_id":"桩编号", "connector_id":"枪编号",
    "account_id":"账户编号", "vehicle_id":"车辆编号", "order_id":"订单编号", "payment_id":"支付编号",
    "refund_id":"退款编号", "tariff_id":"规则版本编号", "alarm_id":"告警编号", "work_id":"工单编号",
    "settlement_id":"结算编号", "diff_id":"差异编号", "campaign_id":"活动编号", "coupon_id":"券编号",
    "fleet_id":"车队编号", "fleet_card_id":"车队卡编号", "manager_id":"管理员编号", "driver_id":"用车人编号",
    "technician_id":"维修人员编号", "reviewed_by":"复核人员编号", "actor":"确认人编号", "original_id":"原发票编号",
    "call_id":"叫号编号", "entry_id":"排队编号", "period":"账期", "code":"告警码", "part":"备件名称",
    "side":"确认方", "sampled_at":"采样时刻", "begins":"分段开始", "ends":"结束/失效时间",
    "starts":"生效时间", "started_at":"开始充电", "ended_at":"结束充电", "happened_at":"发生时间",
    "registered_at":"注册时间", "queued_at":"取号时间", "called_at":"叫号时间", "deadline":"响应/保留期限",
    "reading":"累计电量", "kwh":"充电电量", "gross":"优惠前金额", "discount":"优惠金额", "amount":"金额",
    "energy_rate":"电价", "service_rate":"服务费单价", "service_mode":"服务费模式", "label":"峰平谷类型",
    "minute_from":"时段起始分钟", "minute_to":"时段结束分钟", "free_minutes":"免费分钟数", "minimum":"起步金额/门槛",
    "rated_kw":"桩额定功率", "max_kw":"最大充电功率", "gun_position":"枪序号", "interface":"接口标准",
    "model":"型号", "protocol":"通信协议", "heartbeat":"末次心跳", "warranty_until":"质保截止",
    "old_state":"变更前状态", "new_state":"变更后状态", "payload":"申请变更内容", "created_at":"创建时间",
    "reason":"复核原因", "conclusion":"处理结论", "last_reading":"最后可信读数", "succeeded":"支付成功标志",
    "reference":"交易业务流水号", "channel":"注册/支付渠道", "temperature":"模块温度", "kw":"运行功率",
    "severity":"告警级别", "response_minutes":"响应分钟数", "opened_at":"告警发生时间", "restored_at":"恢复时间",
    "assigned_at":"派单时间", "accepted_at":"接单时间", "arrived_at":"到场时间", "repaired_at":"修复时间",
    "closed_at":"关闭时间", "result":"处理结果", "quantity":"备件数量", "login":"登录名", "role":"角色",
    "balance":"账户余额", "tier":"会员等级", "verified":"实名状态", "phone_mask":"脱敏手机号",
    "plate_mask":"脱敏车牌", "capacity_kwh":"电池容量", "since":"归属生效时间", "binding_end":"归属结束时间",
    "credit_limit":"车队额度", "enabled":"启用状态", "face":"券面额", "expires":"有效期截止", "stock":"发放上限",
    "change":"余额变动金额", "title":"发票抬头", "content":"反馈内容", "delta":"差异金额", "net_received":"净收款快照",
    "energy_share":"电费分成", "service_share":"服务费分成", "platform_fee":"平台服务费", "tax_id":"税号",
    "batch":"导入批次号", "expected_rows":"预期导入行数", "confirmed_at":"确认时间", "completed_at":"完成时间",
    "request_id":"开票申请编号", "issued_by":"开票经办人编号", "issued_at":"开票时间",
    "energy":"电费金额", "service":"服务费金额", "notified_at":"通知时刻", "paid":"已支付标志",
    "estimated":"估算标志", "adjustment":"复核差额", "fault_code":"故障码", "offline_seconds":"离线秒数",
    "source_period":"订单归属账期", "customer_reduction":"客户应付冲减额", "reserved_amount":"车队冻结金额",
    "used_at":"核销时间", "requested_at":"申请时间", "topup_ref":"充值请求号", "scope_connector":"告警去重枪范围",
}
PREFERRED = {
    "operator":["name"], "station":["name","address","spaces"], "charger":["model","rated_kw","state"],
    "connector":["gun_position","kind","max_kw"], "asset_history":["old_state","new_state","happened_at"],
    "asset_request":["kind","state","created_at"], "queue_entry":["state","queued_at"],
    "queue_call":["called_at","deadline"], "gun_hold":["state"], "tariff":["starts","ends","service_mode"],
    "tariff_band":["label","energy_rate","service_rate"], "charge_order":["started_at","state","kwh","gross"],
    "meter_sample":["reading"], "fee_detail":["ends","kwh","energy","service"],
    "order_review":["reason","conclusion","last_reading"], "payment":["amount","channel","reference"],
    "refund":["amount","reference"], "telemetry":["kw","temperature","fault_code"],
    "alarm_rule":["severity","response_minutes"], "alarm":["severity","opened_at","deadline"],
    "work_order":["accepted_at","repaired_at","closed_at"], "work_part":["quantity"],
    "alarm_notice":["created_at"], "account":["login","tier","balance"],
    "vehicle":["plate_mask","capacity_kwh","max_kw"], "vehicle_binding":["since","binding_end"],
    "fleet":["name"], "fleet_card":["credit_limit","enabled"], "campaign":["name","face","expires"],
    "coupon":["issued_at"], "wallet_entry":["change","topup_ref","happened_at"], "redemption":["discount","used_at"],
    "consumer_invoice_request":["title","state"], "driver_feedback":["kind","content"],
    "settlement":["period","state"], "settlement_item":["kwh","net_received"],
    "external_bill":["kwh","amount","paid"], "recon_diff":["kind","delta","conclusion"],
    "diff_confirmation":["confirmed_at"], "settlement_adjustment":["amount","reason"],
    "settlement_invoice":["title","amount","issued_at"],
    "consumer_invoice":["title","amount","issued_at"], "settlement_import":["batch","state","expected_rows"],
    "settlement_confirmation":["confirmed_at"],
}


def split_top(text):
    out, start, depth, quote = [], 0, 0, None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote and (i == 0 or text[i-1] != "\\"): quote = None
        elif ch in "'\"`": quote = ch
        elif ch == "(": depth += 1
        elif ch == ")": depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip()); start = i+1
    out.append(text[start:].strip())
    return out


def identifiers(s): return [x.strip().strip("`").split()[0] for x in split_top(s)]
def j(s): return json.dumps(s.replace("\\n", "\n") if isinstance(s,str) else s, ensure_ascii=False)
def esc(s): return html.escape(str(s), quote=True)
def label(name): return NAMES.get(name, name.replace("_", " "))
def field_label(table,column):
    return {('coupon','issued_at'):'领券时间',('campaign','minimum'):'使用门槛',('payment','channel'):'支付渠道',('account','channel'):'注册渠道',('tariff','ends'):'规则失效时间',('fee_detail','ends'):'分段结束时间',('queue_call','deadline'):'保留截止时间',('alarm','deadline'):'响应截止时间'}.get((table,column),FIELDS.get(column,column))


def text_width(s,size):
    return sum((1.06 if ord(c)>255 else 0.59) * size for c in s)


def geometry(s,shape="box",size=18,icon=False):
    rows=s.replace("\\n","\n").splitlines() or [""]
    width=max(text_width(r,size) for r in rows)+30
    height=len(rows)*size*1.5+18
    if shape=="ellipse": width=width*1.48; height=height*1.45
    if shape=="diamond": width=width*1.8; height=height*1.8
    if icon: height=100
    return f'width={max(width/72,0.8):.3f},height={max(height/72,0.5):.3f},fixedsize=true'


RELATIONS={
    ("station","operator_id"):"运营", ("charger","station_id"):"部署", ("connector","charger_id"):"配置",
    ("asset_history","charger_id"):"记录桩状态", ("asset_history","connector_id"):"记录枪状态", ("asset_request","charger_id"):"申请验收/变更",
    ("queue_entry","station_id"):"在站排队", ("queue_entry","vehicle_id"):"车辆取号", ("queue_entry","account_id"):"提交排队",
    ("queue_call","entry_id"):"产生叫号", ("queue_call","connector_id"):"分配枪", ("gun_hold","order_id"):"转为订单", ("gun_hold","call_id,connector_id"):"建立留枪",
    ("account","operator_id"):"运营商身份", ("account","station_id"):"授权运维范围",
    ("vehicle_binding","vehicle_id"):"归属历史", ("vehicle_binding","account_id"):"持有车辆",
    ("fleet","manager_id"):"管理车队", ("fleet_card","fleet_id"):"发行车队卡", ("fleet_card","vehicle_id"):"绑定车辆", ("fleet_card","driver_id"):"授权用车",
    ("tariff","station_id"):"适用计费", ("tariff","fleet_id"):"企业专属价", ("tariff_band","tariff_id"):"划分时段",
    ("charge_order","account_id"):"发起充电", ("charge_order","connector_id"):"服务订单", ("charge_order","vehicle_id"):"车辆充电", ("charge_order","tariff_id"):"按版本核价", ("charge_order","fleet_card_id"):"车队卡消费",
    ("meter_sample","order_id"):"采集电量", ("fee_detail","order_id"):"拆分费用", ("order_review","order_id"):"异常复核", ("order_review","reviewed_by"):"审核账单",
    ("payment","order_id"):"分次收款", ("refund","payment_id"):"退回支付", ("telemetry","charger_id"):"运行采样",
    ("alarm","charger_id"):"设备告警", ("alarm","connector_id"):"指定枪源告警", ("alarm","code"):"依据告警规则", ("work_order","alarm_id"):"多次派单", ("work_order","technician_id"):"负责维修",
    ("work_part","work_id"):"耗用备件", ("alarm_notice","alarm_id"):"发送通知",
    ("campaign","station_id"):"活动适用", ("coupon","campaign_id"):"发放优惠券", ("coupon","account_id"):"领取券",
    ("wallet_entry","account_id"):"记录余额变动", ("wallet_entry","payment_id"):"支付记账", ("wallet_entry","refund_id"):"退款记账",
    ("redemption","coupon_id"):"核销优惠券", ("redemption","order_id"):"订单用券", ("consumer_invoice_request","order_id"):"申请用户发票", ("driver_feedback","order_id"):"报障/评价",
    ("settlement","station_id"):"按站点汇总", ("settlement","operator_id"):"运营商结算", ("settlement_item","settlement_id"):"包含结算明细", ("settlement_item","order_id"):"订单入账",
    ("external_bill","settlement_id"):"外部对照账单", ("external_bill","order_id"):"运营商记账", ("recon_diff","settlement_id"):"包含对账差异", ("recon_diff","order_id"):"差异来源",
    ("diff_confirmation","diff_id"):"双方确认", ("diff_confirmation","actor"):"经办人签认", ("settlement_adjustment","settlement_id"):"调整应结金额", ("settlement_adjustment","order_id"):"调整来源订单", ("settlement_adjustment","diff_id"):"差异形成调整", ("settlement_adjustment","refund_id"):"退款跨期调整",
    ("settlement_invoice","settlement_id"):"开具结算发票", ("settlement_invoice","original_id"):"红冲原票",
    ("consumer_invoice","request_id"):"落实用户开票", ("consumer_invoice","order_id"):"订单开票", ("consumer_invoice","original_id"):"红冲用户原票", ("consumer_invoice","issued_by"):"经办开票",
    ("settlement_import","settlement_id"):"导入账单批次", ("external_bill","settlement_id,batch"):"包含外部明细",
    ("settlement_confirmation","settlement_id"):"双方确认结算", ("settlement_confirmation","actor"):"经办结算签认",
}


def read_schema():
    tables, foreign, hashes = {}, [], {}
    for path in sorted(ROOT.rglob("*.sql")):
        if path.name in {"seed.sql", "smoke.sql", "queries.sql", "09_roles.sql"}: continue
        original = path.read_text(encoding="utf-8-sig")
        hashes[path.relative_to(PROJECT).as_posix()] = hashlib.sha256(original.encode()).hexdigest()
        # Preserve line numbers while ignoring SQL comments in column fragments.
        text = re.sub(r'/\*[\s\S]*?\*/|--[^\n]*',lambda m:'\n'*m.group().count('\n'),original)
        owner = "Q" if path.name == '04_queue.sql' else path.relative_to(ROOT).parts[0].split('_', 1)[0]
        if owner not in MODULES: continue
        for match in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\(", text, re.I):
            name = match.group(1); start = match.end(); depth=1; quote=None; end=start
            while end < len(text) and depth:
                ch=text[end]
                if quote:
                    if ch==quote and text[end-1] != "\\": quote=None
                elif ch in "'\"`": quote=ch
                elif ch=="(": depth+=1
                elif ch==")": depth-=1
                end+=1
            body=text[start:end-1]
            cols=[]; pk=[]; unique=[]
            for fragment in split_top(body):
                pm=re.match(r"PRIMARY\s+KEY\s*\((.*?)\)",fragment,re.I)
                um=re.match(r"(?:CONSTRAINT\s+\w+\s+)?UNIQUE(?:\s+(?:KEY|INDEX))?(?:\s+\w+)?\s*\((.*?)\)",fragment,re.I)
                if pm: pk=identifiers(pm.group(1)); continue
                if um: unique.append(identifiers(um.group(1))); continue
                cm=re.match(r"`?(\w+)`?\s+([A-Za-z]+(?:\([^)]*\))?)",fragment)
                if not cm or cm.group(1).upper() in {"FOREIGN","CHECK","CONSTRAINT","INDEX","KEY"}: continue
                cn,typ=cm.groups()
                cols.append({"name":cn,"type":typ,"required":bool(re.search(r"\bNOT\s+NULL\b|\bPRIMARY\s+KEY\b",fragment,re.I))})
                if re.search(r"\bPRIMARY\s+KEY\b",fragment,re.I): pk.append(cn)
                if re.search(r"\bUNIQUE\b",fragment,re.I): unique.append([cn])
            for fm in re.finditer(r"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+`?(\w+)`?\s*\(([^)]+)\)",body,re.I):
                foreign.append({"child":name,"columns":identifiers(fm.group(1)),"parent":fm.group(2),"references":identifiers(fm.group(3)),"kind":"physical"})
            tables[name]={"name":name,"owner":owner,"columns":cols,"pk":pk,"unique":unique,"source":path.relative_to(PROJECT).as_posix(),"line":text.count("\n",0,match.start())+1}
        for am in re.finditer(r"ALTER\s+TABLE\s+`?(\w+)`?\s+([^;]+);",text,re.I):
            t=tables.get(am.group(1))
            if not t: continue
            for action in split_top(am.group(2)):
                cm=re.match(r"ADD\s+(?:COLUMN\s+)?`?(\w+)`?\s+([A-Za-z]+(?:\([^)]*\))?)",action,re.I)
                if cm and cm.group(1).upper() not in {"UNIQUE","KEY","INDEX","CONSTRAINT","FOREIGN","PRIMARY","CHECK"}:
                    cn,typ=cm.groups()
                    if not any(c['name']==cn for c in t['columns']):
                        t['columns'].append({"name":cn,"type":typ,"required":bool(re.search(r'\bNOT\s+NULL\b',action,re.I)),"generated":bool(re.search(r'\bGENERATED\b',action,re.I))})
                    if re.search(r'\bUNIQUE\b',action,re.I): t['unique'].append([cn])
                um=re.match(r"ADD\s+UNIQUE(?:\s+(?:KEY|INDEX))?(?:\s+\w+)?\s*\(([^)]+)\)",action,re.I)
                if um: t['unique'].append(identifiers(um.group(1)))
    # MySQL partitioned telemetry intentionally uses trigger-enforced logical ownership.
    if "telemetry" in tables and not any(f["child"]=="telemetry" for f in foreign):
        foreign.append({"child":"telemetry","columns":["charger_id"],"parent":"charger","references":["id"],"kind":"logical"})
    # Reconciliation keeps unmatched external order numbers deliberately; draw a
    # nullable logical association instead of pretending an absent physical FK exists.
    for child in ["external_bill","recon_diff","settlement_adjustment"]:
        if child in tables and any(c['name']=='order_id' for c in tables[child]['columns']) and not any(f['child']==child and f['columns']==['order_id'] for f in foreign):
            foreign.append({"child":child,"columns":["order_id"],"parent":"charge_order","references":["id"],"kind":"logical","optional_override":True})
    for f in foreign:
        if f["parent"] not in tables: raise ValueError(f"Missing referenced entity: {f}")
        child=tables[f["child"]]
        unique=[child["pk"]]+child["unique"]
        f["many"] = not any(set(u) <= set(f["columns"]) and u for u in unique)
        f["optional"] = f.get("optional_override",not all(next(c["required"] for c in child["columns"] if c["name"]==x) or x in child["pk"] for x in f["columns"]))
    return tables, foreign, hashes


def header(title, rank="LR", size=18):
    return ["digraph G {", f'graph [fontname={j(FONT)},fontsize={size+3},label={j(title)},labelloc=t,pad="0.45",nodesep="0.44",ranksep="1.0",rankdir={rank},splines=polyline,bgcolor="white",outputorder=edgesfirst];',
            f'node [fontname={j(FONT)},fontsize={size},color="#253343",penwidth=1.5,margin="0.15,0.10"];',
            f'edge [fontname={j(FONT)},fontsize={size-3},color="#526171",penwidth=1.2,arrowsize=0.7];']


def scope(tables, foreign, owner):
    own={n for n,t in tables.items() if t["owner"]==owner}
    fks=[f for f in foreign if f["child"] in own]
    names=own | {f["parent"] for f in fks}
    return own,names,fks


def attributes(t):
    fkcols={c for f in FOREIGN if f["child"]==t["name"] for c in f["columns"]}
    choices=[x for x in PREFERRED.get(t["name"],[]) if x not in fkcols and x not in t['pk'] and any(c["name"]==x for c in t["columns"])]
    for c in t["columns"]:
        if len(choices)>=3: break
        if not c.get('generated') and c["name"] not in choices and c["name"] not in t["pk"] and c["name"] not in fkcols and not any(x in c["name"] for x in ["cipher","password","secret","token"]): choices.append(c["name"])
    return [x for x in choices if x not in t["pk"]][:4]


def chen(owner=None,selection=None,report_title=None,report_attributes=None):
    report=selection is not None
    if report:
        own=names=set(selection)
        fks=[f for f in FOREIGN if f['child'] in own and f['parent'] in own]
    else:
        own,names,fks=(set(TABLES),set(TABLES),FOREIGN) if owner is None else scope(TABLES,FOREIGN,owner)
    title=report_title or ("全局 Chen E-R 图｜全实体及全部引用关系（分区细节见各线图）" if owner is None else MODULES[owner][1]+"｜Chen 局部 E-R 图")
    lines=header(title,"TB",20 if report else (16 if owner is None else 18))
    lines.append('edge [dir=none];')
    for n in sorted(names):
        t=TABLES[n]; external=n not in own
        fill="#f3f4f5" if external else MODULES[t["owner"]][2]
        name=label(n)+("\\n【外部引用】" if external else "")+"\\n"+n
        if report:
            node_width=(max(text_width(label(n),20),text_width(n,12))+30)/72
            lines.append(f'{j(n)} [shape=box,width={node_width:.3f},height=0.85,fixedsize=true,style=filled,fillcolor={j(fill)},label=<<B>{esc(label(n))}</B><BR/><FONT POINT-SIZE="12">{esc(n)}</FONT>>];')
        else:
            lines.append(f'{j(n)} [shape=box,{geometry(name)},style={j("filled,dashed" if external else "filled")},fillcolor={j(fill)},label={j(name)}];')
        if not external:
            if t["pk"]:
                key="＋".join((label(n)+"编号") if c=='id' else field_label(n,c) for c in t["pk"])
                lines.append(f'{j(n+"__pk")} [shape=ellipse,{geometry(key,"ellipse")},label=<<U>{esc(key)}</U>>];')
                lines.append(f'{j(n)} -> {j(n+"__pk")} [color="#77818b",weight=5];')
            chosen=(report_attributes or {}).get(n,attributes(t)[:2]) if report else attributes(t)[:(1 if owner is None else 3)]
            for c in chosen:
                if c in t['pk'] or not any(x['name']==c for x in t['columns']): continue
                lines.append(f'{j(n+"__"+c)} [shape=ellipse,{geometry(field_label(n,c),"ellipse")},label={j(field_label(n,c))}];')
                lines.append(f'{j(n)} -> {j(n+"__"+c)} [color="#77818b",weight=4];')
    for i,f in enumerate(fks):
        name="rel_"+str(i)
        words=RELATIONS.get((f["child"],",".join(f["columns"])),"关联"+label(f["parent"]))
        lines.append(f'{name} [shape=diamond,{geometry(words,"diamond",15)},label={j(words)},fontsize=15];')
        style=',style=dashed' if f["kind"]=="logical" else ''
        lines.append(f'{j(f["parent"])} -> {name} [label={j("0..1" if f["optional"] else "1")},minlen=1{style}];')
        lines.append(f'{name} -> {j(f["child"])} [label={j("N" if f["many"] else "0..1")},minlen=1{style}];')
    legend="矩形：实体；菱形：联系；椭圆：业务属性\n下划线：主标识；N：0..N；0..1：可选\n灰色虚框：跨线实体；虚线：逻辑关联\n外键由联系表达；完整字段见 UML 分区图"
    if not report: lines.append(f'legend [shape=note,{geometry(legend,size=13)},fontsize=13,label={j(legend)}];')
    return "\n".join(lines+["}"])


def uml(owner=None):
    own,names,fks=(set(TABLES),set(TABLES),FOREIGN) if owner is None else scope(TABLES,FOREIGN,owner)
    title="全局 UML 类图｜全部实体与关系" if owner is None else MODULES[owner][1]+"｜全局 UML 分区详图（完整字段）"
    lines=header(title,"LR",13 if owner is None else 15)
    for n in sorted(names):
        t=TABLES[n]; external=n not in own
        chosen=(t["pk"]+attributes(t)[:2]) if owner is None else [c["name"] for c in t["columns"]]
        if external: chosen=t["pk"]
        rows=[]
        fcols={c for f in FOREIGN if f["child"]==n and f["kind"]=='physical' for c in f["columns"]}
        lcols={c for f in FOREIGN if f["child"]==n and f["kind"]=='logical' for c in f["columns"]}
        for c in t["columns"]:
            if c["name"] not in chosen: continue
            marks=("PK " if c["name"] in t["pk"] else "")+("FK " if c["name"] in fcols else "")+("关联 " if c["name"] in lcols and c["name"] not in fcols else "")+("派生 " if c.get('generated') else "")
            rows.append(f'<TR><TD ALIGN="LEFT">{esc(marks+c["name"]+" : "+c["type"]+(" [1]" if c["required"] or c["name"] in t["pk"] else " [0..1]"))}</TD></TR>')
        fill="#f3f4f5" if external else MODULES[t["owner"]][2]
        cellwidth=max(240,max((text_width(re.sub('<[^>]+>','',x),15) for x in rows),default=0)+25,text_width(label(n),15)+30)
        box=f'<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="7"><TR><TD WIDTH="{int(cellwidth)}" BGCOLOR="{fill}"><B>{esc(label(n))}</B><BR/>{esc(n)}'+(" 【外部引用】" if external else "")+'</TD></TR><HR/>'+"".join(rows)+'</TABLE>'
        lines.append(f'{j(n)} [shape=plain,label=<{box}>];')
    for f in fks:
        role=",".join(f["columns"])
        style=',style=dashed' if f["kind"]=="logical" else ''
        lines.append(f'{j(f["child"])} -> {j(f["parent"])} [arrowhead=none,taillabel={j("0..*" if f["many"] else "0..1")},headlabel={j("0..1" if f["optional"] else "1")},label={j(role)},labeldistance=1.7{style}];')
    return "\n".join(lines+["}"])


def report_chen(owner,selection,title,chosen_attributes,layout):
    """Pin compact entity/attribute constellations; neato routes their links.

    Each report panel is deliberately a projection of the complete model.
    Coordinates are authoring information, not a second hand-written schema.
    """
    lines=header(title+'｜报告子图','TB',20)
    lines.append('graph [overlap=true,splines=polyline,sep="+12"]; edge [dir=none,fontsize=16];')
    occupied=[]
    def add(name,text,x,y,shape='box',key=False,color='white',font=20):
        if shape=='box':
            w=max(text_width(label(name),20),text_width(name,12))+28;h=60
            content=f'<<B>{esc(label(name))}</B><BR/><FONT POINT-SIZE="12">{esc(name)}</FONT>>'
        else:
            w=text_width(text,font)+26;h=42
            if shape=='ellipse':w*=1.35;h=56
            if shape=='diamond':w*=1.75;h=80
            content=f'<<U>{esc(text)}</U>>' if key else j(text)
        occupied.append((x-w/2,y-h/2,x+w/2,y+h/2))
        lines.append(f'{j(name)} [shape={shape},pos="{x/72:.4f},{-y/72:.4f}!",pin=true,width={w/72:.4f},height={h/72:.4f},fixedsize=true,fontsize={font},style=filled,fillcolor={j(color)},label={content}];')
    short={'operator':'运营商编号','station':'场站编号','charger':'桩编号','connector':'枪编号','tariff':'规则编号','charge_order':'订单编号','payment':'支付编号','refund':'退款编号','account':'用户编号','vehicle':'车辆编号','fleet':'车队编号','fleet_card':'车队卡编号','campaign':'活动编号','coupon':'券编号','consumer_invoice_request':'申请编号','consumer_invoice':'用户发票编号','settlement':'结算编号','recon_diff':'差异编号','settlement_adjustment':'调整编号','settlement_invoice':'结算发票编号'}
    for n in selection:
        t=TABLES[n];gx,gy=layout[n];x,y=gx*520,gy*360
        add(n,label(n),x,y,color=MODULES[t['owner']][2])
        key='＋'.join(short.get(n,'编号') if c=='id' else field_label(n,c) for c in t['pk'])
        add(n+'__pk',key,x,y-106,'ellipse',True,font=18)
        lines.append(f'{j(n)} -> {j(n+"__pk")} [color="#77818b"];')
        attrs=[c for c in chosen_attributes.get(n,attributes(t)[:2]) if c not in t['pk'] and any(a['name']==c for a in t['columns'])][:2]
        for i,c in enumerate(attrs):
            ax=x+((i*2-1)*120 if len(attrs)>1 else 0)
            add(n+'__'+c,field_label(n,c),ax,y+106,'ellipse',font=18)
            lines.append(f'{j(n)} -> {j(n+"__"+c)} [color="#77818b"];')
    for i,f in enumerate(f for f in FOREIGN if f['child'] in selection and f['parent'] in selection):
        # Keep only the business focus in report projections. The complete graphs
        # still retain these extra references, which otherwise obscure the panel.
        if title=='企业车队与用车额度' and f['child']=='charge_order' and f['columns'] in [['account_id'],['vehicle_id']]: continue
        if title=='用户消费票据与运营商结算票据' and f['child']=='consumer_invoice' and f['columns']==['order_id']: continue
        a,b=f['parent'],f['child'];ax,ay=layout[a];bx,by=layout[b]
        x,y=(ax+bx)*260,(ay+by)*180
        if a==b:x,y=ax*520+(-250 if a=='consumer_invoice' else 250),ay*360
        if ax==bx and a!=b:x+=220
        text=RELATIONS.get((b,','.join(f['columns'])),'关联'+label(a))
        w=(text_width(text,15)+26)*1.75;h=80
        def clear(cx,cy):
            box=(cx-w/2-10,cy-h/2-10,cx+w/2+10,cy+h/2+10)
            return all(box[2]<q[0] or q[2]<box[0] or box[3]<q[1] or q[3]<box[1] for q in occupied)
        candidates=[(x+dx,y+dy) for dx,dy in [(0,0),(0,70),(0,-70),(170,0),(-170,0),(170,110),(-170,110),(230,-90),(-230,-90),(0,200),(230,200),(-230,200)]]
        x,y=next(((cx,cy) for cx,cy in candidates if clear(cx,cy)),(x+320,y+160))
        r='report_rel_'+str(i);add(r,text,x,y,'diamond',font=15)
        style=',style=dashed' if f['kind']=='logical' else ''
        if a==b:
            p1,p2,p3,p4=('nw','ne','se','sw') if a=='consumer_invoice' else ('ne','nw','sw','se')
            lines.append(f'{j(a)}:{p1} -> {r}:{p2} [label="0..1"];')
            lines.append(f'{r}:{p3} -> {j(b)}:{p4} [label="0..1"];')
        else:
            lines.append(f'{j(a)} -> {r} [label={j("0..1" if f["optional"] else "1")}{style}];')
            lines.append(f'{r} -> {j(b)} [label={j("N" if f["many"] else "0..1")}{style}];')
    return '\n'.join(lines+['}'])


USECASES={
 "A": (["平台运营管理员","场站运维工程师","车主用户","设备/心跳模拟器"],
        ["登记场站与桩枪","验收并投运","申请改造/迁移/退役","审核档案变更","查询场站与可用枪","上报心跳与设备状态","离线扫描并生成待办"],
        [(0,0),(0,1),(1,1),(1,2),(0,3),(2,4),(3,5),(3,6)],[]),
 "Q": (["车主用户","周期调度器","设备状态服务"],
        ["预计到站费用估算","线上取号","取消排队","兼容性与归属校验","按队列叫号","保留可用枪","超时释放与顺延","凭有效叫号扫码开单","设备离线撤销保留"],
        [(0,0),(0,1),(0,2),(1,4),(1,6),(0,7),(2,8)],[(1,3,"include"),(4,3,"include"),(4,5,"include"),(7,3,"include"),(6,4,"extend")]),
 "B": (["车主用户","电表/设备模拟器","客服结算专员","支付回执模拟器"],
        ["扫码启动充电","校验枪/账户/车辆资格","查看充电进度与账单","结束充电","分时分段核价","断连暂结与人工复核","分次支付与补缴","支付幂等与余额入账","办理退款"],
        [(0,0),(0,2),(1,3),(1,5),(2,5),(0,6),(3,7),(2,8)],[(0,1,"include"),(3,4,"include"),(5,3,"extend"),(6,7,"include")]),
 "C": (["设备模拟器","平台运营管理员","场站运维工程师","周期调度器"],
         ["批量采集运行数据","按桩/枪范围产生合并告警","派单与再次派单","接单/到场/修复/关闭","登记备件与处理结果","超时升级与通知","连续运行与枪状态复核","解除告警并恢复可用"],
         [(0,0),(0,1),(1,1),(1,2),(2,3),(2,4),(3,5),(2,6),(2,7)],[(1,0,"extend"),(3,4,"include"),(7,6,"include")]),
 "D": (["车主用户","平台运营管理员","企业车队管理员"],
        ["注册/登录/实名","绑定及换绑车辆","领取新人/定向券","核销优惠券","查询余额与流水","申请电子发票","报障与评价","配置及审批活动","批量开卡并绑定用车人","设置与校验车队额度","查询车队月账单","申请企业专属价格"],
        [(0,0),(0,1),(0,2),(0,3),(0,4),(0,5),(0,6),(1,7),(2,8),(2,9),(2,10),(2,11)],[]),
 "E": (["客服结算专员","运营商经办人","平台审批管理员"],
        ["按站点账期生成结算","导入运营商账单","逐订单对账与差异核查","登记本方差异确认","双方确认后应用调整","确认结算及登记付款","申请/开具结算发票","红冲并保留原票","校验累计开票额度"],
        [(0,0),(0,1),(0,2),(0,3),(1,3),(2,4),(0,5),(1,5),(0,6),(0,7)],[(4,3,"include"),(6,8,"include")]),
}


def usecase(owner):
    actors,cases,associations,deps=USECASES[owner]
    lines=header(MODULES[owner][1]+"｜UML 用例图","LR",17)
    for i,a in enumerate(actors): lines.append(f'actor_{i} [shape=box,{geometry(a,size=17,icon=True)},style=filled,color="white",fillcolor="white",label={j(a)}];')
    lines.append('subgraph cluster_system { label="'+MODULES[owner][1]+'子系统"; style=rounded; color="#8194a6";')
    for i,c in enumerate(cases): lines.append(f'uc_{i} [shape=ellipse,{geometry(c,"ellipse",17)},style=filled,fillcolor="#f3f7fb",label={j(c)}];')
    lines.append('}')
    for a,c in associations: lines.append(f'actor_{a} -> uc_{c} [dir=none];')
    for a,b,kind in deps: lines.append(f'uc_{a} -> uc_{b} [style=dashed,label="«{kind}»",constraint=false,arrowhead=open];')
    return "\n".join(lines+["}"])


ROBUST={
 "A": (["管理员/运维","设备模拟器","车主"],
       ["设备档案与验收页","变更申请/审批页","设备心跳接入","场站查询接口"],
       ["设施登记与验收控制","变更审批及层级约束控制","在线状态与离线待办控制","可用枪查询控制"],
       ["operator","station","charger","connector","asset_request","asset_history"],
       [(0,0),(0,1),(1,2),(2,3)],[(0,0),(1,1),(2,2),(3,3)],
       [(0,"operator"),(0,"station"),(0,"charger"),(0,"connector"),(0,"asset_request"),(1,"asset_request"),(1,"charger"),(1,"connector"),(2,"charger"),(2,"asset_history"),(2,"asset_request"),(3,"station"),(3,"connector")],
       [("C：告警及断连处置控制",2),("Q：留枪资格控制",3)]),
 "Q": (["车主","周期调度器","设备状态服务"],
       ["预计到站估价页","取号/取消接口","定时叫号入口","扫码开单入口"],
       ["预计电量及费率估算控制","排队归属与兼容校验控制","叫号与留枪分配控制","扫码转单与幂等控制"],
       ["vehicle","queue_entry","queue_call","gun_hold","connector"],
       [(0,0),(0,1),(1,2),(0,3),(2,2)],[(0,0),(1,1),(2,2),(3,3)],
       [(0,"vehicle"),(0,"connector"),(1,"vehicle"),(1,"queue_entry"),(2,"queue_entry"),(2,"queue_call"),(2,"gun_hold"),(2,"connector"),(3,"gun_hold"),(3,"queue_entry")],
       [("B：统一费率估算控制",0),("D：车辆归属/额度控制",1),("B：创建充电订单控制",3)]),
 "B": (["车主","读数/支付模拟器","客服结算员"],
       ["扫码与进度接口","读数/结束回执入口","支付与退款接口","异常复核工作台"],
       ["开单与枪占用事务控制","分段计量及核价控制","支付幂等与退款控制","人工复核审批控制"],
       ["charge_order","tariff","tariff_band","meter_sample","fee_detail","order_review","payment","refund"],
       [(0,0),(1,1),(0,2),(1,2),(2,2),(2,3)],[(0,0),(1,1),(2,2),(3,3)],
       [(0,"charge_order"),(0,"tariff"),(1,"charge_order"),(1,"tariff_band"),(1,"meter_sample"),(1,"fee_detail"),(1,"order_review"),(2,"charge_order"),(2,"payment"),(2,"refund"),(3,"order_review"),(3,"charge_order")],
       [("A/Q：枪资格与保留控制",0),("D：账户/车队额度控制",0),("D：优惠券与钱包事务控制",2)]),
 "C": (["设备模拟器","管理员/调度器","运维工程师"],
        ["遥测/枪级告警接入","派单及超时任务入口","工单处理页面","恢复复核入口"],
        ["采样与桩枪告警去重控制","派单与响应超时控制","工单状态与备件控制","连续运行与枪状态复核控制"],
        ["telemetry","alarm_rule","alarm","alarm_notice","work_order","work_part","connector"],
        [(0,0),(1,0),(1,1),(2,2),(2,3)],[(0,0),(1,1),(2,2),(3,3)],
        [(0,"telemetry"),(0,"alarm_rule"),(0,"alarm"),(0,"connector"),(1,"alarm"),(1,"alarm_notice"),(1,"work_order"),(2,"work_order"),(2,"work_part"),(3,"telemetry"),(3,"alarm"),(3,"work_order"),(3,"connector")],
       [("A/Q：离线状态及留枪撤销控制",0),("B：异常断连暂核控制",0),("A：设备恢复可用控制",3)]),
 "D": (["车主","运营管理员","车队管理员"],
       ["注册/实名与车辆页面","活动与优惠券入口","个人中心及发票入口","车队管理工作台"],
       ["账号认证与车辆归属控制","活动发放及核销控制","余额/发票/反馈控制","车队卡额度及专属价控制"],
       ["account","vehicle","vehicle_binding","campaign","coupon","redemption","wallet_entry","consumer_invoice_request","driver_feedback","fleet","fleet_card"],
       [(0,0),(1,0),(0,1),(1,1),(0,2),(2,3)],[(0,0),(1,1),(2,2),(3,3)],
       [(0,"account"),(0,"vehicle"),(0,"vehicle_binding"),(1,"campaign"),(1,"coupon"),(1,"redemption"),(2,"wallet_entry"),(2,"consumer_invoice_request"),(2,"driver_feedback"),(3,"fleet"),(3,"fleet_card")],
       [("B：订单核价/支付事务控制",1),("B：支付退款流水控制",2),("E：企业对公结算控制",3)]),
 "E": (["客服结算员","运营商经办人","平台审批人"],
       ["月结与账单导入页面","逐单差异核查页面","双方确认接口","开票/红冲与付款入口"],
       ["账期汇总与快照控制","逐单差异比对控制","双边确认与调整控制","净开票额度与结款控制"],
       ["settlement","settlement_item","external_bill","recon_diff","diff_confirmation","settlement_adjustment","settlement_invoice"],
       [(0,0),(0,1),(0,2),(1,2),(2,2),(0,3)],[(0,0),(1,1),(2,2),(3,3)],
       [(0,"settlement"),(0,"settlement_item"),(0,"external_bill"),(1,"settlement_item"),(1,"external_bill"),(1,"recon_diff"),(2,"recon_diff"),(2,"diff_confirmation"),(2,"settlement_adjustment"),(3,"settlement"),(3,"settlement_invoice")],
       [("B：核价/支付/退款快照控制",0),("D：运营商身份与权限控制",2),("A：场站归属及协议控制",0)]),
}


def robustness(owner):
    actors,bounds,controls,entities,ab,bc,ce,cross=ROBUST[owner]
    # Newly added tables participate through the controlling service of their module.
    for n,t in TABLES.items():
        if t["owner"]==owner and n not in entities:
            entities=entities+[n]; ce=ce+[(len(controls)-1,n)]
    lines=header(MODULES[owner][1]+"｜鲁棒图（分析模型，非时序图）","LR",16)
    for i,a in enumerate(actors): lines.append(f'actor_{i} [shape=box,{geometry(a,size=16,icon=True)},color="white",label={j(a)}];')
    for i,b in enumerate(bounds): lines.append(f'boundary_{i} [shape=box,{geometry(b,size=16,icon=True)},color="white",label={j(b)}];')
    for i,c in enumerate(controls): lines.append(f'control_{i} [shape=box,{geometry(c,size=16,icon=True)},color="white",label={j(c)}];')
    for n in entities:
        if n in TABLES: lines.append(f'entity_{n} [shape=box,{geometry(label(n),size=16,icon=True)},color="white",label={j(label(n))}];')
    for a,b in ab: lines.append(f'actor_{a} -> boundary_{b} [dir=none];')
    for b,c in bc: lines.append(f'boundary_{b} -> control_{c} [label="请求/事件"];')
    for c,e in ce:
        if e in TABLES: lines.append(f'control_{c} -> entity_{e} [dir=both,arrowtail=open,arrowhead=open,color="#3b6d91"];')
    for i,(c,target) in enumerate(cross):
        lines.append(f'cross_{i} [shape=box,{geometry("«control»\\n"+c,size=14)},style="rounded,dashed",fillcolor="#f2f5f7",label={j("«control»\\n"+c)},fontsize=14];')
        lines.append(f'control_{target} -> cross_{i} [style=dashed,label="调用/协作",constraint=false];')
    links={"A":[(0,2),(1,2),(2,3)],"Q":[(1,2),(2,3)],"B":[(0,1),(1,2),(1,3),(3,2)],"C":[(0,1),(1,2),(2,3)],"D":[(0,1),(1,2),(3,2)],"E":[(0,1),(1,2),(2,3)]}
    for a,b in links[owner]: lines.append(f'control_{a} -> control_{b} [style=dotted,label="业务协作",constraint=false];')
    legend="boundary：页面/接入边界；control：业务协调\nentity：领域实体；虚线：跨线控制依赖\n参与者只接边界，边界经控制访问实体"
    lines.append(f'legend [shape=note,{geometry(legend,size=12)},fontsize=12,label={j(legend)}];')
    return "\n".join(lines+["}"])


TABLES,FOREIGN,HASHES=read_schema()
# Keep the inherited 20-source audit trail, including regression and backup SQL.
_existing_model = OUT / '模型清单.json'
if _existing_model.exists():
    _previous = json.loads(_existing_model.read_text(encoding='utf-8'))
    for _relative, _digest in _previous.get('sql_sha256', {}).items():
        _source = (PROJECT / _relative).resolve()
        if _source.is_relative_to(PROJECT) and _source.is_file():
            HASHES.setdefault(_relative, hashlib.sha256(_source.read_text(encoding='utf-8-sig').encode()).hexdigest())
if '--check' in sys.argv:
    saved = json.loads((OUT / '模型清单.json').read_text(encoding='utf-8'))
    assert set(TABLES) == set(saved['tables']), 'table set changed'
    for name, table in TABLES.items():
        for key in ('owner', 'columns', 'pk', 'unique'):
            assert table[key] == saved['tables'][name][key], (name, key)
    canonical = lambda values: sorted(json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values)
    assert canonical(FOREIGN) == canonical(saved['relationships']), 'relationships changed'
    assert len(TABLES) == 44 and sum(len(t['columns']) for t in TABLES.values()) == 320
    print(json.dumps({'tables': len(TABLES), 'columns': 320, 'relationships': len(FOREIGN),
                      'passed': True, 'mode': 'read-only parse; no PNG or manifest written'}, ensure_ascii=False))
    raise SystemExit(0)
REPORTS=[
    ('A','报告ER_资产主链',['operator','station','charger','connector'],{'operator':['name'],'station':['name','spaces'],'charger':['model','rated_kw'],'connector':['kind','max_kw']},'场站—桩—枪资产主链'),
    ('B','报告ER_订单计量与费率',['tariff','tariff_band','charge_order','meter_sample','fee_detail'],{'tariff':['starts','ends'],'tariff_band':['label','energy_rate'],'charge_order':['started_at','kwh'],'meter_sample':['reading'],'fee_detail':['kwh','energy']},'订单计量与费率'),
    ('B','报告ER_支付退款与复核',['charge_order','payment','refund','order_review'],{'charge_order':['gross','state'],'payment':['amount','reference'],'refund':['amount','reference'],'order_review':['reason','conclusion']},'支付、退款与异常复核'),
    ('D','报告ER_用户与车辆',['account','vehicle','vehicle_binding'],{'account':['login','tier'],'vehicle':['plate_mask','capacity_kwh'],'vehicle_binding':['since','binding_end']},'用户与车辆归属'),
    ('D','报告ER_活动与核销',['campaign','coupon','redemption','charge_order'],{'campaign':['face','minimum'],'coupon':['issued_at'],'redemption':['discount','used_at'],'charge_order':['gross','discount']},'优惠活动、发券与核销'),
    ('D','报告ER_车队与额度',['fleet','fleet_card','account','vehicle','charge_order'],{'fleet':['name'],'fleet_card':['credit_limit','reserved_amount'],'account':['login'],'vehicle':['plate_mask','max_kw'],'charge_order':['gross','state']},'企业车队与用车额度'),
    ('E','报告ER_结算对账与确认',['settlement','settlement_item','external_bill','recon_diff','diff_confirmation','settlement_confirmation','settlement_adjustment'],{'settlement':['period','state'],'settlement_item':['net_received'],'external_bill':['amount','paid'],'recon_diff':['kind','delta'],'diff_confirmation':['conclusion','confirmed_at'],'settlement_confirmation':['confirmed_at'],'settlement_adjustment':['amount','reason']},'结算、逐单对账与双方确认'),
    ('E','报告ER_消费与结算票据',['consumer_invoice_request','consumer_invoice','charge_order','settlement','settlement_invoice'],{'consumer_invoice_request':['title','state'],'consumer_invoice':['amount','issued_at'],'charge_order':['gross'],'settlement':['period','state'],'settlement_invoice':['amount','issued_at']},'用户消费票据与运营商结算票据'),
]
manifest=[]
def write(path,source,kind):
    path.parent.mkdir(parents=True,exist_ok=True)
    manifest.append({"source":source,"source_sha256":hashlib.sha256(source.encode('utf-8')).hexdigest(),"png":path.relative_to(PROJECT).as_posix(),"kind":kind,"engine":'neato' if kind=='报告友好ChenER' else 'dot'})

for owner,(folder,title,color) in MODULES.items():
    base=IMAGES/folder
    write(base/"局部ER图.png",chen(owner),"Chen局部ER")
    write(base/"用例图.png",usecase(owner),"UML用例")
    write(base/"鲁棒图.png",robustness(owner),"鲁棒图")
    write(base/"全局UML分区详图.png",uml(owner),"UML分区详图")
globalbase=IMAGES/MODULES['A'][0]
write(globalbase/"全局UML类图.png",uml(),"全局UML")
write(globalbase/"全局ER图.png",chen(),"全局ChenER")
for owner,filename,selection,attrs,title in REPORTS:
    layouts={
        '报告ER_资产主链':{'operator':(0,0),'station':(1,0),'charger':(1,1),'connector':(0,1)},
        '报告ER_订单计量与费率':{'tariff':(0,0),'tariff_band':(1,0),'charge_order':(0,1),'fee_detail':(1,1),'meter_sample':(.5,2)},
        '报告ER_支付退款与复核':{'charge_order':(0,0),'order_review':(1,0),'payment':(0,1),'refund':(1,1)},
        '报告ER_用户与车辆':{'account':(0,0),'vehicle':(1,0),'vehicle_binding':(.5,1)},
        '报告ER_活动与核销':{'campaign':(0,0),'coupon':(1,0),'charge_order':(0,1),'redemption':(1,1)},
        '报告ER_车队与额度':{'account':(0,0),'fleet':(1,0),'vehicle':(0,1),'fleet_card':(1,1),'charge_order':(.5,2)},
        '报告ER_结算对账与确认':{'settlement':(1,0),'settlement_confirmation':(2,0),'settlement_item':(0,1),'external_bill':(2,1),'recon_diff':(1,1.8),'diff_confirmation':(0,2.7),'settlement_adjustment':(2,2.7)},
        '报告ER_消费与结算票据':{'charge_order':(0,0),'settlement':(1.5,0),'consumer_invoice_request':(0,1),'consumer_invoice':(0,2),'settlement_invoice':(1.5,2)},
    }
    write(IMAGES/MODULES[owner][0]/(filename+'.png'),report_chen(owner,selection,title,attrs,layouts[filename]),'报告友好ChenER')
inventory={"tables":TABLES,"relationships":FOREIGN,"sql_sha256":HASHES,"table_count":len(TABLES),"relationship_count":len(FOREIGN)}
(OUT/"模型清单.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"render_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
index=["# 图件索引与建模口径", "", "整合日期：2026-11-16。本工具只读解析第二版02目录SQL，不连接数据库、不执行SQL；运行本脚本准备清单，PNG仅由显式运行render.mjs重绘。", "",
       f"本版覆盖 **{len(TABLES)} 个实体、{len(FOREIGN)} 条物理或逻辑关联**。全局图覆盖全部实体与关联；六张 UML 分区详图列出该区所有字段及直接引用的外部实体。", "",
       "正式PNG按A—E保存在业务分线与图件，历史QA拼图位于第二版过程文件/历史记录/图件目视检查。工具只保存PNG与内嵌布局JSON，不落盘DOT/SVG。", "",
       "## 图例与一致性", "", "- Chen E-R：矩形实体、菱形业务联系、椭圆业务属性、下划线主标识。外键通过联系表达，不再重复绘为普通属性；组合主标识合并为一个下划线属性。", 
       "- 1/N 为最大基数，N 允许 0..N；0..1 表示可选。外键必填性决定父实体端基数；唯一外键决定子实体端最多一条。跨行状态、有效期互斥等额外限制见 SQL，不由普通 1/N 代替。", 
        "- UML 分区图：PK/FK 标明标识与物理外键，‘关联’表示非物理外键的逻辑链接，‘派生’表示数据库生成列，[1]/[0..1] 表示属性必填性；不同用途的多条外键分别标注列名。总览只选主标识与关键属性，完整字段查看分区图。", 
       "- 虚线为逻辑关联：分区遥测由触发器校验桩编号；对账保留未知外部订单号时可能没有平台订单，不能伪称物理外键。", 
       "- 鲁棒图明确区分 boundary（页面/接入）、control（业务协调）、entity（领域实体），并绘出跨线控制依赖。它是需求分析模型，不是顺序图，也不是已通过接口验收的证明。", 
       "- 用例图中 include 只表示被包含的必需子行为，extend 表示条件扩展；此前/之后的业务前置条件不强行画成 include。", 
        "- 异常复核 order_review 直接关联 charge_order，未再错误挂到 fee_detail 下。旧 Word 图示说明作为背景文字保留；本索引、PNG 和模型清单是本版图结构依据。",
        "- 告警 alarm.connector_id 为可选的真实枪来源：NULL 表示整桩或未指定枪，不把桩下全部枪伪装为来源。scope_connector 是去重用生成列，Chen 图不把它当业务属性；枪级恢复仍以桩级连续遥测为观测基础，并额外检查指定枪状态。",
        "- 余额流水 wallet_entry.topup_ref 为可空且唯一的充值请求号；全字段 UML 保留该字段，充值幂等不再依靠负数主键。", "",
       "## 全局图", ""]
for name in ['全局UML类图','全局ER图']:
    rel=Path(MODULES['A'][0])/name
    index.append(f"- {name}：[PNG](业务分线与图件/{rel.as_posix()}.png)")
index += ["", "## 各业务线", "", "| 分区 | Chen 局部 E-R | 用例图 | 鲁棒图 | 完整字段 UML |", "|---|---|---|---|---|"]
for owner,(folder,title,color) in MODULES.items():
    index.append('| '+title+' | '+' | '.join(f'[{name}](业务分线与图件/{folder}/{name}.png)' for name in ['局部ER图','用例图','鲁棒图','全局UML分区详图'])+' |')
index += ["", "## 重建与校核", "", "1. 在第二版根目录用本工程Python运行 `03_需求与设计/图件维护工具/生成图件.py`（只核对加 --check），只读抽取建表、ALTER 新增列、主键、唯一键及外键，更新模型与内嵌布局清单。", "2. 需要重绘时，在工具目录先npm ci，再运行 `render.mjs`，依赖由本目录package-lock锁定；仅核对清单可运行node render.mjs --check，无需npm依赖。渲染中间格式只驻留内存，最终仅写出 PNG。", "3. 核对 `图件维护工具/模型清单.json` 中的实体、字段、关系和 SQL 哈希；查看 `图件维护工具/渲染结果.json` 的尺寸与警告。", "4. 目视检查 PNG；SQL 更新后必须重新生成，不能只修改图片上的表名。", "", "新增实体自动归入其 SQL 所在业务分区；新的用例/控制协作及中文命名仍需按业务语义人工评审。全局大图用于完整性检查，报告应同时使用模块详图，避免压缩到一页导致字号过小。"]
index += ['', '## 报告插图用子图', '', '保留全部完整图。下列子图每张只选3–7个业务实体及重点属性，适合个人报告、分节说明和答辩内联展示；为保持字号，省略子图外的用户、场站、权限等引用，以及不属于本图重点的重复关联路径。省略不表示删除实体或外键，完整关系仍以原全局图和六区UML为准。票据图分开展示用户订单开票与运营商结算开票的不同依据，不把两类票据混为一体。', '', '| 业务 | 子图 | 实体数 |', '|---|---|---|']
for owner,filename,selection,attrs,title in REPORTS:
    folder=MODULES[owner][0]
    index.append(f'| {MODULES[owner][1]} | [{title} PNG](业务分线与图件/{folder}/{filename}.png) | {len(selection)} |')
(PROCESS/'图件索引.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
globaldoc=['# 全局模型与图码对应', '', '本文件由 `03_需求与设计/图件维护工具/生成图件.py` 从当前业务 DDL 重新生成。旧版只展示主链的 Mermaid 图已由完整图件及下列实体、关系清单替代。', '',
           f'本版包含 {len(TABLES)} 个业务实体、{sum(len(t["columns"]) for t in TABLES.values())} 个表字段、{sum(f["kind"]=="physical" for f in FOREIGN)} 条物理外键关系和 {sum(f["kind"]=="logical" for f in FOREIGN)} 条逻辑关联。部署跟踪表不属于业务概念模型。', '',
           '全局图：[UML PNG](../../../业务分线与图件/A_场站设施与排队/场站与充电设施/全局UML类图.png) · [Chen E-R PNG](../../../业务分线与图件/A_场站设施与排队/场站与充电设施/全局ER图.png)。完整字段分区图与全部分析图见 [图件索引](../../../图件索引.md)。', '',
           '全局概念图以业务实体及基数表达关系；主标识下划线。UML 为持久化数据类模型，属性保留类型、主外键及必填性。历史金额及计费快照属于历史事实，不能由当前费率或当前设备归属回推。', '',
           '## 实体分区', '', '| 分区 | 实体 |', '|---|---|']
for owner,(_,title,_) in MODULES.items():
    globaldoc.append('| '+title+' | '+'、'.join(f'{label(n)}（`{n}`）' for n,t in TABLES.items() if t['owner']==owner)+' |')
globaldoc+=['', '## 完整关系清单', '', '复合外键作为一条关系列出；逻辑关联不冒充数据库外键。未知外部订单号可能无法匹配平台订单，所以相应关系为可选虚线。', '', '| 子实体与字段 | 父实体与引用字段 | 类型 | 子实体数量 / 每个子实体的父实体数量 |', '|---|---|---|---|']
for f in FOREIGN:
    globaldoc.append(f'| `{f["child"]}({", ".join(f["columns"])})` | `{f["parent"]}({", ".join(f["references"])})` | '+('物理外键' if f['kind']=='physical' else '逻辑关联（虚线）')+f' | {"0..N" if f["many"] else "0..1"} / {"0..1" if f["optional"] else "1"} |')
globaldoc+=['', '## 结构核对', '', '实际 MySQL 元数据逐项核对结果见 `../../../图件维护工具/图模数据库一致性.json`。异常复核 `order_review.order_id` 直接引用 `charge_order.id`，并不引用费用分段。图中的可选性不代替跨表约束、并发互斥和状态机测试。']
global_doc_path=DESIGN_ROOT/'模型与数据字典/A/场站与充电设施/全局模型.md'
global_doc_path.parent.mkdir(parents=True,exist_ok=True)
global_doc_path.write_text('\n'.join(globaldoc)+'\n',encoding='utf-8')
print(f"Read-only DDL model: {len(TABLES)} entities, {len(FOREIGN)} relationships; {len(manifest)} PNG render jobs prepared.")

# Coding: utf-8
"""Build an offline Chinese design dictionary from structure metadata and SQL exports.
No database connection or business-row input is used.
"""
from pathlib import Path
from collections import defaultdict
import csv
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '01_平台工程'))
from project_paths import DESIGN_ROOT
META=DESIGN_ROOT/"模型与数据字典/数据库结构快照.json"
MODEL=DESIGN_ROOT/"图件维护工具/模型清单.json"
OUTPUT=DESIGN_ROOT/"模型与数据字典/数据库设计与数据字典.md"
EXPORTS=DESIGN_ROOT/"数据库结构导出"

TABLE_INFO={
"operator":("运营商","A","登记场站经营主体，独立维护运营商名称。"),
"station":("充电场站","A","保存当前运营商、位置、营业时间、车位与启用状态。"),
"charger":("充电桩","A","保存桩级设施参数、验收投运日期、心跳及状态。"),
"connector":("充电枪","A","保存桩下枪位、接口、功率与运行状态；开单与排队按枪互斥。"),
"asset_history":("设施状态历史","A","逐次记录桩或枪的状态变化，一条历史只能对应其中一种设施。"),
"asset_request":("设施变更申请","A","保存验收、参数变更及下线申请的载荷与审核状态。"),
"queue_entry":("到站排队","A-排队","按场站登记车主车辆的排队与转单状态。"),
"queue_call":("叫号通知","A-排队","保存一次排队的具体叫号、枪位分配、通知及保留期限。"),
"gun_hold":("枪位临时保留","A-排队","把叫号与枪位绑定，跟踪保留、用枪、超时和释放。"),
"tariff":("费率版本","B","按场站和可选车队确定有效期、服务计费方式、最低收费与预授权额度。"),
"tariff_band":("分时费率区间","B","保存费率版本中的每日分钟区间、电价与服务费率。"),
"charge_order":("充电订单","B","保存一次充电的身份归属、计费版本、资金预授权、实际费用及生命周期。"),
"meter_sample":("电表原始读数","B","保存订单在采样时刻的累计电表读数，供插值与分段核价使用。"),
"fee_detail":("分段费用明细","B","保存核价后各时间段的电量、费率快照、电费与服务费。"),
"order_review":("异常核价复核","B","为断连、插值或预算异常订单保存待核价证据及人工结论。"),
"payment":("付款记录","B","保存模拟渠道或钱包付款结果，使用渠道和流水号保证幂等。"),
"refund":("退款记录","B","区分减少债权的正常退款与保留债权的收款撤销，保留原付款引用。"),
"telemetry":("设备遥测","C","按桩和时刻采集电压、电流、功率、温度、离线时长和故障码；按时间分区。"),
"alarm_rule":("告警规则","C","按故障码配置触发时的严重等级与首次响应时限。"),
"alarm":("告警事件","C","保存告警触发时规则快照、升级与恢复时刻，并限制同桩同码的重复活动告警。"),
"work_order":("故障维修工单","C","保存指派技术员及接单、到场、修复、关闭的顺序时间和维修结果。"),
"work_part":("工单备件使用","C","按工单与备件名称记录使用数量。"),
"alarm_notice":("告警通知事件","C","记录告警某类通知已生成，避免同类通知重复登记；不代表短信已真实发送。"),
"account":("平台账号","D","承载车主与工作人员身份、角色范围、认证信息、会员层级及钱包余额。"),
"vehicle":("车辆档案","D","保存脱敏车牌和车辆充电参数，身份绑定历史另表维护。"),
"vehicle_binding":("车辆绑定历史","D","保存车辆与账号的有效绑定区间，限制同一车辆同时只有一个当前绑定。"),
"fleet":("车队","D","维护车队名称及管理账号。"),
"fleet_card":("车队车辆额度卡","D","关联车队、车辆、驾驶员和授信上限，同时保留活动订单冻结额。"),
"campaign":("领券活动","D","配置活动有效期、适用场站与会员层级、券面额、门槛及总发行上限。"),
"coupon":("用户优惠券","D","记录某账号从某活动领到的一张券，同活动每账号至多一张。"),
"redemption":("优惠券核销","D","把券与订单一对一关联，保存实际优惠金额与核销时刻。"),
"wallet_entry":("钱包流水","D","记录钱包资金实际增减；预授权冻结不作为钱包扣款流水。"),
"consumer_invoice_request":("用户发票申请","D","登记订单开票抬头和审批状态，实际蓝票及红冲记录另表保存。"),
"driver_feedback":("车主反馈","D","登记订单相关故障或评价类反馈文本；本表没有独立数字星级字段。"),
"settlement":("运营商月结单","E","按历史运营商、场站、账期归集应结金额，双方签字后冻结。"),
"settlement_item":("月结订单快照","E","记录订单唯一首结、原服务月份及退款前客户金额和三项分摊。"),
"settlement_import":("外账完整批次","E","登记一张草稿结算单的外账批次、声明行数及导入完成状态。"),
"external_bill":("外部账单行","E","保留完整外账，包括平台未知订单及退款负金额，供漏单多单比较。"),
"recon_diff":("对账差异","E","保存差异两侧快照、差额、建议调整额及双方一致后的结论。"),
"diff_confirmation":("差异双方意见","E","分别保存平台和运营商对单项差异的accept/reject意见，允许暂时相反。"),
"settlement_confirmation":("结算单双边签字","E","分别保存平台与所属运营商对整张结算单的签字。"),
"settlement_adjustment":("月结调整明细","E","保存双方认可的差异调整或正常退款按原分摊逆冲的调整，来源二选一。"),
"settlement_invoice":("运营商结算票","E","记录正向结算发票及等额红冲，原票与红票均保留。"),
"consumer_invoice":("用户消费票","E","保存开票申请对应的实际金额、抬头、税号、签发人及蓝红票关联。"),
}

COMMON={
"id":"本记录内部标识，不是外部业务流水号",
"login":"登录名，平台内唯一",
"password_hash":"带随机盐的scrypt口令摘要格式，不保存明文口令",
"role":"账号业务角色，决定接口与数据范围",
"operator_id":"关联运营商编号",
"station_id":"关联场站编号",
"charger_id":"关联充电桩编号",
"connector_id":"关联充电枪编号",
"vehicle_id":"关联车辆编号",
"account_id":"关联平台账号编号",
"tariff_id":"关联费率版本编号",
"fleet_id":"关联车队编号",
"fleet_card_id":"可选的车队额度卡编号；空值表示个人钱包模式",
"manager_id":"车队管理账号编号",
"driver_id":"额度卡指定驾驶员账号编号",
"order_id":"关联充电订单编号",
"payment_id":"关联原付款编号",
"refund_id":"关联退款编号",
"alarm_id":"关联告警事件编号",
"technician_id":"被指派维修技术员的账号编号",
"campaign_id":"关联领券活动编号",
"coupon_id":"关联优惠券编号",
"settlement_id":"关联结算单编号",
"diff_id":"关联对账差异编号",
"request_id":"关联用户发票申请编号",
"call_id":"关联叫号编号，同时作为枪位保留主标识",
"entry_id":"关联到站排队编号",
"actor":"执行确认一方的账号编号",
"original_id":"被本次全额红冲的原正票编号；正票为空",
"issued_by":"签发该消费票或红冲票的工作人员账号编号",
"phone_cipher":"手机号的Fernet密文，密钥在库外配置",
"phone_mask":"仅供展示的脱敏手机号，不是唯一标识",
"plate_cipher":"车牌的Fernet密文，密钥在库外配置",
"plate_mask":"仅供展示的脱敏车牌，不是唯一标识",
"verified":"管理员标记的车主认证状态；布尔值，不代表已接外部实名认证服务",
"tier":"会员层级标签；实际列为自由文本，不是数据库ENUM",
"registered_at":"账号注册时刻",
"balance":"钱包账面余额，已实际扣款和退款后的人民币金额",
"reserved_balance":"所有活动订单冻结的钱包金额合计，可用余额为balance减本字段",
"failed_logins":"累计失败登录计数，由登录逻辑更新",
"locked_until":"账号临时禁止登录的截止时刻；空值表示没有活动锁定期限",
"model":"设备或车辆型号名称",
"protocol":"充电桩通信协议标识文本",
"interface":"充电接口标准标识；车辆与枪的兼容判断比较该值",
"capacity_kwh":"车辆电池名义容量",
"max_kw":"车辆或枪允许的最大充电功率；估算使用两者较小值",
"supports_dc":"车辆是否支持直流充电",
"rated_kw":"桩额定功率，枪功率还受桩额定功率校验",
"gun_position":"桩内枪位序号，同桩不可重复",
"commissioned_on":"验收通过并投运的日期；未投运为空",
"warranty_until":"保修截止日期",
"heartbeat":"桩最后有效心跳时刻，可用性判断检查最近3分钟",
"address":"场站地址说明文本",
"longitude":"地理经度；当前DDL仅由数值精度限制，未设经度区间CHECK",
"latitude":"地理纬度；当前DDL仅由数值精度限制，未设纬度区间CHECK",
"spaces":"场站可用停车位总数，非负整数",
"opens":"每日营业或活动开始时间",
"closes":"每日营业或活动结束时间",
"parking_note":"停车及收费说明文本",
"enabled":"是否启用该场站或额度卡",
"old_state":"变更前设备状态文本",
"new_state":"变更后设备状态文本",
"payload":"设施申请的JSON载荷；不是逗号分隔的多值字段",
"created_at":"本记录创建时刻",
"happened_at":"付款、退款、流水或资产事件实际登记时刻",
"starts":"版本或活动的有效起始时刻，包含该时刻",
"ends":"版本或计费段的终止时刻，不含该边界",
"expires":"领券活动失效时刻，不包含该时刻",
"free_minutes":"按小时服务费模式的免费时长",
"minimum":"最低收费或活动使用门槛",
"authorization_amount":"费率版本要求的初始资金预授权额度，须大于0",
"authorized_amount":"订单已批准的总资金预算；追加授权只增不减",
"wallet_hold":"本订单当前冻结的钱包金额；个人模式使用",
"fleet_hold":"本订单当前冻结的车队授信金额；车队模式使用",
"budget_period":"开单月份首日，用于车队月度额度核算；触发器按started_at填写",
"budget_exceeded":"原始读数对应费用是否已超过批准预算",
"stop_requested_at":"预算超限后请求停止设备充电的时刻；空值表示未请求",
"started_at":"订单实际开始时刻",
"ended_at":"订单核价使用的充电结束时刻，充电中可空",
"start_soc":"开始时电池荷电百分比，可空",
"end_soc":"结束时电池荷电百分比，可空",
"kwh":"本记录对应的充电电量",
"gross":"核价后优惠及退款前的订单总价，包含最低收费或人工复核调整",
"discount":"本记录实际核销的优惠金额",
"queued_at":"到站取号进入队列的时刻",
"called_at":"叫号分配枪位的时刻",
"deadline":"叫号保留或告警响应截止时刻",
"notified_at":"叫号通知登记时刻；演示中与叫号同时记录，不代表短信真实发送",
"sampled_at":"原始电表或设备遥测的采样时刻",
"reading":"电表累计读数，不是该采样间隔的增量电量",
"begins":"费用分段的起始时刻，包含该边界",
"minute_from":"每日费率区间起始分钟，从0点计算并包含该分钟",
"minute_to":"每日费率区间终止分钟，不含该分钟；1440表示次日0点",
"label":"核价时分时段标签快照，源于peak峰、flat平、valley谷；本费用表未另设标签CHECK",
"energy_rate":"电费单价",
"service_rate":"服务费率，单位随费率版本的service_mode决定",
"energy":"本费用分段核算出的电费金额快照",
"service":"本费用分段核算出的服务费金额快照",
"estimated":"该段边界是否用电表插值估算，供异常复核",
"reason":"异常复核或结算调整的业务原因文本",
"last_reading":"异常结算所依据的最后累计电表读数",
"adjustment":"人工复核对原核价金额的有符号调整，不是优惠券折扣",
"reviewed_by":"完成人工核价复核的工作人员账号编号",
"reviewed_at":"人工核价复核完成时刻",
"reference":"调用方提供的幂等业务流水标识",
"amount":"本记录的人民币金额",
"succeeded":"模拟支付或钱包扣款是否成功",
"debt_reduction":"本次退款实际免除的客户债权金额；减价退款等于amount，收款撤销等于0",
"volts":"采样电压",
"amps":"采样电流",
"kw":"采样有功功率",
"temperature":"采样设备温度",
"offline_seconds":"采样时报告的连续离线秒数",
"fault_code":"采样故障码；无故障为空；触发告警需匹配alarm_rule.code",
"code":"告警规则代码或事件故障码",
"severity":"告警严重等级；1到5为存储等级，5为最高值",
"response_minutes":"告警首次响应允许时长，必须大于0",
"opened_at":"告警开启或外账批次开始登记的时刻",
"escalated_at":"超时未响应告警被升级的时刻，可空",
"restored_at":"告警达到恢复条件后的恢复时刻；未恢复为空",
"assigned_at":"维修工单指派时刻",
"accepted_at":"维修人员接单时刻，可空",
"arrived_at":"维修人员到场时刻，可空",
"repaired_at":"维修完成时刻，可空",
"closed_at":"工单关闭时刻，可空",
"result":"维修结果说明；工单关闭时必须非空",
"work_id":"关联维修工单编号",
"part":"备件名称，与工单编号共同标识一条使用记录",
"quantity":"该备件使用数量，正整数",
"since":"车辆绑定开始时刻",
"binding_end":"车辆绑定结束时刻；空值表示当前有效",
"credit_limit":"该车队卡的月度授信上限，不是已付款余额",
"reserved_amount":"该额度卡被活动订单冻结的授信合计，不等于已结清款项",
"face":"优惠券面额，必须大于0",
"stock":"活动总发行数量上限；当前实现通过已发行券COUNT比较，不逐次递减该字段",
"issued_at":"优惠券、结算票或消费票签发登记时刻",
"used_at":"优惠券核销时刻",
"change":"钱包实际变动额，充值及退款为正、扣款为负，不能为0",
"topup_ref":"模拟钱包充值的全局幂等请求号，1至64位ASCII字母数字及._:-；大小写精确区分，非充值流水为空",
"scope_connector":"源枪编号的范围归一化生成列：connector_id为空取0表示桩级或未指定源枪，否则取源枪编号；本列不是物理外键",
"title":"发票申请或票据的开票抬头",
"tax_id":"开票税号文本；当前演示未接商业税务校验",
"requested_at":"用户提交开票申请的时刻",
"content":"车主提交的反馈正文文本",
"period":"结算账期月份首日",
"confirmed_at":"单项意见、整单签字或结算完成确认的时刻",
"source_period":"订单原服务结束月份首日；可早于实际首结账期",
"energy_share":"原订单电费部分分给运营商的金额快照",
"service_share":"原订单服务费部分分给运营商的金额快照",
"platform_fee":"原折后退款前金额的2%平台费快照",
"net_received":"首结的原客户折后、正常退款前金额快照；不是动态净实收",
"batch":"外部账单批次标识，同结算单必须匹配已声明批次",
"expected_rows":"该完整CSV批次声明的行数，允许0到10000",
"completed_at":"批次行数校验并完成比较的时刻",
"paid":"外账声称该行客户现金已付的标志；由双方对账核查",
"delta":"外账值减平台期望值的有符号差额，单位取决于差异种类",
"expected_kwh":"平台侧电量快照；多单时可空",
"actual_kwh":"外账侧电量快照；漏单时可空",
"expected_amount":"平台侧客户现金金额快照；多单时可空",
"actual_amount":"外账侧客户现金金额快照；漏单时可空",
"proposed_adjustment":"系统建议的运营商应结调整额，不等于原客户金额差额",
"automatic_allowed":"双方接受后是否可安全自动生成财务调整；未知多单等为否",
"customer_reduction":"退款对应的客户债权减少额快照",
"energy_reversal":"按原电费分成应逆向冲回的正金额",
"service_reversal":"按原服务费分成应逆向冲回的正金额",
"fee_reversal":"按原平台费应逆向冲回的正金额，净冲回中抵减该值",
}
OVERRIDES={
"operator":{"name":"运营主体名称"},
"station":{"name":"场站名称","opens":"场站每日营业起始时间；与closes相同表示全天营业，支持跨午夜","closes":"场站每日营业终止时间；起止相同表示全天营业","enabled":"场站当前是否启用，不等于所有枪均可用"},
"charger":{"state":"桩当前运行状态：idle空闲、occupied占用、fault故障、offline离线"},
"connector":{"kind":"枪型：AC交流或DC直流","state":"枪当前运行状态：idle空闲、occupied占用、fault故障、offline离线"},
"asset_history":{"old_state":"事件发生前桩或枪的状态快照，当前DDL未用CHECK限制文本集合","new_state":"事件发生后桩或枪的状态快照，当前DDL未用CHECK限制文本集合"},
"asset_request":{"kind":"申请种类：acceptance验收、amendment参数变更、offline下线","state":"申请状态：pending待审批、approved通过、rejected驳回","pending_charger":"仅待审批下线申请取charger_id，否则为空；生成列和唯一键保证同桩仅一项待下线申请"},
"account":{"channel":"账号注册来源标签，默认local；与支付渠道不是同一概念","role":"driver车主、admin管理员、maintenance运维、settlement结算、operator运营商、fleet车队管理员","operator_id":"运营商角色所属主体编号，其他角色可空","station_id":"运维角色可访问的场站编号，其他角色可空"},
"vehicle_binding":{"current_vehicle":"binding_end为空时取vehicle_id，否则为空；生成列唯一键限制单车当前绑定"},
"fleet":{"name":"车队名称"},
"fleet_card":{"enabled":"该车队卡当前是否启用"},
"campaign":{"name":"活动名称","station_id":"限定使用场站；空值表示不限场站","tier":"可领券的会员层级标签，空值表示不限层级","minimum":"使用本活动优惠券所需的订单金额门槛","opens":"优惠券每日适用充电时段的开始时间，核销按订单started_at判断；不是领取开始时间","closes":"优惠券每日适用充电时段的结束时间，支持跨午夜；不是领取结束时间"},
"queue_entry":{"state":"waiting等待、called已叫号、converted已转订单、expired叫号超时、cancelled已取消","active_vehicle":"仅waiting/called取vehicle_id，否则为空；与station_id联合唯一，限制同站重复活动排队"},
"queue_call":{"deadline":"本次叫号枪位保留截止时刻，必须晚于called_at"},
"gun_hold":{"state":"held正在保留、used已转订单、expired已超时、released已释放","connector_id":"叫号实际保留的枪编号，与call_id共同引用queue_call复合唯一键","active_gun":"仅state=held时取connector_id，否则为空；唯一索引保证同枪至多一个活动保留"},
"tariff":{"service_mode":"服务费计费单位：kwh按电量、hour按小时","minimum":"订单最低总收费金额，核价不足时补足","fleet_id":"车队专用费率的车队编号；为空为公共费率"},
"tariff_band":{"label":"peak峰、flat平、valley谷的分时标签"},
"charge_order":{"station_id":"开单时按枪归属写入的场站历史快照，之后不随设施搬迁改变","operator_id":"开单时场站运营商历史快照，之后不随场站经营主体变更改变","state":"starting启动中、charging充电中、finishing结束中、review待复核、billed已核价待付款、paid已结清、cancelled取消","active_gun":"仅starting/charging/finishing取connector_id，否则为空；生成列唯一键保证同枪活动订单互斥"},
"order_review":{"conclusion":"人工核价复核的说明性文本，非accept/reject二值枚举"},
"payment":{"channel":"mock模拟支付，或wallet真实本地钱包扣款；未接第三方支付网关","reference":"付款幂等流水，与channel联合唯一","amount":"本次实际付款金额，必须大于0，最多到分"},
"refund":{"reference":"退款幂等流水，在refund表全局唯一","kind":"price_adjustment正常减价退款，payment_reversal仅撤销收款并保留债权","amount":"本次退回的现金金额，必须大于0"},
"alarm":{"connector_id":"可选的故障来源枪编号，必须属于本告警charger_id；空值为桩级或未指定来源，不等于设备受影响枪列表","severity":"触发时复制规则等级；超时可逐级升高至5，之后不随当前规则重算","deadline":"触发时按规则response_minutes生成的响应截止时刻快照","live_charger":"未恢复时取charger_id，否则为空；与scope_connector、code联合唯一，限制同桩同来源范围同码的活动告警"},
"alarm_notice":{"kind":"通知事件类别文本，例如escalated表示升级；当前DDL没有CHECK枚举"},
"driver_feedback":{"kind":"fault故障反馈或rating评价文本；rating并非数值星级"},
"consumer_invoice_request":{"state":"pending待处理、issued已有签发、rejected驳回；蓝红票记录在consumer_invoice"},
"settlement":{"station_id":"该月结单对应的历史场站编号，确认后不可变","operator_id":"该月结单的历史运营商编号，确认后不可变","state":"draft可编辑草稿、confirmed双方确认冻结、paid结算款已付"},
"settlement_item":{"order_id":"全系统唯一首结订单编号，也是本表另一候选键","net_received":"订单gross-discount的退款前客户金额快照，退款另记负调整；不等于v_order_balance实时净现金"},
"settlement_import":{"state":"open尚在导入、complete行数校验并完成比较"},
"external_bill":{"order_id":"外账给出的订单编号，允许平台未知编号以保留多单证据，因此无charge_order物理外键","amount":"外账客户现金金额，跨期退款可以为负"},
"recon_diff":{"order_id":"对账引用的业务订单编号，未知多单可没有平台订单，因此不是物理外键","kind":"energy电量、price现金金额、payment收款状态、missing漏单、extra多单","conclusion":"双方一致后的accept接受建议调整或reject保留平台口径；待协商为空","delta":"energy时为电量kWh差；其他种类为客户现金人民币差，均保留正负号"},
"diff_confirmation":{"side":"platform平台方或operator运营商方","conclusion":"本方意见：accept接受系统建议调整，reject保留平台明细排除外账差异"},
"settlement_confirmation":{"side":"platform平台方或operator所属运营商方"},
"settlement_adjustment":{"order_id":"调整对应业务订单编号；多单拒绝时可能未知，故未设charge_order外键","amount":"运营商应结的有符号调整；退款为-energy_reversal-service_reversal+fee_reversal"},
"consumer_invoice":{"order_id":"由request_id所指申请对应的订单编号，作为票据历史快照保留","title":"签发时冻结的开票抬头，不随申请后续编辑改变","tax_id":"签发时冻结的税号文本，当前无商业税务校验"},
}
UNITS={
"kwh":"kWh","capacity_kwh":"kWh","reading":"kWh（累计）","last_reading":"kWh（累计）",
"rated_kw":"kW","max_kw":"kW","kw":"kW","volts":"V","amps":"A","temperature":"℃",
"longitude":"度（经度）","latitude":"度（纬度）","spaces":"个车位","gun_position":"序号",
"minute_from":"自0点起分钟","minute_to":"自0点起分钟","free_minutes":"分钟","response_minutes":"分钟","offline_seconds":"秒",
"start_soc":"%","end_soc":"%","severity":"1~5级","stock":"张（总上限）","quantity":"件","expected_rows":"行",
"energy_rate":"元/kWh","service_rate":"元/kWh或元/小时","failed_logins":"次",
}
MONEY=set("balance reserved_balance credit_limit reserved_amount face minimum authorization_amount authorized_amount wallet_hold fleet_hold gross discount energy service amount debt_reduction change adjustment energy_share service_share platform_fee net_received expected_amount actual_amount proposed_adjustment customer_reduction energy_reversal service_reversal fee_reversal".split())
DATE_FIELDS=set("budget_period period source_period commissioned_on warranty_until".split())
TIME_FIELDS=set("opens closes".split())
BOOL_FIELDS=set("verified enabled supports_dc budget_exceeded estimated succeeded paid automatic_allowed".split())
ENUM_CN={
"driver":"车主","admin":"管理员","maintenance":"运维","settlement":"结算专员","operator":"运营商","fleet":"车队管理员",
"idle":"空闲","occupied":"占用","fault":"故障","offline":"离线或下线","AC":"交流","DC":"直流",
"acceptance":"验收","amendment":"参数变更","pending":"待审批","approved":"通过","rejected":"驳回",
"starting":"启动中","charging":"充电中","finishing":"结束中","review":"待复核","billed":"已核价待付款","paid":"已结清或已付",
"cancelled":"已取消","waiting":"等待","called":"已叫号","converted":"转单","expired":"超时","held":"正在保留","used":"已用","released":"已释放",
"kwh":"按电量","hour":"按小时","peak":"峰","flat":"平","valley":"谷","mock":"模拟","wallet":"钱包",
"price_adjustment":"减价退款","payment_reversal":"撤销收款","issued":"已有签发","rating":"评价文本",
"energy":"电量差","price":"金额差","payment":"收款状态差","missing":"漏单","extra":"多单","draft":"草稿","confirmed":"双方确认冻结",
"platform":"平台方","accept":"接受建议调整","reject":"保留平台口径","open":"导入中","complete":"完整比较完成",
}

# Per-table dependencies are claims about the actual relation, not join reachability.
FD_NOTES={
"account":"login为非空候选键，login→id及其余账号属性。balance/reserved_balance是受事务维护的流水汇总，见受控冗余说明。",
"connector":"(charger_id,gun_position)为候选键，决定接口、功率与状态；不复制场站名称等主数据。",
"asset_history":"桩/枪二选一指向事件对象，old_state/new_state是事件时事实，不能由当前设备状态重算。",
"asset_request":"pending_charger是kind/state/charger_id的确定函数，为条件唯一性而物理生成，不是另一项独立业务事实。",
"vehicle_binding":"有效区间属于完整绑定事件；current_vehicle为生成列。绑定无效后同一车可有多条历史，因此vehicle_id不是全表候选键。",
"tariff_band":"(tariff_id,minute_from)→minute_to、时段标签和两种费率；minute_from单独不能决定其他列。父版本的场站/有效期不复制到本表。",
"charge_order":"订单id决定事件、收费与预算；tariff_id→费率所属station_id等跨表依赖和当前账务汇总带来有意快照冗余，物理表不宣称严格3NF。",
"meter_sample":"(order_id,sampled_at)→reading；订单和时间单独均不能决定读数。",
"fee_detail":"(order_id,begins)决定结束边界和费率快照；energy/service是电量、费率、服务计费规则的计算快照，属于为核价审计保留的派生冗余。",
"order_review":"order_id为主键，一订单至多一个复核档案；reviewed_by仅引用账号，不复制工作人员姓名。",
"payment":"(channel,reference)为非空候选键，决定付款订单、金额、结果；多次付款仍归同一订单。",
"refund":"reference为非空候选键；kind与amount决定debt_reduction，是为区分现金和债权并便于审计保留的受CHECK约束派生列。",
"queue_entry":"有效状态下(station_id,active_vehicle)唯一，历史非活动行active_vehicle为空；它不是包含NULL的全历史候选键。",
"queue_call":"id为主键，(id,connector_id)是为复合引用设置的超键，不是最小候选键。",
"gun_hold":"call_id是主键；复合外键又使call_id→connector_id成立。active_gun为状态条件生成列，order_id非空时唯一；本表包含为一致性校验保留的受控关联冗余。",
"fleet_card":"额度卡id决定归属及授信；reserved_amount是活动订单冻结额汇总，使用事务及行锁维护，不能按严格3NF普通事实列论证。",
"coupon":"(campaign_id,account_id)为非空候选键，决定该券id和签发时间；面额等活动属性从campaign读取，不复制。",
"redemption":"coupon_id为主键，order_id为非空候选键；一券一单、一单一券。discount是核销当时实际折扣快照，不随活动面额变化。",
"wallet_entry":"id决定流水；payment_id/refund_id非空时各唯一。两者可同时为空表示独立充值或初始流水；topup_ref非空时为全局幂等模拟充值号，CHECK限定正向且不关联付款/退款。不把可空唯一列称为完整候选键。",
"telemetry":"(charger_id,sampled_at)决定本次全部采样值；分区设计未设桩物理FK，由插入/更新触发器与删除保护形成逻辑引用。",
"alarm":"code指向可变规则；severity/deadline保存触发快照且severity可升级，所以code不能决定事件等级。live_charger为生成列。",
"alarm_notice":"(alarm_id,kind)→created_at，告警与通知种类单独均不能决定本行。",
"work_part":"(work_id,part)→quantity，名称与数量依赖完整组合键。",
"settlement":"(operator_id,station_id,period)为非空候选键。operator_id表示冻结归属，不能套用当前station.operator_id覆盖历史。",
"settlement_item":"order_id全局非空唯一，也是最小候选键，决定settlement_id及全部快照；(settlement_id,order_id)主键是超键而非最小候选键。",
"settlement_import":"settlement_id为主键，一单一个当前批次；(settlement_id,batch)为复合FK准备的超键。expected_rows是外部声明，不从实际行数推定。",
"external_bill":"(settlement_id,order_id)为主键；settlement_id→batch成立，因此batch依赖复合主键的真子集settlement_id，是为批次复合FK保留的受控部分依赖冗余；该物理关系不严格满足2NF/3NF。",
"recon_diff":"(settlement_id,order_id,kind)为非空候选键；两侧快照、delta、proposed_adjustment和一致conclusion有可计算依赖，作为审计证据保留。",
"diff_confirmation":"(diff_id,side)→actor、conclusion、confirmed_at；diff_id或side单独都不能决定本方意见。",
"settlement_confirmation":"(settlement_id,side)→actor、confirmed_at；同侧两个工作人员不等于双边签字。",
"settlement_adjustment":"id为主键；diff_id/refund_id二选一且非空时唯一。amount由分摊逆冲或双方建议产生，连同分量保存为不可变审计事实。",
"consumer_invoice_request":"order_id为非空候选键，一订单一申请；申请状态为流程状态，不替代实际蓝红票记录。",
"consumer_invoice":"request_id→order_id成立；本表重复order_id及抬头是票据冻结快照，并非严格3NF。original_id非空时唯一，保证原票至多一次全额红冲。",
"settlement_invoice":"正票/红票金额均为正，以original_id区分符号；原票引用用于核验等额金额；票面文本作为本次签发内容保存，属于原票/红票留痕模型，而非可覆盖汇总。",
}
EXTRA_RULES={
"station":"当前DDL没有经纬度合法区间CHECK；营业时段in_hours采用左闭右开，起止相同为全天，支持跨午夜。enabled只表示站点启用。",
"charger":"投运、参数变更与有未完成工单时的下线限制由过程/触发器完成；可用性还需有效心跳。额定功率不能直接当作实际采样功率。",
"connector":"枪额定上限受桩功率校验；正在使用的枪不能任意更改或搬迁。可用枪还需结合桩心跳、场站营业与枪保留计算。",
"account":"钱包可用资金=balance-reserved_balance；冻结不是扣款。role为CHECK文本枚举，tier/channel为普通文本。手机号密文、脱敏文本不设唯一约束。",
"campaign":"stock为总发行上限，已发行券数另查coupon；领券还校验活动日期、会员层级与并发锁。opens/closes表示券适用的每日充电时段，核销按订单started_at检查；领券和定向发放使用starts/expires整体有效期，二者不混用。",
"charge_order":"插入触发器固定历史场站/运营商及预算月；授权不可倒退，钱包/车队冻结模式互斥。净应付=gross-discount-累计正常退款债权减少额；净实付=成功付款累计-现金退款累计；欠款=净应付-净实付。同枪活动订单由active_gun唯一性与行锁共同限制。",
"tariff":"同场站同车队的有效区间不重叠；已被订单使用的费率版本及分时区间不可改。授权额度须正数，不允许用0预算代替真实额度控制。",
"tariff_band":"分时区间左闭右开、不可交叠；开单要求当日区间覆盖1440分钟。service_rate在kwh模式为元/kWh，hour模式为元/小时，免费时长仅影响按小时服务费。",
"meter_sample":"保留原始累计读数，核价检查单调不回退并按边界插值；预算超限仍保留原始样本并请求停止，不能通过丢读数伪造低费用。",
"fee_detail":"电费/服务费为段级金额快照，按分舍入；最低收费补足、正负复核差额另体现在订单gross，不保证SUM(energy+service)=gross。",
"payment":"只有mock和wallet两种渠道，没有真实第三方网关；付款重放必须匹配原订单、金额和结果。0元订单直接结清，不造0元付款。",
"refund":"正常退款减少现金及债权，订单可以继续paid；payment_reversal只撤销现金，产生欠款。退款累计不可超过原付款可退额；有效消费票可能超额时须先红冲。",
"telemetry":"charger_id与故障规则是逻辑业务关联，当前未定义charger或alarm_rule物理FK；不要在关系模式中伪标FK。数值电压/电流/功率/温度可空，DDL未统一给非负CHECK。",
"alarm":"触发时复制规则等级和响应截止，规则变化不重写旧告警；同桩、同来源范围（指定源枪或桩级）同码至多一个未恢复告警；connector_id为来源，受影响枪列表由设备状态另行推导，不能混写。",
"work_order":"必须按指派→接单→到场→修复→关闭执行；关闭需结果，已关闭时间不可改；恢复还需维修后新鲜连续健康遥测，不能靠关闭工单直接标设备恢复。",
"wallet_entry":"topup_ref仅用于mock模拟充值，1~64位ASCII请求号在全表大小写精确唯一；同账号同金额重放只返回原流水，不重复加余额，异账号或异金额重放冲突。函数先锁账号，再current-read幂等号，流水与余额在同一事务提交/回滚。该入口不接银行或第三方真实支付。",
"consumer_invoice_request":"申请state=issued不等于存在合法票额，实际金额以consumer_invoice蓝红记录及余额视图为准。",
"driver_feedback":"kind=rating仅分类文本，不存在1到5分的数值字段或对应CHECK，不能在报告中编造评分统计。",
"settlement":"完整外账比较、无未解决分歧、可收款状态及平台/运营商各一签缺一不可；确认后冻结，仅允许confirmed→paid。应结金额来自快照明细与调整，不存重复总额列。",
"settlement_item":"同一订单只首结一次；迟到付款可进入后续账期，source_period保留原服务月。电费运营商90%、服务费80%、平台费折后原客户金额2%；正起步/复核差额归服务，负复核差额按原比例减少。",
"external_bill":"外账必须保留未知订单形成extra，不能在导入时INNER JOIN平台订单过滤。金额允许负数以表示往期退款。完整批次行数和批次状态在过程与触发器中核验。",
"recon_diff":"漏单/多单必须比较全集；未付与金额差同时出现只做一次现金风险调整。双方相反意见保留并仍待协商；无法自动分摊的多单即便同意accept也不能凭空计入收入。",
"diff_confirmation":"actor必须从当前会话取值，按角色与结算单运营商归属判断本方。修改意见会使整单原签字失效。",
"settlement_confirmation":"必须是一平台方与所属运营商方，不是简单数两个账号；该表不承载差异意见。",
"settlement_adjustment":"正常退款只按debt_reduction，分别累计逆冲原energy_share/service_share/platform_fee后取相邻差额。原100元纯电费应结90-2=88，全退只冲88；多次部分退款最终仍精确冲88。payment_reversal不自动当减价收益冲回。",
"consumer_invoice":"限额=MAX(0,MIN(订单净应付,订单净实付))；有效蓝票减红票累计不能超过限额。正票及红冲金额均须>0，0元单不造0元发票；红冲等额且保留原票；这里是本地教育演示记录。",
"settlement_invoice":"正票累计不能超过应结可开票余额，红票全额引用原正票且不能重复红冲；已签票禁止更新/删除。不是商业税务接口。",
}

# Disambiguate shared names in their actual table context.
for _table,_values in {
 "charger":{"model":"充电桩设备型号"},
 "vehicle":{"model":"车辆车型名称","max_kw":"车辆可接受的最大充电功率，估算时与枪功率取较小值"},
 "connector":{"max_kw":"枪允许的最大输出功率，不能超过所属桩的额定功率"},
 "asset_history":{"happened_at":"设施状态变化登记时刻"},
 "payment":{"happened_at":"本次付款结果登记时刻"},
 "refund":{"happened_at":"本次退款发生时刻，月结据此判断截止账期"},
 "wallet_entry":{"happened_at":"钱包实际资金变动登记时刻"},
 "tariff":{"ends":"该费率版本有效期终止时刻，左闭右开不含本边界"},
 "fee_detail":{"ends":"本费用分段终止时刻，不含边界，必须晚于begins"},
 "alarm":{"opened_at":"告警首次开启时刻"},
 "settlement_import":{"opened_at":"本批次声明登记时刻"},
 "coupon":{"issued_at":"该账号优惠券签发时刻"},
 "settlement":{"confirmed_at":"平台与运营商双边签字齐备、结算单被冻结的时刻"},
 "diff_confirmation":{"confirmed_at":"本方最近一次差异意见登记或修改时刻"},
 "settlement_confirmation":{"confirmed_at":"本方对整单签字的登记时刻"},
 "settlement_invoice":{"amount":"本张正票或红冲票的正人民币金额，以original_id区分记账符号","issued_at":"本张运营商结算票或红票签发登记时刻"},
 "consumer_invoice":{"amount":"本张消费蓝票或红票的正人民币金额，original_id非空表示负向红冲","issued_at":"本张用户消费票或红票的签发登记时刻"},
}.items():
 OVERRIDES.setdefault(_table,{}).update(_values)

def cell(value):
    return str(value).replace("|", "\\|").replace("\n"," ").strip()
def code(value):
    return chr(96)+cell(value)+chr(96)
def clean_check(expression):
    return expression.replace("_utf8mb4", "").replace("\\'", "'")
def meaning(table,column):
    value=OVERRIDES.get(table,{}).get(column,COMMON.get(column))
    if value is None: raise AssertionError(f"Missing Chinese explanation: {table}.{column}")
    return value
def unit(table,column,ctype):
    if table=="recon_diff" and column=="delta": return "kWh或元，随kind"
    if column=="scope_connector": return "源枪编号/0范围标记"
    if column in UNITS: return UNITS[column]
    if column in MONEY: return "元（人民币）"
    if column in BOOL_FIELDS: return "布尔0/1惯例，类型未强制仅0/1"
    if column in DATE_FIELDS: return "日期"
    if column in TIME_FIELDS: return "每日时分秒"
    if ctype.startswith("datetime"): return "北京时间，微秒"
    if column in {"expected_kwh","actual_kwh"}: return "kWh"
    if column in {"state","kind","role","side","conclusion","channel","label","service_mode"}: return "标签/枚举文本"
    if column=="id" or column.endswith("_id") or column in {"actor","issued_by","reviewed_by","active_gun","active_vehicle","live_charger","pending_charger","current_vehicle"}: return "内部编号"
    return "文本/结构值（无物理单位）"

def generate():
    metadata=json.loads(META.read_text(encoding="utf-8-sig"))
    model=json.loads(MODEL.read_text(encoding="utf-8-sig"))
    tables=metadata["tables"]
    assert set(tables)==set(TABLE_INFO)==set(model["tables"]), "table catalog mismatch"
    columns=defaultdict(list)
    for c in metadata["columns"]:
        if c["TABLE_NAME"] in tables: columns[c["TABLE_NAME"]].append(c)
    constraints=defaultdict(list); indexes=defaultdict(list)
    for p in EXPORTS.glob("*/*/约束.csv"):
        for row in csv.DictReader(p.open(encoding="utf-8-sig",newline="")):
            if row["表"] in tables and row not in constraints[row["表"]]: constraints[row["表"]].append(row)
    for p in EXPORTS.glob("*/*/索引.csv"):
        for row in csv.DictReader(p.open(encoding="utf-8-sig",newline="")):
            if row["表"] in tables and row not in indexes[row["表"]]: indexes[row["表"]].append(row)
    assert sum(map(len,columns.values()))==320, "base table column count changed"
    foreign_groups=set((r["TABLE_NAME"],r["CONSTRAINT_NAME"]) for r in metadata["foreign_keys"])
    lines=[
"# 数据库设计与数据字典","",
"版本日期：2026-11-14。本版对应本地 MySQL 8.4.13 专用课程设计库的结构快照，覆盖 **44 张基表、320 个基表字段**。视图字段另行排除，不混算为基表字段。本文件不读取业务记录，不包含口令、密钥、实际身份信息或个人数据，也不连接数据库。","",
"依据：[数据库结构元数据](数据库结构快照.json)、最终01—10 SQL（09为权限、10为模拟钱包函数）、[各模块离线导出的字段/约束/索引CSV](../数据库结构导出)、[新版图件索引](../图件索引.md)和[模型清单](../图件维护工具/模型清单.json)。表名、类型、NULL与主外键以结构快照和SQL为准，中文解释按实际后端代码补充。重新部署后若结构变化，须重新导出核对。","",
"## 1. 总体设计与记号","",
"按A设施及排队、B订单计费、C设备运维、D会员车队、E结算票据分区，共享统一关系库。读数、费用分段、备件及双方意见分别以多行表示，不在单一字符串堆放重复条目。","",
"- PK为声明主键，UK为唯一约束，FK为真实物理外键。可空唯一列仅约束非空值，不自动成为全关系候选键；复合PK也不一定最小，月结明细的order_id本身唯一才是其最小候选键。",
"- NULL表示尚未产生、未知或不适用，与0不同。金额为人民币元，电量kWh、功率kW、SOC百分比。服务费单位依赖计费模式。",
"- datetime(6)本身不含时区；连接按北京时间+08:00运行。本文件用北京时间解释时刻，不能把DATETIME误写成带时区类型。账期日期取月份首日。",
"- 金额使用DECIMAL并按分核算。tinyint(1)是布尔惯例类型，本身不禁止其他整数；API/过程按0/1使用，未设CHECK时不伪称有0/1数据库约束。",
"- 逐列范围栏列出实际涉及该列的CHECK。跨行互斥、资金冻结、生命周期、累计额度、票据冻结由过程/触发器/事务保证，不能只用单列CHECK代替。",
"- telemetry分区设计使用触发器验证桩；外账和差异允许平台未知订单号。这些逻辑关系不能伪标为物理FK。","",
"## 2. 关系模式与表目录","",
"| 分区 | 物理表 | 中文对象 | 字段数 | 职责 |","|---|---|---|---:|---|",
]
    ordered=list(TABLE_INFO)
    for table in ordered:
        title,area,summary=TABLE_INFO[table]
        lines.append(f"| {area} | {code(table)} | {title} | {len(columns[table])} | {summary} |")
    lines+=["","## 3. 逐表关系模式、字段字典与完整性",""]
    declared_columns=0
    for i,table in enumerate(ordered,1):
        title,area,summary=TABLE_INFO[table]
        cs=columns[table]; m=model["tables"][table]; rows=constraints[table]
        checks=[clean_check(r["检查表达式"]) for r in rows if r["约束类型"]=="CHECK"]
        group=defaultdict(list)
        for r in rows: group[(r["约束类型"],r["约束名"])].append(r)
        pk=m["pk"]
        assert pk==[r["字段"] for r in group.get(("PRIMARY KEY","PRIMARY"),[])],f"PK mismatch {table}"
        fks=[(k,rs) for k,rs in group.items() if k[0]=="FOREIGN KEY"]
        uks=[(k,rs) for k,rs in group.items() if k[0]=="UNIQUE"]
        expected={(r["COLUMN_NAME"],r["REFERENCED_TABLE_NAME"],r["REFERENCED_COLUMN_NAME"]) for r in metadata["foreign_keys"] if r["TABLE_NAME"]==table}
        actual={(r["字段"],r["引用表"],r["引用字段"]) for _,rs in fks for r in rs}
        assert expected==actual,f"FK mismatch {table}: {expected ^ actual}"
        lines += [f"### 3.{i} {title} — {code(table)}","",summary,"",
        "关系模式："+code(table+"("+", ".join(c["COLUMN_NAME"] for c in cs)+")")+"。","",
        "**主键**："+code("("+", ".join(pk)+")")+"。"]
        lines.append("**唯一约束**："+("；".join(code(k[1])+": "+code("("+", ".join(r["字段"] for r in rs)+")") for k,rs in uks) if uks else "除主键外无其他声明唯一键")+"。")
        lines.append("**物理外键**："+("；".join(code(k[1])+": "+code("("+", ".join(r["字段"] for r in rs)+")")+" → "+code(rs[0]["引用表"]+"("+", ".join(r["引用字段"] for r in rs)+")") for k,rs in fks) if fks else "未声明物理FK，业务逻辑关联见下方说明")+"。")
        lines+=["","| 字段 | 真实类型 | 可空 | 默认/生成方式 | 中文语义 | 单位 | 键与检查范围 |","|---|---|---|---|---|---|---|"]
        for c in cs:
            name=c["COLUMN_NAME"]; ctype=c["COLUMN_TYPE"]; description=meaning(table,name)
            assert re.search("[\u4e00-\u9fff]",description),f"non-Chinese description {table}.{name}"
            nullable=c["IS_NULLABLE"]=="YES"; extra=c["EXTRA"]
            if "GENERATED" in extra.upper(): default="存储生成列（"+extra+"）"
            elif "auto_increment" in extra: default="自增"
            elif c["COLUMN_DEFAULT"] is None: default="NULL" if nullable else "无默认，插入提供/触发器填写"
            else: default=str(c["COLUMN_DEFAULT"])
            notes=[]
            if name in pk: notes.append("PK")
            for k,rs in uks:
                if name in [r["字段"] for r in rs]: notes.append("UK"+("（组合）" if len(rs)>1 else "")+": "+k[1])
            for k,rs in fks:
                for r in rs:
                    if r["字段"]==name: notes.append("FK"+("（组合）" if len(rs)>1 else "")+"→"+r["引用表"]+"."+r["引用字段"])
            matching=[expr for expr in checks if chr(96)+name+chr(96) in expr]
            for expr in matching: notes.append("CHECK "+expr)
            if not matching:
                match=re.fullmatch(r"varchar\((\d+)\)",ctype)
                if match: notes.append("最长"+match.group(1)+"字符；无额外列CHECK")
                elif ctype.startswith("decimal"): notes.append("声明精度；无额外列CHECK")
                else: notes.append("无额外列CHECK")
            lines.append("| "+" | ".join(cell(x) for x in [code(name),code(ctype),"是" if nullable else "否",code(default),description,unit(table,name,ctype),"<br>".join(notes)])+" |")
            declared_columns+=1
        lines+=["","**主要函数依赖与规范化**："+code("("+", ".join(pk)+")")+" → 本表其余字段。"+FD_NOTES.get(table,"除声明候选键决定本对象属性外，当前业务语义没有另行确认的非键决定非键依赖；关联对象的名称和配置保存在各自主表，不重复复制。"),""]
        if table in EXTRA_RULES: lines+=["**跨字段、跨行及生命周期规则**："+EXTRA_RULES[table],""]
        ix=defaultdict(list)
        for r in indexes[table]: ix[r["索引名"]].append(r)
        normal=[(k,rs) for k,rs in ix.items() if rs[0].get("非唯一")=="1"]
        if normal:
            lines+=["**普通索引**："+"；".join(code(k)+": "+code("("+", ".join(r["字段"] for r in sorted(rs,key=lambda r:int(r["列顺序"])))+")") for k,rs in normal)+"。",""]
        lines+=["SQL来源："+code(m["source"])+f"（建表起始行{m['line']}，并包含后续ALTER新增列）。",""]
    assert declared_columns==320
    lines+=["## 4. 联系与FK边界","",
"运营商1:N场站，场站1:N桩，桩1:N枪；账号与车辆通过有效期绑定；订单引用账号、车辆、枪、费率及可选车队卡。订单1:N读数/费用/付款，付款1:N退款；活动1:N券，核销使券与订单至多一对一；桩1:N告警，告警1:N工单，工单1:N备件。结算单1:N明细/差异/调整/票据，差异与整单分别保存平台及运营商两方记录。用户申请1:N实际蓝红票。","",
"这是最大基数，不保证父记录已经存在子记录，不表示生命周期可由FK表达。结构快照含"+str(len(foreign_groups))+"组物理FK约束、"+str(len(metadata["foreign_keys"]))+"条外键列映射。复合FK按组解释，不能把每个列映射都数成独立联系；图件还包含逻辑关联，关联数不必与物理FK组数相等。","",
"## 5. 范式论证与有意冗余","",
"**1NF。** 每关系有确定行标识，普通列保存单一标量；订单分段、采样、备件和双方意见独立成行。asset_request.payload为JSON半结构申请载荷，不承担需要FK关联的核心对象列表；不能据此声称其内部每个成员都已逐列规范化。","",
"**2NF。** 读数(order_id,sampled_at)、分时费率(tariff_id,minute_from)、费用分段(order_id,begins)、备件(work_id,part)、差异意见(diff_id,side)、整单签字(settlement_id,side)等关系，基础事实依赖完整最小组合键。单列候选键关系不存在对该键真子集的依赖。settlement_item虽声明复合PK，但order_id为UNIQUE NOT NULL且是最小候选键，不能只看复合PK就判其存在部分依赖。","",
"**3NF核心分解。** 运营商名称只放operator、场站地址只放station、车辆参数只放vehicle、活动条件只放campaign、分时费率只放tariff_band、告警规则只放alarm_rule；关联事实引用编号，避免把名称、地址、可变配置复制到每条业务记录。按已确认依赖，这些核心主数据及纯关联事实符合非键属性不经非超键属性传递依赖候选键的3NF目标。","",
"**不把44张物理表一概宣称严格3NF。** external_bill中settlement_id→batch是对复合PK真子集的部分依赖（因此连严格2NF也不满足）；consumer_invoice中id→request_id→order_id是可识别的传递依赖。订单费率归属、分段派生金额等也需说明。历史快照或跨表汇总本身不自动等于违反3NF：必须识别本关系内非超键决定非主属性的函数依赖；例如账户冻结额跨表聚合主要是更新一致性问题，不能单凭“汇总”二字判其不符合3NF。受控冗余的理由与维护规则如下：","",
"| 位置 | 保留原因 | 维护与保护 |","|---|---|---|",
"| 订单station_id/operator_id、预算月及费率引用 | 固定交易时归属；当前设施关系会变化 | 开单触发器填写并禁止篡改，不从当前枪归属覆盖旧单 |",
"| account.reserved_balance、fleet_card.reserved_amount、订单hold | 并发开单时原子保留资金，减少反复扫描 | 行锁、订单触发器、额度边界、付款或取消释放；冻结不等于扣款 |",
"| refund.debt_reduction | 分离退现金与免除债权，便于净应付和结算逆冲 | kind/amount/debt_reduction的CHECK；撤销收款为0，减价退款等于amount |",
"| 费用分段单价、金额、estimated及订单gross | 保留历史核价、舍入、插值、最低费与人工调整 | 已用费率不可改，人工复核留痕，不按当前价格重算旧单 |",
"| 告警severity/deadline、设施状态历史 | 当前规则和设备状态会改变，事件证据需保留 | 触发时复制，独立升级，恢复不倒写原事实 |",
"| 月结原客户金额/分成、调整分量及amount | 冻结月结并精确逆冲跨期退款 | 首结唯一、退款来源唯一、累计舍入差额，确认后冻结 |",
"| external_bill.batch | settlement_id部分决定batch，但需要复合FK核对批次 | 一单一完整批次、声明行数、整批重置，不逐行掩盖差异 |",
"| 差异两侧快照/delta/建议额/一致结论 | 保留双方当时看到的证据 | 完整批次生成，双方意见分开，改变意见使整单签字失效 |",
"| 用户票order_id/title、票据金额和原票引用 | 保留签发票面和全额红冲证据 | 净票额限额、唯一红冲、不允许更新/删除，申请状态不是票据 |",
"| 活动标识及告警范围存储生成列 | 实现带状态条件的唯一性 | 由数据库生成表达式和唯一索引维护，应用不能另写不同值 |","",
"v_order_balance、v_settlement、v_invoice_balance、v_recon_expected等总额由视图计算，不另存一份可随意修改的合计。资金冻结余额属于有意物化汇总，必须与订单/流水一致；它与历史快照的维护目的不同。","",
"## 6. 离线生成与核对","",
"支持脚本：[生成数据字典.py](生成数据字典.py)。脚本只读结构JSON、图件模型和结构CSV，不导入deploy/app，不连接数据库，不读取seed或业务数据。320字段都要求显式中文解释，缺项、主外键不一致或数量变化即停止生成，不用英文列名回填掩盖缺项。第二版仅在本目录生成字典；运行记录统一保存在第二版过程文件/本次整合。","",
"本版核对：44张基表均有说明，320字段均有中文语义、单位、类型、可空及默认信息；每表PK及77条FK列映射与导出约束匹配；CHECK直接取实际约束表达式。未声明的检查范围明确标注，视图字段未混入基表。本文件不替代真实集成、资金、结算、并发验收日志。",
]
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Generated {OUTPUT.name}: {len(tables)} tables, {declared_columns} columns, {len(foreign_groups)} FK groups/{len(metadata['foreign_keys'])} FK mappings.")

if __name__=="__main__":
    generate()

# E 结算与对账

本目录负责“账期应结多少、外部账单是否一致、双方是否分别确认，以及票据如何留痕”。

| 文件 | 作用 |
|---|---|
| [08_settlement.sql](08_settlement.sql) | 结算快照、账期调整、完整外账批次、差异、双方意见与整单签字、消费/结算票据及红冲 |
| [queries.sql](queries.sql) | 运营商账期应结与差异、未决意见、可开票额度的三对等价查询 |
| [audit_queries.sql](audit_queries.sql) | 用于核对结算和资金关系的补充审计查询，按具体SQL阅读结果 |

主要表为`settlement`、`settlement_item`、`settlement_import`、`external_bill`、`recon_diff`、`diff_confirmation`、`settlement_confirmation`、`settlement_adjustment`、`settlement_invoice`、`consumer_invoice`。

## 正确使用顺序

1. A/B/C/D依赖就绪后，按[全局顺序](../README.md)执行`08_settlement.sql`。
2. 先生成指定场站和账期的平台快照；外账按完整批次导入，不能只挑金额相同的几笔当作对账完成。
3. 按差异逐条保留平台与运营商各自意见；未决差异和不完整批次不能跳过。整单也需不同真实角色分别签字，单方签署仍为草稿。
4. 已确认快照受到冻结保护。草稿外账纠错可经受控重置入口清理批次、差异意见及签字，再重新完整导入；它不会删除原平台计费事实。
5. 消费票和运营商结算票分别依各自额度签发；红冲保留原票关系，不删除或直接覆盖已签票据。跨期退款通过后续调整保留原账期快照。

`v_settlement`本身由结算单、快照明细和调整汇总组成；讲解三关系以上查询时应同时展示视图展开，不能仅统计顶层JOIN个数。

DDL需要管理权限；平台结算与运营商只查询或确认授权范围的数据。备份策略、演练文件和恢复工具统一在`05_备份与恢复`，测试证据在`04_测试与验收`。

# 备份与恢复：策略、样例与演练工具

- `备份恢复策略.md`说明全量/binlog周期、留存、RPO/RTO、敏感密钥和恢复演练。
- `历史全量样例_20261114`是本机留存的恢复演练资料，GitHub 版本提供策略与演练工具。
- `工具/backup_validate.py`是现行全量备份＋新隔离库恢复验证入口。不会删除主库，也不会覆盖任何已有恢复库。

## 显式演练

管理员需在当前进程提供`CHARGE_ADMIN_DSN`，指向本机3307的charge_course_20261114，并有备份、CREATE DATABASE、例程/触发器恢复及必要全局参数权限。运行命令不在文档中包含实际密码：

```powershell
.\01_平台工程\.venv\Scripts\python.exe .\05_备份与恢复\工具\backup_validate.py --target charge_course_restore_v2_example --mysql-bin "C:\Program Files\MySQL\MySQL Server 8.4\bin"
```

`--target`必填，必须是尚未存在的新库名且不能等于主库。上例名字已经使用时，另取新名字，工具拒绝覆盖而不是先删库。MySQL工具目录也可由`CHARGE_MYSQL_BIN`指定。

工具输出在`过程文件/本次整合/备份恢复/时间戳`，包含备份、只改库标识符的恢复SQL、binlog坐标和逐表内容SHA-256/对象集合核验。失败的新隔离库保留供排查，不能自动清空或删除原库。

**本工具只演练全量恢复。** binlog时间点重放、连续归档、自动周期调度、异机密钥恢复仍需单独实施与验证。RPO/RTO为设计目标，不把一次小样本全量恢复时间当作长期运维保证。

SQL备份与PII密钥分开保管；当前DPAPI配置只对当前Windows用户有效。不要把root密码或解密密钥写入SQL、截图、日志或共享说明。

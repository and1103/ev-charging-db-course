# 数据库部署与独立空库复现工具

| 入口 | 做什么 | 权限与影响 |
|---|---|---|
| [deploy_local.py](deploy_local.py) | 调用平台部署器，按九个迁移建立对象；可用`--demo`加载基础样例；临时调整例程创建设置后在finally恢复 | 目标库DDL及相应系统变量管理权限；会写对象与版本记录 |
| [verify_clean_build.py](verify_clean_build.py) | 在明确命名的新隔离库中执行完整结构、三阶段样例及对象/数据量核验 | 管理员权限；不得覆盖已存在的库，详细参数以`--help`为准 |
| [平台deploy.py](../../01_平台工程/deploy.py) | SQL解析、迁移ID、执行顺序及统一连接工厂，供部署和测试工具复用 | 是共用实现，不是第二套SQL来源 |

## 已有库与新库分开使用

本机现有主库`charge_course_20261114`已经完成部署。启动网页、读图、查字典、查看已有记录，都不需要重新建库。

## 给组员的交互式管理员入口

首次安装MySQL 8.4并准备3307端口→根目录“安装环境.cmd”→按01说明运行configure创建全新空库及本机配置→再在第二版根目录执行：

```powershell
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\admin_run.py init
```

按提示输入本机MySQL root密码，不会回显或写入文件。该入口只接受尚无对象的目标课设库，依次执行DDL＋基础样例、扩展样例、车队样例；已有表/视图、例程、触发器或事件都会拒绝，不清空原库。完成后再双击“启动平台.cmd”。连接已部署库的组员应使用connect-existing，不执行init。

同一个临时管理员入口还支持以下明确任务：

```powershell
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\admin_run.py schema
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\admin_run.py sql-regression
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\admin_run.py explain
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\admin_run.py clean-build --target charge_course_verify_newname
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\admin_run.py backup-restore --target charge_course_restore_newname
```

新目标名必须实际不存在；上面newname只是示例，按本次演练命名。恢复工具可附加`--mysql-bin`指定MySQL 8.4 bin目录。管理员口令仅用于本次进程，不恢复已删除的数据库控制台展示。

schema使用管理员只读核对完整对象清单，包含应用账号通常不可见的触发器元数据。日常快速检查仍使用应用账号，不为方便导出而扩大网页账号权限。

## 已有管理员环境变量的高级用法

`CHARGE_ADMIN_DSN`格式为`mysql+pymysql://root:<URL编码的密码>@127.0.0.1:3307/<目标库>?charset=utf8mb4`。密码特殊字符需要URL编码，不应把真实连接串写进共享代码、报告或命令历史；普通组员优先使用上面的交互式入口。

需要重现时，先由管理员创建并明确选定一个新的空库，在自己的本地会话设置`CHARGE_ADMIN_DSN`。该连接应指向新库而非现有主库，口令不写入README或代码。首次合成账号还需要有效的演示密码配置（至少10字符）；当前Windows用户的受保护配置可提供相关密钥，跨电脑需单独配置。

在第二版根目录运行：

```powershell
.\01_平台工程\.venv\Scripts\python.exe .\02_数据库脚本\部署工具\deploy_local.py --demo
```

该命令先做全部九个结构迁移，再加载基础`seed.sql`。随后按[样例说明](../初始化与样例/README.md)执行`seed_extended.py`、`seed_fleet.py`。

`--through 1`至`--through 9`用于明确的分阶段DDL检查；`--demo`必须完成全部九个迁移。迁移ID保留旧版名称，不随文件夹改名改变。`charge_migration`是部署控制表，不计入44张业务表。

## 运行约束

- 普通网页应用账号不具备建表/创建例程和修改系统变量的管理权限；不要将应用连接冒充管理员连接。
- 版本记录只表示相应脚本已被登记，不自动修复手工修改造成的结构漂移。遇到同名表、缺版本、权限失败时应停止并核对，不通过清空库或删版本记录重跑解决。
- MySQL DDL存在隐式提交。中途失败不能以一次ROLLBACK当作全部还原；保留新验证库供排查，勿改动旧库。
- `09_roles.sql`另由DBA选定目标库后处理，结构迁移不会自动把数据库角色授予其他登录账号。
- 历史空库构建结果与新一轮执行结果分别保留日期；不能把文件复制成功当作已经重新部署或已经重新验证所有SQL。

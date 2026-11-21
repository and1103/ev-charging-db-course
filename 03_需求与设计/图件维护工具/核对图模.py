"""Compare generated diagram inventory against an existing MySQL metadata export.

Read-only: does not execute application code or connect to the database.
"""
from pathlib import Path
import json
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0, str(ROOT / '01_平台工程'))
from project_paths import DESIGN_ROOT, SQL_ROOT
PROCESS=DESIGN_ROOT
model=json.loads((HERE/'模型清单.json').read_text(encoding='utf-8'))
export=DESIGN_ROOT/'模型与数据字典/数据库结构快照.json'
actual=json.loads(export.read_text(encoding='utf-8'))
tables=set(actual['tables'])-{'charge_migration'}
expected=set(model['tables'])
issues=[]
if tables!=expected: issues.append({'category':'tables','only_diagram':sorted(expected-tables),'only_database':sorted(tables-expected)})
dbcols={(r['TABLE_NAME'],r['COLUMN_NAME']):r for r in actual['columns'] if r['TABLE_NAME'] in tables}
graphcols={(n,c['name']):c for n,t in model['tables'].items() for c in t['columns']}
if set(dbcols)!=set(graphcols): issues.append({'category':'columns','only_diagram':sorted(set(graphcols)-set(dbcols)),'only_database':sorted(set(dbcols)-set(graphcols))})
dbpk={(r['TABLE_NAME'],r['COLUMN_NAME']) for r in actual['columns'] if r['TABLE_NAME'] in tables and r['COLUMN_KEY']=='PRI'}
graphpk={(n,c) for n,t in model['tables'].items() for c in t['pk']}
if dbpk!=graphpk: issues.append({'category':'primary_keys','only_diagram':sorted(graphpk-dbpk),'only_database':sorted(dbpk-graphpk)})
dbfk={(r['TABLE_NAME'],r['COLUMN_NAME'],r['REFERENCED_TABLE_NAME'],r['REFERENCED_COLUMN_NAME']) for r in actual['foreign_keys'] if r['TABLE_NAME'] in tables}
graphfk={(f['child'],a,f['parent'],b) for f in model['relationships'] if f['kind']=='physical' for a,b in zip(f['columns'],f['references'])}
if dbfk!=graphfk: issues.append({'category':'foreign_keys','only_diagram':sorted(graphfk-dbfk),'only_database':sorted(dbfk-graphfk)})
for key,c in graphcols.items():
 if key not in dbcols: continue
 required=c['required'] or key in graphpk
 if required!=(dbcols[key]['IS_NULLABLE']=='NO'): issues.append({'category':'nullability','column':key,'diagram_required':required,'database':dbcols[key]['IS_NULLABLE']})
 def normalize_type(s):
  s=s.lower().replace('numeric','decimal').replace('integer','int')
  return 'tinyint(1)' if s=='boolean' else s
 if normalize_type(c['type'])!=normalize_type(dbcols[key]['COLUMN_TYPE']): issues.append({'category':'column_type','column':key,'diagram':c['type'],'database':dbcols[key]['COLUMN_TYPE']})
# Compare object names as well; only source SQL in business module folders counts.
ddl_routines=set(); ddl_triggers=set()
for path in SQL_ROOT.rglob('*.sql'):
 if path.relative_to(SQL_ROOT).parts[0].split('_',1)[0] not in {'A','B','C','D','E'}: continue
 if path.name in {'seed.sql','smoke.sql','queries.sql','09_roles.sql'} or path.name.startswith('regression_'): continue
 sql=re.sub(r'/\*[\s\S]*?\*/|--[^\n]*','',path.read_text(encoding='utf-8-sig'))
 ddl_routines.update((name,kind.upper()) for kind,name in re.findall(r'CREATE\s+(FUNCTION|PROCEDURE)\s+(\w+)\s*\(',sql,re.I))
 ddl_triggers.update(re.findall(r'CREATE\s+TRIGGER\s+(\w+)',sql,re.I))
db_routines={(r['ROUTINE_NAME'],r['ROUTINE_TYPE'].upper()) for r in actual.get('routines',[])}
db_triggers=set(actual.get('triggers',[]))
if ddl_routines!=db_routines: issues.append({'category':'routines','only_diagram_source':sorted(ddl_routines-db_routines),'only_database':sorted(db_routines-ddl_routines)})
if ddl_triggers!=db_triggers: issues.append({'category':'triggers','only_diagram_source':sorted(ddl_triggers-db_triggers),'only_database':sorted(db_triggers-ddl_triggers)})
result={'database_metadata_source':str(export.relative_to(ROOT)),'table_count':len(tables),'column_count':len(dbcols),'physical_fk_column_pairs':len(dbfk),'physical_fk_relationships':sum(f['kind']=='physical' for f in model['relationships']),'logical_relationships':sum(f['kind']=='logical' for f in model['relationships']),'routine_count':len(db_routines),'trigger_count':len(db_triggers),'passed':not issues,'issues':issues}
(HERE/'图模数据库一致性.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
index=PROCESS/'图件索引.md'
text=re.sub(r'\n## 与实库元数据核对[\s\S]*$','',index.read_text(encoding='utf-8'))
text+='\n## 与实库元数据核对\n\n'
text+=f"读取已有的 `模型与数据字典/数据库结构快照.json`，逐项比对业务表集合、字段集合、主键、必填性及物理外键列对。结果：{'通过' if not issues else '存在差异'}；{len(tables)} 张业务表、{len(dbcols)} 个表字段、{len(dbfk)} 对物理外键列。{result['physical_fk_relationships']} 条物理关系之外的 {result['logical_relationships']} 条逻辑关联均以虚线单独标明。\n\n"
text+=f"同时核对业务 SQL 的例程名称/类型及触发器名称：{len(db_routines)} 个例程、{len(db_triggers)} 个触发器，与元数据一致。\n\n" if not issues else ''
text+='核对依据、问题清单见 [图模数据库一致性.json](图件维护工具/图模数据库一致性.json)，可运行 `图件维护工具/核对图模.py` 复核；此脚本只读元数据导出，不连接数据库。该结构核对不替代业务、并发或权限测试。\n'
index.write_text(text,encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
if issues: raise SystemExit(1)

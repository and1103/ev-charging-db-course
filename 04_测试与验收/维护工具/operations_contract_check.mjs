// Pure client-side protocol checks; this does not write to MySQL or drive a browser.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

import path from 'node:path';
import {fileURLToPath} from 'node:url';
const projectRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const output=process.env.CHARGE_TEST_OUTPUT || path.join(projectRoot,'过程文件/本次整合/验证结果/手动客户端检查');
fs.mkdirSync(output,{recursive:true});
const modulePath=path.join(projectRoot,'01_平台工程/static/js/operations.js');
const source=fs.readFileSync(modulePath,'utf8').replace(/^import .*;\r?$/gm,'').replace(/^export /gm,'');
const {csvRows,periodLabel,beijingInput,nowLocal}=vm.runInNewContext(source+'\n;({csvRows,periodLabel,beijingInput,nowLocal})',{}, {timeout:1000});
const header='order_id,kwh,amount,paid';
const cases=[];
const check=(name,fn)=>{try{fn();cases.push({name,passed:true});}catch(error){cases.push({name,passed:false,error:error.message});}};
const rejects=(text)=>assert.throws(()=>csvRows(text));
check('ordinary CSV and strict boolean strings',()=>assert.equal(csvRows(header+'\n11,2.0000,3.20,true')[0].amount,'3.20'));
check('quoted headers and CRLF data',()=>assert.equal(csvRows('"order_id","kwh","amount","paid"\r\n"11","2.0000","3.20","true"\r\n').length,1));
check('UTF8 BOM header is accepted',()=>assert.equal(csvRows('\uFEFF'+header+'\n11,2,3.2,true').length,1));
check('bare blank lines are ignored',()=>assert.equal(csvRows(header+'\n\n11,2,3.2,true\n\n').length,1));
check('empty comma-delimited row is rejected instead of silently omitted',()=>rejects(header+'\n,,,\n11,2,3.2,true'));
check('duplicate order in a batch is rejected',()=>rejects(header+'\n11,2,3.2,true\n11,2,3.2,true'));
check('capitalized paid boolean is rejected',()=>rejects(header+'\n11,2,3.2,True'));
check('hexadecimal value rejected before backend Decimal conversion',()=>rejects(header+'\n11,0x20,3.2,true'));
check('negative energy is rejected',()=>rejects(header+'\n11,-1,3.2,true'));
check('duplicate header is rejected',()=>rejects(header+',paid\n11,2,3.2,true,true'));
check('unclosed quote is rejected',()=>rejects(header+'\n11,"2,3.2,true'));
check('characters after a closing quote are rejected',()=>rejects(header+'\n11,"2"x,3.2,true'));
check('more than 10000 rows is rejected',()=>rejects(header+'\n'+Array.from({length:10001},(_,i)=>`${i+1},2,3.2,true`).join('\n')));
check('ISO month remains the exact accounting month',()=>assert.equal(periodLabel('2026-11-01'),'2026-11'));
check('input datetime explicitly carries Beijing offset',()=>assert.equal(beijingInput('2026-11-16T12:30'),'2026-11-16T12:30+08:00'));
check('server timestamp is converted to Beijing input time',()=>assert.equal(nowLocal('2026-11-16T04:30:00Z'),'2026-11-16T12:30:00'));
const report={checked_at:new Date().toISOString(),scope:'Pure client-side CSV and timezone contract checks; not browser E2E or MySQL mutation tests.',source:'static/js/operations.js',test_count:cases.length,passed:cases.every(x=>x.passed),cases};
fs.writeFileSync(path.join(output,'operations_contract_result.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({test_count:report.test_count,passed:report.passed,scope:report.scope}));
if(!report.passed){console.log(JSON.stringify(cases.filter(x=>!x.passed)));process.exitCode=1;}

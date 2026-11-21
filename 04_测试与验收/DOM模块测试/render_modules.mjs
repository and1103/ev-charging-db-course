// Pure local DOM integration. No browser, network navigation or HTML scripts.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {JSDOM} from 'jsdom';
import {createHash} from 'node:crypto';

const here=path.dirname(fileURLToPath(import.meta.url));
const projectRoot=path.resolve(here,'../..');
const rootPath=path.join(projectRoot,'01_平台工程');
const output=process.env.CHARGE_TEST_OUTPUT || path.join(projectRoot,'过程文件/本次整合/验证结果/手动DOM检查');
fs.mkdirSync(output,{recursive:true});
const fixtures=JSON.parse(fs.readFileSync(path.join(output,'api_fixtures.json'),'utf8'));
const normalize=value=>{const u=new URL(value,'http://local-dom-test.invalid');u.searchParams.sort();return u.pathname+(u.search?u.search:'');};
const report={checked_at:new Date().toISOString(),mode:'jsdom code-only DOM; local modules and captured Flask responses; no browser or external network',html_scripts:'Not executed; jsdom uses default script-disabled mode',cases:[],limits:['Does not prove browser layout, native interactions, browser policy, real HTTP or end-to-end transactions.','Fixtures are snapshots; synthetic state variants test rendering branches only, not database rules.']};
let roleData,overrides,requests,errors,currentWindow;
function setup(data,hash,html='<!doctype html><html lang="zh-CN"><body><main id="root"></main><div id="toast-region"></div></body></html>',pathname='/ui/'){
  if(currentWindow)currentWindow.close();
  const dom=new JSDOM(html,{url:'http://local-dom-test.invalid'+pathname+'#'+hash});
  currentWindow=dom.window;
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,Node:dom.window.Node,location:dom.window.location,Event:dom.window.Event,FormData:dom.window.FormData,sessionStorage:dom.window.sessionStorage});
  errors=[];requests=[];roleData=data;overrides=new Map();
  dom.window.addEventListener('error',event=>errors.push(event.error?.message||event.message));
  globalThis.fetch=async(input,options={})=>{
    const method=(options.method||'GET').toUpperCase();
    if(method!=='GET')throw new Error('DOM_RENDER_TEST_REFUSED_WRITE:'+method);
    const key=normalize(String(input));requests.push(key);
    const fixture=overrides.get(key)||roleData.responses[key];
    if(!fixture)throw new Error('UNEXPECTED_LOCAL_FIXTURE_REQUEST:'+key);
    return new Response(JSON.stringify(fixture.body),{status:fixture.status,headers:{'Content-Type':'application/json'}});
  };
  return dom.window.document.getElementById('root');
}

setup(Object.values(fixtures.roles)[0],'initial');
const core=await import(pathToFileURL(path.join(rootPath,'static/js/core.js')).href);
const modules=await Promise.all(['assets','orders','members','operations'].map(name=>import(pathToFileURL(path.join(rootPath,`static/js/${name}.js`)).href)));
const exports=Object.assign({},...modules);

async function run(role,spec,mutate){
  const data=fixtures.roles[role];
  const root=setup(data,`${spec.export}?${spec.params||''}`);
  core.state.session=data.user;core.state.csrfToken='local-code-test-token';core.state.serverTime=data.responses['/ui/session'].body.server_time;
  let error;
  try{
    if(mutate)mutate();
    await exports[spec.export]({root,user:data.user,params:new URLSearchParams(spec.params||'')});
    const text=root.textContent;
    if(!root.querySelector('h2'))throw new Error('No content heading rendered');
    if(/\bundefined\b|\bNaN\b|\[object Object\]/.test(text))throw new Error('Invalid value escaped into visible content');
    if(errors.length)throw new Error(errors.join(';'));
  }catch(e){error=String(e.message||e);}
  const record={role,label:spec.label,export:spec.export,params:spec.params||'',source_mode:spec.source_mode,passed:!error,headings:root.querySelectorAll('h2').length,tables:root.querySelectorAll('table').length,forms:root.querySelectorAll('form').length,buttons:root.querySelectorAll('button').length,fetch_requests:requests};
  if(error)record.error=error;
  report.cases.push(record);
  console.log(`${record.passed?'PASS':'FAIL'} ${role} ${spec.label}${error?' '+error:''}`);
}
for(const [role,data]of Object.entries(fixtures.roles))for(const spec of data.cases)await run(role,spec);

// Explicitly marked local variants cover action-form branches absent in the seed snapshot.
for(const role of ['driver','admin','fleet']){
  const data=fixtures.roles[role];
  const detailEntry=Object.entries(data.responses).find(([key,value])=>/^\/ui\/api\/orders\/\d+$/.test(key)&&value.body.order);
  if(!detailEntry)continue;
  for(const status of (role==='fleet'?['charging']:['billed','charging','review'])){
    const [key,fixture]=detailEntry;
    const spec={export:'renderOrders',params:`id=${fixture.body.order.id}`,label:`合成DOM分支-${status}`,source_mode:'synthetic_state_variant'};
    await run(role,spec,()=>{
      const changed=structuredClone(fixture);
      Object.assign(changed.body.order,{state:status,outstanding:'9.40',received:'0.00',discount:'0.00',stop_requested_at:null});
      changed.body.payments=[];changed.body.requests=[];changed.body.invoices=[];
      overrides.set(key,changed);
    });
  }
}
const expectedNavigation={
  driver:['dashboard','stations','queue','orders','members','tariffs'],
  admin:['dashboard','stations','orders','facilities','monitor','members','fleet','settlements','invoices','tariffs','demo'],
  maintenance:['dashboard','monitor'],
  settlement:['dashboard','orders','settlements','invoices','tariffs'],
  operator:['dashboard','settlements','tariffs'],
  fleet:['dashboard','orders','fleet','tariffs']
};
for(const [role,data] of Object.entries(fixtures.roles)){
  setup(data,'dashboard',data.workspace_html);
  let error;
  try{
    await import(pathToFileURL(path.join(rootPath,'static/js/app.js')).href+'?localDomCase='+role);
    const actual=[...document.querySelectorAll('.nav-item')].map(x=>x.dataset.page);
    if(JSON.stringify([...actual].sort())!==JSON.stringify([...expectedNavigation[role]].sort()))throw new Error('Role navigation mismatch: '+actual.join(','));
    if(!document.querySelector('#page-title')?.textContent.trim())throw new Error('Missing workspace page title');
    if(!document.querySelector('#view-content .stat-card'))throw new Error('Dashboard metrics were not rendered');
    if(document.querySelector('#view-content .notice.error'))throw new Error(document.querySelector('#view-content .notice.error').textContent);
    if(/\bundefined\b|\bNaN\b|\[object Object\]/.test(document.body.textContent))throw new Error('Invalid visible value');
    if(errors.length)throw new Error(errors.join(';'));
  }catch(e){error=String(e.message||e);}
  const record={role,label:'主应用启动、权限导航与总览',export:'app.js startup',source_mode:'actual_html_api_snapshot',passed:!error,navigation:[...document.querySelectorAll('.nav-item')].map(x=>x.dataset.page),dashboard_cards:document.querySelectorAll('#view-content .stat-card').length,fetch_requests:requests};
  if(error)record.error=error;
  report.cases.push(record);console.log(`${record.passed?'PASS':'FAIL'} ${role} app.js startup${error?' '+error:''}`);
}
{
  setup(fixtures.anonymous,'',fixtures.anonymous.login_html,'/ui/login');
  let error;
  try{
    await import(pathToFileURL(path.join(rootPath,'static/js/login.js')).href+'?localDomCase=anonymous');
    const password=()=>document.querySelector('#login-form input[name="password"]');
    if(password()?.type!=='password'||password().autocomplete!=='current-password')throw new Error('Anonymous login password field contract failed');
    if(document.querySelector('#login-form input[name="phone"]'))throw new Error('Phone field leaked into login mode');
    document.getElementById('switch-auth').click();
    if(!document.querySelector('#login-form input[name="phone"]')||password()?.type!=='password'||password().autocomplete!=='new-password')throw new Error('Registration toggle field contract failed');
    if(!document.getElementById('login-title').textContent.includes('注册'))throw new Error('Registration title missing');
    document.getElementById('switch-auth').click();
    if(document.querySelector('#login-form input[name="phone"]')||password()?.autocomplete!=='current-password')throw new Error('Return to login failed');
    if(errors.length)throw new Error(errors.join(';'));
  }catch(e){error=String(e.message||e);}
  const record={role:'anonymous',label:'匿名登录与注册切换',export:'login.js startup',source_mode:'actual_html_api_snapshot',passed:!error,fetch_requests:requests};
  if(error)record.error=error;
  report.cases.push(record);console.log(`${record.passed?'PASS':'FAIL'} anonymous login.js startup${error?' '+error:''}`);
}
report.passed=report.cases.every(x=>x.passed);
report.case_count=report.cases.length;
report.actual_snapshot_cases=report.cases.filter(x=>x.source_mode==='actual_api_snapshot').length;
report.synthetic_variant_cases=report.cases.filter(x=>x.source_mode==='synthetic_state_variant').length;
report.entrypoint_cases=report.cases.filter(x=>x.source_mode==='actual_html_api_snapshot').length;
report.exports_covered=[...new Set(report.cases.filter(x=>x.source_mode!=='actual_html_api_snapshot').map(x=>x.export))];
report.entrypoints_covered=[...new Set(report.cases.filter(x=>x.source_mode==='actual_html_api_snapshot').map(x=>x.export))];
report.jsdom_version=JSON.parse(fs.readFileSync(path.join(here,'node_modules/jsdom/package.json'),'utf8')).version;
report.source_sha256=Object.fromEntries(['assets.js','orders.js','members.js','operations.js','core.js','app.js','login.js'].map(name=>[`static/js/${name}`,createHash('sha256').update(fs.readFileSync(path.join(rootPath,'static/js',name))).digest('hex')]));
fs.writeFileSync(path.join(output,'DOM模块集成结果.json'),JSON.stringify(report,null,2));
if(currentWindow)currentWindow.close();
console.log(JSON.stringify({passed:report.passed,case_count:report.case_count,exports:report.exports_covered.length,entrypoints:report.entrypoints_covered.length}));
if(!report.passed)process.exitCode=1;

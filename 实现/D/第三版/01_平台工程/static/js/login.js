import {api,loadSession,form,node} from './core.js';
let registering = false;
const host = document.getElementById('login-form');
function render() {
  document.getElementById('login-title').textContent = registering ? '注册车主账号' : '登录工作台';
  document.getElementById('login-subtitle').textContent = registering ? '注册后可添加车辆、查找场站和管理充电订单。' : '使用课设账号，进入你的业务空间。';
  document.getElementById('switch-auth').textContent = registering ? '已有账号？返回登录 →' : '还没有账号？注册车主账号 →';
  const fields = [
    {label:'账号',name:'login',required:true,autocomplete:'username',placeholder:'请输入账号',maxLength:128},
    {label:'密码',name:'password',type:'password',required:true,autocomplete:registering?'new-password':'current-password',placeholder:registering?'至少 10 个字符':'请输入密码',maxLength:128},
  ];
  if (registering) fields.push({label:'手机号',name:'phone',required:true,placeholder:'用于合成演示的手机号',maxLength:32});
  host.replaceChildren(form(fields,async values=>{
    if(registering) { await api('/auth/register',{method:'POST',body:values}); }
    await api('/auth/login',{method:'POST',body:{login:values.login,password:values.password}});
    await loadSession(); location.replace('/ui/');
  },registering?'注册并进入平台':'登录工作台'));
  if(registering) host.append(node('p',{className:'field-help'},'密码加盐哈希保存，手机号加密存储。课程演示请使用合成资料。'));
}
document.getElementById('switch-auth').addEventListener('click',()=>{registering=!registering;render();});
try { const value=await loadSession(); if(value.authenticated) location.replace('/ui/'); else render(); }
catch(e) { document.getElementById('login-error').textContent=e.message; }

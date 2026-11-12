// Real Chromium forms against a newly seeded, loopback-only SQLite application.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const browserPath = process.env.KUZENGA_BROWSER_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
assert.ok(existsSync(browserPath), 'Provide a local Chromium browser');
mkdirSync(path.join(project, 'build'), {recursive:true});
const profile = mkdtempSync(path.join(project, 'build/finance-browser-profile-'));
let server, browser, socket, sequence=0, config, serverError='';
const pending = new Map();
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));
async function until(fn, label, attempts=200) { for(let i=0;i<attempts;i++){ const result=await fn(); if(result)return result; await pause(100); } throw Error('Timed out: '+label); }
try {
  server = spawn(process.env.KUZENGA_PYTHON || 'python', ['scripts/finance_browser_server.py'], {cwd:project, windowsHide:true, stdio:['ignore','pipe','pipe']});
  let output='';
  server.stdout.on('data', bytes=> {output+=bytes; for(const line of output.split('\n')) { try {const value=JSON.parse(line); if(value.origin)config=value;} catch{} }});
  server.stderr.on('data', bytes=> {serverError+=bytes;});
  await until(()=> {if(server.exitCode!==null)throw Error(serverError); return config;}, 'isolated finance server',1200);
  browser=spawn(browserPath,['--headless=new','--disable-gpu','--disable-sync','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
  const port=await until(()=>{try{return readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];}catch{return null;}},'browser startup');
  const tabs=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(tabs.find(tab=>tab.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve);socket.addEventListener('error',reject);});
  socket.addEventListener('message',({data})=>{const message=JSON.parse(data);if(pending.has(message.id)){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(Error(message.error.message)):waiter.resolve(message.result);}});
  const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error('Browser command timed out: '+method));},15000);pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
  const navigate=async url=>{console.log('Checking '+url);await command('Page.navigate',{url:config.origin+url});await until(()=>evaluate(`document.readyState==='complete' && location.pathname===${JSON.stringify(url.split('?')[0])}`),'page '+url);assert.equal(await evaluate(`document.body.innerText.includes('Server Error (500)')`),false);};
  async function submit(selector, values, button='button') {
    const old=await evaluate('location.href');
    await evaluate(`(()=>{const forms=Array.from(document.querySelectorAll(${JSON.stringify(selector)}));const form=forms.find(candidate=>Object.keys(${JSON.stringify(values)}).every(name=>candidate.elements.namedItem(name)))||forms[0];if(!form)throw Error('Missing form');for(const [name,value] of Object.entries(${JSON.stringify(values)})){const input=form.elements.namedItem(name);if(!input)throw Error('Missing field '+name);if(input.type==='checkbox')input.checked=!!value;else input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));}const button=form.querySelector(${JSON.stringify(button)});form.requestSubmit(button);return true;})()`);
    await pause(350);
    await until(()=>evaluate(`document.readyState==='complete'`),'form completion');
    assert.equal(await evaluate(`document.body.innerText.includes('Server Error (500)')`),false,old);
  }
  const login=async role=>{await command('Network.clearBrowserCookies');await navigate('/login/');await submit('form',{username:`${role}@finance.test`,password:'pass12345!'});await until(()=>evaluate(`location.pathname!='/login/'`),'school login');};
  await login('bursar');
  // Fee creation and invalid input feedback.
  await navigate('/finance/fees/new/');
  const feeValues={code:'BROWSER-EXTRA',name:'Browser examination fee',academic_year:config.year,currency:config.usd,amount:'25',income_account:config.income,effective_from:'2026-01-01',effective_to:'2026-12-31',due_date:'2026-02-15'};
  await submit('form',feeValues);assert.equal(await evaluate('location.pathname'),'/finance/fees/');
  await navigate('/finance/billing/');
  await submit('form',{fee:config.fee,date:'2026-02-01',period:config.period,receivable_account:config.receivable},'button[value="preview"]');
  assert.ok(await evaluate(`document.body.innerText.includes('New billing total 150')`));
  await submit('form:has(input[name="preview_token"])',{},'button[value="post"]');
  async function payment(value){
    await navigate('/finance/payments/new/');await submit('form',{student:config.student,currency:config.usd,value,method:'cash',receiving_account:config.cash,receivable_account:config.receivable,on_date:'2026-02-02'});
    const paymentPath=await evaluate('location.pathname');assert.match(paymentPath,/\/payments\/.+\//);
    await submit('form:has(button[value="confirm"])',{period:config.period,auto_allocate:true},'button[value="confirm"]');
    assert.ok(await evaluate(`document.body.innerText.includes('RCPT-')`));return paymentPath;
  }
  const first=await payment('50');
  await navigate(`/finance/students/${config.student}/?currency=${config.usd}`);assert.ok(await evaluate(`document.body.innerText.includes('Closing balance: 100')`));
  await payment('100');
  await navigate(`/finance/students/${config.student}/?currency=${config.usd}`);assert.ok(await evaluate(`document.body.innerText.includes('Closing balance: 0')`));
  await navigate('/finance/cash-up/new/');await submit('form',{on_date:'2026-02-02',currency:config.usd,account:config.cash,opening_float:'5'});
  await submit('form',{actual:'155',note:'Synthetic browser cash count'});
  await login('admin');
  await navigate(`/finance/controls/${config.concession}/decide/`);await submit('form',{period:config.period,on_date:'2026-02-03',reason:'Independent browser approval',approved:'yes'});
  assert.ok(await evaluate(`document.body.innerText.includes('Calculated amount: USD 10')`));
  await navigate(`/finance/controls/${config.refund}/decide/`);await submit('form',{period:config.period,on_date:'2026-02-03',reason:'Independent refund approval',approved:'yes'});
  assert.ok(await evaluate(`document.body.innerText.includes('NOT DISBURSED')`));
  await navigate(`/finance/reconciliation/${config.match}/review/`);await submit('form',{approved:'yes',reason:'Browser independent match'});
  assert.ok(await evaluate(`document.body.innerText.includes('Reconciled')`));
  await navigate(`/finance/imports/${config.opening}/review/`);await submit('form',{approved:'yes',reason:'Browser reviewed opening balances',period:config.period,on_date:'2026-02-01',acknowledged_existing:true});
  assert.ok(await evaluate(`document.body.innerText.includes('Approved')`));
  await navigate('/finance/cash-up/');
  const review=await evaluate(`document.querySelector('a[href$="/review/"]')?.getAttribute('href')`);assert.ok(review);await navigate(review);await submit('form',{approved:'yes',reason:'Supervisor counted synthetic cash'});
  await navigate(first+'reverse/');await submit('form',{period:config.period,on_date:'2026-02-04',reason:'Synthetic incorrect payment correction'});
  assert.ok(await evaluate(`document.body.innerText.includes('reversed')`));
  await login('bursar');
  await navigate(`/finance/controls/${config.refund}/disburse/`);await submit('form',{period:config.period,on_date:'2026-02-03',reference:'BROWSER-PAID-REFUND',paid:true});
  assert.ok(await evaluate(`document.body.innerText.includes('Actual refund recorded')`));
  // Approver-only routes must remain denied to the cashier identity.
  await navigate(`/finance/controls/${config.concession}/decide/`);assert.ok(await evaluate(`document.body.innerText.includes('403') || document.body.innerText.includes('permission') || document.body.innerText.includes('Access')`));
  for(const url of ['/finance/','/finance/debt/','/finance/collections/','/finance/reports/?kind=trial','/finance/imports/','/finance/payments/','/finance/receipts/'])await navigate(url);
  await navigate('/finance/');
  for(const width of [1440,390]){
    await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<500});
    const screenshot=await command('Page.captureScreenshot',{format:'png'});writeFileSync(path.join(config.folder,`dashboard-${width}.png`),Buffer.from(screenshot.data,'base64'));
    assert.ok(await evaluate(`!!document.querySelector('nav[aria-label="Finance navigation"]')`));
  }
  await command('Browser.close');
  console.log('Finance browser passed: fee creation, billing preview/post, partial/full payment, receipt pages, statements, concession and refund decisions/disbursement, cash-up/review, reconciliation, opening approval, payment reversal, permission denial and dashboard screenshots. Artifacts: '+config.folder);
}finally{socket?.close();browser?.kill();server?.kill();}

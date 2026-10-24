import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {join} from 'node:path';

const {connectCDP,createProfile,stopBrowser}=await import(process.env.ARTICULOUS_BROWSER_SESSION);
const {collector}=await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
const maintained=['/assets/js/code-blocks.js','/assets/js/prism-copy-to-clipboard.js'];
const vendor=['prism-core','prism-markup','prism-clike','prism-javascript','prism-batch','prism-vbnet','prism-visual-basic','prism-toolbar','prism-keep-markup'];
const assets=new Map();
for(const name of [...maintained,...vendor.map(name=>'/assets/vendor/prism/'+name+'.js')]) {
  assets.set(name,await readFile(new URL('../../articulous/theme_assets'+name,import.meta.url)));
}
assets.set('/test-page.js',await readFile(new URL('./code-block-page.js',import.meta.url)));

function page(mode) {
  let scripts=['/test-page.js'];
  if(mode!=='missing-prism') scripts.push(...vendor.filter(name=>mode!=='missing-toolbar'||name!=='prism-toolbar').map(name=>'/assets/vendor/prism/'+name+'.js'));
  scripts.push('/assets/js/prism-copy-to-clipboard.js');
  if(!mode.startsWith('missing')) scripts.push('/assets/js/code-blocks.js');
  return '<!doctype html><html><head><meta charset="utf-8"><title>Code lifecycle</title></head><body>'+
    scripts.map(path=>'<script src="'+path+'"></script>').join('')+'</body></html>';
}

const server=createServer((request,response)=>{
  const url=new URL(request.url,'http://localhost');
  response.setHeader('Cache-Control','no-store');
  if(url.pathname==='/') {response.setHeader('Content-Type','text/html; charset=utf-8');response.end(page(url.searchParams.get('mode')));return;}
  const source=assets.get(url.pathname);
  response.statusCode=source ? 200 : 404;
  response.setHeader('Content-Type','text/javascript; charset=utf-8');
  response.end(source || '');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const profile=await createProfile('articulous-code-');
const chrome=spawn(process.env.ARTICULOUS_CHROMIUM,[
  '--headless=new','--no-sandbox','--no-first-run','--disable-dev-shm-usage',
  '--disable-background-networking','--disable-component-update','--disable-sync','--disable-quic',
  '--proxy-server=http://127.0.0.1:9','--proxy-bypass-list=127.0.0.1;localhost',
  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
  '--remote-debugging-port=0','--user-data-dir='+profile.path,'about:blank',
],{stdio:['ignore','ignore','pipe']});
let diagnostic='';
chrome.stderr.on('data',data=>{diagnostic=(diagnostic+data).slice(-65536);});
chrome.on('error',error=>{diagnostic=String(error);});

async function debuggingPort() {
  const deadline=Date.now()+10000;
  while(Date.now()<deadline) {
    try {return Number((await readFile(join(profile.path,'DevToolsActivePort'),'utf8')).split('\n')[0]);}
    catch(error) {if(error.code!=='ENOENT') throw error;}
    if(chrome.exitCode!==null) throw new Error('Chromium exited: '+diagnostic);
    await new Promise(resolve=>setTimeout(resolve,10));
  }
  throw new Error('Chromium startup protocol timed out: '+diagnostic);
}

async function evaluate(command,expression) {
  const result=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));
  return result.result.value;
}

async function navigate(command,mode) {
  const navigation=await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/?mode=${mode}`});
  assert.ok(!navigation.errorText,navigation.errorText);
  const deadline=Date.now()+10000;
  while(!await evaluate(command,"document.readyState==='complete' && typeof CodeTest!=='undefined'")) {
    assert.ok(Date.now()<deadline,'Page load protocol timed out');
    await new Promise(resolve=>setTimeout(resolve,10));
  }
}

function pageEvents(event) {
  const message=JSON.parse(event.data);
  if(message.method==='Runtime.exceptionThrown') console.error(JSON.stringify(message.params.exceptionDetails));
  if(message.method==='Runtime.consoleAPICalled') {
    const values=message.params.args.map(argument=>argument.value ?? argument.description);
    if(values[0]?.startsWith('[BUILD-013]')) console.error(...values);
  }
}

async function measure(command,socket) {
  const native=collector(command,maintained,socket);
  await command('Debugger.enable');await command('Runtime.enable');await command('Profiler.enable');
  await command('Profiler.startPreciseCoverage',{callCount:true,detailed:true});
  const cases=[];
  for(const mode of ['normal','unsupported','missing-toolbar','missing-prism']) {
    await navigate(command,mode);
    cases.push(...await evaluate(command,'CodeTest.run()'));
    await native.capture();
    console.error('[BUILD-013] settled browser mode '+mode);
  }
  const browser=await command('Browser.getVersion');
  const sources=Object.fromEntries(maintained.map(name=>[name,createHash('sha256').update(assets.get(name)).digest('hex')]));
  return {browser,node:process.versions.node,cases,sources,coverage:native.report()};
}

try {
  const port=await debuggingPort();
  const target=await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT',signal:AbortSignal.timeout(10000)})).json();
  const socket=new WebSocket(target.webSocketDebuggerUrl);
  const command=await connectCDP(socket);
  socket.addEventListener('message',pageEvents);
  try {
    const report=await measure(command,socket);
    await writeFile(process.env.ARTICULOUS_CODE_COVERAGE,JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({cases:report.cases.length,functions:report.coverage.length,browser:report.browser.product}));
  } finally {socket.removeEventListener('message',pageEvents);command.dispose();socket.close();}
} finally {await stopBrowser(chrome,server,profile);}

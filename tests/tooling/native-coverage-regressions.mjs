// BUILD-012: retain sources while their native script contexts still exist.
import assert from 'node:assert/strict';
const {collector} = await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
const file='/assets/js/example.js', source='function run() { return 1; }';
function fixture() {
  const socket=new EventTarget(), scripts=new Map();
  let counters=[];
  async function command(method,params) {
    if(method==='Profiler.takePreciseCoverage')return {result:counters};
    assert.ok(scripts.has(params.scriptId),'No script for id: '+params.scriptId);
    return {scriptSource:scripts.get(params.scriptId)};
  }
  function parsed(id,body=source) {
    scripts.set(id,body);
    socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({method:'Debugger.scriptParsed',params:{scriptId:id,url:'http://localhost'+file}})}));
    counters=[{scriptId:id,url:'http://localhost'+file,functions:[{functionName:'run',ranges:[{startOffset:0,endOffset:body.length,count:1}]}]}];
  }
  return {socket,command,parsed,forget:()=>scripts.clear()};
}
{
  const f=fixture(), native=collector(f.command,[file],f.socket);
  f.parsed('lost');await Promise.resolve();f.forget();
  await native.capture();assert.equal(native.report()[0].percent,100);
}
{
  const f=fixture(), native=collector(f.command,[file],f.socket);
  f.parsed('first');await native.capture();
  f.parsed('second','function run() { return 2; }');
  await assert.rejects(native.capture(),/source changed/);
}
{
  const f=fixture(), native=collector(f.command,[file],f.socket);
  assert.throws(()=>native.report(),/missing native counters/);
  f.parsed('gone');f.forget();await native.capture();
  assert.equal(native.report().length,1);
}
console.log('BUILD-012 source lifetime regressions passed');
{
 const socket=new EventTarget();
 const native=collector(async method=>{
  if(method==='Profiler.takePreciseCoverage')return {result:[{scriptId:'missing',url:'http://localhost'+file,functions:[]}]};
  throw new Error('unavailable source');
 },[file],socket);
 await assert.rejects(native.capture(),/unavailable source/);
}
{
 const {coverageRows}=await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
 const body='function parent() {\n function child() { return 1; }\n return 2;\n}';
 const childStart=body.indexOf('function child'),childEnd=body.indexOf('}',childStart)+1;
 const parent={functionName:'parent',ranges:[{startOffset:0,endOffset:body.length,count:1},{startOffset:body.indexOf('return 2'),endOffset:body.length,count:1}]};
 const child={functionName:'child',ranges:[{startOffset:childStart,endOffset:childEnd,count:0}]};
 assert.throws(()=>coverageRows(new Map([[file,{source:body,runs:[[parent],[parent,child]]}]])),/below 80/);
}

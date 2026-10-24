// BUILD-012: retain sources while their native script contexts still exist.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
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
    counters=[{scriptId:id,url:'http://localhost'+file,functions:[counter(body,''),counter(body,'run')]}];
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
  assert.equal(native.report().length,2);
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
 const module=counter(body,'');
 assert.throws(()=>coverageRows(new Map([[file,{source:body,runs:[[module,parent],[module,parent,child]]}]])),/below 80/);
}

{
 const {coverageRows}=await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
 const body=readFileSync(new URL('../../articulous/theme_assets/assets/js/code-blocks.js',import.meta.url),'utf8');
 assert.throws(()=>coverageRows(new Map([[file,{source:body,runs:[[]]}]])),/missing native counters/i);
}

function counter(body,name,fragment=body,count=1) {
 const startOffset=body.indexOf(fragment);
 return {functionName:name,ranges:[{startOffset,endOffset:startOffset+fragment.length,count}]};
}

const {coverageRows}=await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
function checked(body,functions) {
 return coverageRows(new Map([[file,{source:body,runs:[functions]}]]));
}

{
 const body='function f(){return 1;}\nf();', module=counter(body,''), fn=counter(body,'f','function f(){return 1;}');
 assert.equal(checked(body,[module,fn]).length,2);
 assert.throws(()=>checked(body,[module]),/Missing native counters for function/);
 assert.throws(()=>checked(body,[fn]),/Missing native counters for module/);
 assert.throws(()=>checked(body,[module,fn,fn]),/Duplicate native function/);
 assert.throws(()=>checked(body,[module,counter(body,'wrong','return 1;')]),/Unexpected native function boundary/);
 for(const field of ['startOffset','endOffset','count']) {
  for(const value of [-1,0.5,NaN,Infinity,true,undefined]) {
   const invalid=structuredClone(fn);invalid.ranges[0][field]=value;
   assert.throws(()=>checked(body,[module,invalid]),/Invalid native counter/);
  }
 }
 for(const ranges of [[],[{startOffset:0,endOffset:body.length+1,count:1}],
   [fn.ranges[0],{...fn.ranges[0],count:0}],
   [{startOffset:2,endOffset:2,count:1}],
   [fn.ranges[0],{startOffset:2,endOffset:fn.ranges[0].endOffset+1,count:1}],
   [fn.ranges[0],{startOffset:2,endOffset:10,count:1},{startOffset:4,endOffset:12,count:1}]]) {
  assert.throws(()=>checked(body,[module,{functionName:'f',ranges}]),/Invalid native counter/);
 }
 assert.throws(()=>checked(body,[module,{...fn,functionName:1}]),/Invalid native function name/);
 assert.throws(()=>checked(body,[module,counter(body,'f','function f(){return 1;}',0)]),/below 80/);
}

{
 const body='function outer(){function nested(){return 1;}return 2;}\nouter();';
 assert.throws(()=>checked(body,[counter(body,''),counter(body,'outer',body.split('\n')[0])]),/Missing native counters for function/);
 const whole='function f(){return 1;}';
 assert.throws(()=>checked(whole,[counter(whole,''),counter(whole,'f',whole,0)]),/below 80/);
 assert.equal(checked('',[counter('','')])[0].percent,100);
 for(const body of ['class A{x=1;}', 'class A{static {void 0;}}']) {
  assert.throws(()=>checked(body,[counter(body,'')]),/implicit class scopes is unsupported/);
 }
}

{
 const methods=['m(){return 1;}','get x(){return 2;}','async n(){}','*g(){}','["q"](){}'];
 const body='class A{static /*gap*/ m(){return 1;} get x(){return 2;} async n(){} *g(){} ["q"](){}}';
 assert.equal(checked(body,[counter(body,''),...methods.map(text=>counter(body,'method',text))]).length,6);
 const object='const o={m(){return 1;},get x(){return 2;},f:function(){return 3;}};';
 const parts=['m(){return 1;}','get x(){return 2;}','function(){return 3;}'];
 assert.equal(checked(object,[counter(object,''),...parts.map(text=>counter(object,'method',text))]).length,4);
}

// Test bootstrap: capture native script identities before process/context teardown.
import {Session} from 'node:inspector';
import {writeFileSync} from 'node:fs';
const session=new Session();session.connect();
const command=(method,params={})=>new Promise((resolve,reject)=>session.post(method,params,(error,result)=>error?reject(error):resolve(result)));
const sources=new Map(), names=new Map();
session.on('Debugger.scriptParsed',({params})=>{
  const name=params.url.split('/').pop();
  if (!['browser-session.mjs','native-coverage.mjs'].includes(name)) return;
  names.set(params.scriptId,name);
  sources.set(params.scriptId,command('Debugger.getScriptSource',{scriptId:params.scriptId}));
});
await command('Debugger.enable');await command('Profiler.enable');
await command('Profiler.startPreciseCoverage',{callCount:true,detailed:true});
process.once('beforeExit',async()=>{
 try {
  const result=await command('Profiler.takePreciseCoverage');
  const scripts=[];
  for(const script of result.result){
   if(!names.has(script.scriptId))continue;
   const source=await sources.get(script.scriptId);
   scripts.push({name:names.get(script.scriptId),source:source.scriptSource,functions:script.functions});
  }
  writeFileSync(process.env.ARTICULOUS_NODE_COVERAGE,JSON.stringify(scripts));
 } catch(error){console.error(error);process.exitCode=1;}
 finally{session.disconnect();}
});

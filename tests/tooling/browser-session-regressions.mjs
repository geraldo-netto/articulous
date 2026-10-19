// REV-095: disconnects, missing replies and dead/stubborn children are bounded.
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {access, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
const {connectCDP,stopBrowser,createProfile} = await import(process.env.ARTICULOUS_BROWSER_SESSION);
const pause=ms=>new Promise(done=>setTimeout(done,ms));
class Socket extends EventTarget {
  readyState=0;
  send(text){this.sent=JSON.parse(text);}
  close(){this.readyState=3;this.dispatchEvent(new Event('close'));}
  reply(data){this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(data)}));}
}
async function bounded(promise){return Promise.race([promise,pause(150).then(()=>{throw new Error('operation did not settle');})]);}
for(const failure of ['close','error','timeout']) {
  const socket=new Socket();const opening=connectCDP(socket,20);socket.readyState=1;socket.dispatchEvent(new Event('open'));
  const command=await bounded(opening);const result=command('Test');
  if(failure!=='timeout')socket.dispatchEvent(new Event(failure));
  await assert.rejects(bounded(result),/closed|error|timed out/);
}
{
 const socket=new Socket();await assert.rejects(bounded(connectCDP(socket,20)),/timed out/);
}
{
 const socket=new Socket();const opening=connectCDP(socket,20);socket.readyState=1;socket.dispatchEvent(new Event('open'));
 const command=await opening;const reply=command('Test');socket.reply({id:socket.sent.id,result:{ok:true}});assert.deepEqual(await reply,{ok:true});
 const failed=command('Fail');socket.reply({id:socket.sent.id,error:{message:'bad'}});await assert.rejects(failed,/bad/);
 socket.reply({id:999,result:{}});socket.reply({method:'Event'});socket.close();await assert.rejects(command('Closed'),/closed/);
}
for(const dead of [true,false]) {
 const child=new EventEmitter();child.exitCode=null;child.signalCode=dead?'SIGTERM':null;
 const signals=[];child.kill=signal=>{signals.push(signal);if(signal==='SIGKILL'){child.signalCode=signal;child.emit('exit',null,signal);}};
 const profile=await createProfile('morpha-cleanup-test-');let closed=false;
 const server={closeAllConnections(){},close(done){closed=true;done();}};
 const control=async phase=>{if(phase==='terminate')child.kill('SIGTERM');else if(child.signalCode===null)child.kill('SIGKILL');};
 await bounded(stopBrowser(child,server,profile,20,control));assert.ok(closed);await assert.rejects(access(profile.path));
 assert.deepEqual(signals,dead?[]:['SIGTERM','SIGKILL']);
}
{
 const child=new EventEmitter();child.exitCode=null;child.signalCode=null;
 const profile=await createProfile('articulous-uncertain-');let closed=false;
 const server={closeAllConnections(){},close(done){closed=true;done();}};
 try {
  await assert.rejects(bounded(stopBrowser(child,server,profile,20,async()=>{})),/did not exit/);
  assert.ok(closed);await access(profile.path);
 } finally {await rm(profile.path,{recursive:true,force:true});}
}
{
 const socket=new Socket();socket.readyState=1;
 const command=await connectCDP(socket,20);
 const pending=command('Dispose');command.dispose();
 await assert.rejects(pending,/disposed/);await assert.rejects(command('After'),/disposed/);
}
{
 const socket=new Socket();socket.readyState=1;socket.send=()=>{throw new Error('send fault');};
 const command=await connectCDP(socket,20);await assert.rejects(command('Fail'),/send fault/);command.dispose();
}
{
 const socket=new Socket();socket.readyState=1;
 const command=await connectCDP(socket,20);const pending=command('Malformed');
 socket.dispatchEvent(new MessageEvent('message',{data:'broken'}));await assert.rejects(pending,/message error/);
}
{
 const profile=await createProfile('articulous-native-fence-');
 const child={exitCode:0,signalCode:null};
 const server={closeAllConnections(){},close(done){done();}};
 await stopBrowser(child,server,profile);
 await assert.rejects(access(profile.path));
}
for(const prefix of ['',null,'../escape','a/b','a\\b'])await assert.rejects(createProfile(prefix),/prefix/);
for(const event of ['error','close']) {
 const socket=new Socket(), opening=connectCDP(socket,20);
 socket.dispatchEvent(new Event(event));await assert.rejects(opening,/error|closed/);
}
{
 const child=new EventEmitter();child.exitCode=null;child.signalCode=null;
 const profile=await createProfile('articulous-cooperative-');
 const server={closeAllConnections(){},close(done){done();}};
 const control=async phase=>{if(phase==='terminate')setTimeout(()=>{child.exitCode=0;child.emit('exit',0,null);},0);};
 await stopBrowser(child,server,profile,20,control);
}
{
 const profile=await createProfile('articulous-server-uncertain-');
 try {await assert.rejects(stopBrowser({exitCode:0,signalCode:null},{closeAllConnections(){},close(){}},profile,20,async()=>{}),/HTTP server close/);await access(profile.path);}
 finally {await rm(profile.path,{recursive:true,force:true});}
}
{
 const python=process.env.ARTICULOUS_PYTHON;
 const server={closeAllConnections(){},close(done){done();}};
 try {
  delete process.env.ARTICULOUS_PYTHON;
  const missing=await createProfile('articulous-missing-control-');
  await assert.rejects(stopBrowser({exitCode:0,signalCode:null},server,missing),/owned Linux/);await access(missing.path);
  process.env.ARTICULOUS_PYTHON='/nonexistent/articulous-python';
  const failed=await createProfile('articulous-failed-control-');
  await assert.rejects(stopBrowser({exitCode:0,signalCode:null},server,failed),/ENOENT/);await access(failed.path);
  const {writeFile}=await import('node:fs/promises');
  const fake=join(tmpdir(),'slow-python');
  await writeFile(fake,'#!'+python+'\nimport sys,time\nprint("diagnostic",file=sys.stderr,flush=True)\ntime.sleep(2)\n',{mode:0o700});
  process.env.ARTICULOUS_PYTHON=fake;
  const slow=await createProfile('articulous-slow-control-');
  await assert.rejects(stopBrowser({exitCode:0,signalCode:null},server,slow,20),/fence timed out/);await access(slow.path);
 } finally {process.env.ARTICULOUS_PYTHON=python;}
}

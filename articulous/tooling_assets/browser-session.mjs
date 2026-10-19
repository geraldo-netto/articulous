// Native CDP request ownership and explicit browser/profile settlement.
import {mkdtemp, lstat, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {spawn} from 'node:child_process';

export async function connectCDP(socket, timeout = 10000) {
  if (socket.readyState !== 1) await new Promise((resolve,reject)=>{
    const finish=error=>{clearTimeout(timer);for(const [event,listener] of listeners)socket.removeEventListener(event,listener);error?reject(error):resolve();};
    const listeners=[['open',()=>finish()],['error',()=>finish(new Error('CDP socket error'))],['close',()=>finish(new Error('CDP socket closed'))]];
    const timer=setTimeout(()=>finish(new Error('CDP open timed out')),timeout);
    for(const [event,listener] of listeners)socket.addEventListener(event,listener);
  });
  let sequence=0, closed;
  const pending=new Map();
  const stop=error=>{
    closed=error;
    for(const operation of pending.values()){clearTimeout(operation.timer);operation.reject(error);}
    pending.clear();
    for (const [event, listener] of listeners) socket.removeEventListener(event, listener);
  };
  function message(event) {
    let reply;
    try {reply=JSON.parse(event.data);} catch {stop(new Error('CDP message error'));return;}
    const operation=pending.get(reply?.id);
    if(!operation)return;
    pending.delete(reply.id);clearTimeout(operation.timer);
    if(reply.error)operation.reject(new Error(JSON.stringify(reply.error)));else operation.resolve(reply.result);
  }
  const listeners=[['close',()=>stop(new Error('CDP socket closed'))],['error',()=>stop(new Error('CDP socket error'))],['message',message]];
  for (const [event, listener] of listeners) socket.addEventListener(event,listener);
  const command=(method,params={})=>new Promise((resolve,reject)=>{
    if(closed || socket.readyState!==1){reject(closed || new Error('CDP socket closed'));return;}
    const id=++sequence;
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`CDP ${method} timed out`));},timeout);
    pending.set(id,{resolve,reject,timer});
    try {socket.send(JSON.stringify({id,method,params}));}
    catch(error){pending.delete(id);clearTimeout(timer);reject(error);}
  });
  command.dispose=()=>stop(new Error('CDP session disposed'));
  return command;
}

export async function createProfile(prefix='articulous-browser-') {
  if (typeof prefix!=='string' || !prefix || /[/\\]/.test(prefix)) throw new TypeError('Invalid browser profile prefix');
  const path=await mkdtemp(join(tmpdir(),prefix));
  const identity=await lstat(path,{bigint:true});
  return Object.freeze({path,dev:identity.dev,ino:identity.ino});
}

async function removeProfile(profile) {
  const identity=await lstat(profile.path,{bigint:true});
  if (!identity.isDirectory() || identity.dev!==profile.dev || identity.ino!==profile.ino) throw new Error('Browser profile identity changed; retained');
  await rm(profile.path,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}

function exited(child,timeout) {
  if(child.exitCode!==null || child.signalCode!==null)return Promise.resolve(true);
  return new Promise(resolve=>{
    const finish=value=>{clearTimeout(timer);child.removeListener('exit',done);resolve(value);};
    const done=()=>finish(true);
    const timer=setTimeout(()=>finish(false),timeout);
    child.once('exit',done);
  });
}

function nativePhase(phase, timeout) {
  return new Promise((resolve,reject)=>{
    const python=process.env.ARTICULOUS_PYTHON;
    if (!python) {reject(new Error('Browser fence requires Articulous-owned Linux session'));return;}
    const child=spawn(python,['-m','articulous.backends.browser_fence',String(process.pid),phase,String(timeout/1000)],{stdio:['ignore','ignore','pipe']});
    let diagnostic='';
    const timer=setTimeout(()=>reject(new Error('Native browser fence timed out; profile retained')),timeout+1000);
    child.stderr.on('data',chunk=>{diagnostic+=chunk;});
    child.on('error',error=>{clearTimeout(timer);reject(error);});
    child.on('close',code=>{clearTimeout(timer);code===0?resolve():reject(new Error('Native browser fence failed: '+diagnostic));});
  });
}

export async function stopBrowser(chrome,server,profile,timeout=2000,control=nativePhase) {
  let fenced=false;
  try {
    if(chrome.exitCode===null && chrome.signalCode===null){
      await control('terminate',timeout);
      if(!await exited(chrome,timeout)){
        await control('fence',timeout);
        if(!await exited(chrome,timeout))throw new Error('Chromium did not exit after SIGKILL');
      }
    }
    await control('fence',timeout);
    fenced=true;
  } finally {
    server.closeAllConnections();
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('HTTP server close timed out')),timeout);
      server.close(()=>{clearTimeout(timer);resolve();});
    });
    if (fenced) await removeProfile(profile);
  }
}

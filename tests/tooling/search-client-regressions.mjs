// THEME-002: neutral consumer, bounded batches, invalid data and lifecycle interleavings.
import assert from 'node:assert/strict';
await import(process.env.ARTICULOUS_SEARCH_CLIENT);
const api=globalThis.SearchClient;
const rows=Array.from({length:503},(_,index)=>({url:`https://example.test/prefix/entry-${index}/`,title:`Title ${index}`,description:'Description',tags:['Some Tag']}));
function metadata(item,url){return {path:url.pathname,language:'neutral',tagRoot:'/custom/taxonomy/'};}
function select(items){return items;}
function match(items,query){return items.filter(item=>item.haystack.includes(query));}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function fixture(overrides={}){
 const events={loads:0,prepared:0,selected:0,clear:0,loading:0,failed:[],published:[],appended:[]};
 const options={origin:'https://example.test/prefix',
  load:async()=>{events.loads++;return rows;},
  prepare(item,url){events.prepared++;return metadata(item,url);},
  select(items){events.selected++;return select(items);},match,
  renderer:{clear(){events.clear++;},loading(){events.loading++;},failed(error){events.failed.push(error);},
   create(){return [];},append(container,item){events.appended.push(item);container.push(item);},
   publish(container,count){events.published.push({container,count});}},...overrides};
 return {options,events,controller:api.create(options)};
}
{
 const f=fixture();await f.controller.search('title');
 assert.equal(f.events.published[0].count,503);assert.equal(f.events.published[0].container.length,503);
 assert.equal(f.events.prepared,503);assert.equal(f.events.selected,1);
 await f.controller.search('description');assert.equal(f.events.loads,1);
 await f.controller.search('');assert.equal(f.events.clear,1);
 f.controller.dispose();f.controller.reset();f.controller.dispose();await f.controller.search('title');
 assert.equal(f.events.clear,1);
}
for(const invalid of [null,false,0,{},'data'])assert.throws(()=>api.prepareIndex(invalid,'https://example.test',metadata),/index/);
for(const invalid of [null,{}, {url:'',title:'x',description:'x'},
 {url:'/x',title:4,description:'x'}, {url:'/x',title:'x',description:null},
 {url:'/x',title:'x',description:'x',tags:'tag'}, {url:'/x',title:'x',description:'x',tags:[4]},
 {url:'javascript:bad()',title:'x',description:'x'}, {url:'http://[',title:'x',description:'x'}]){
 assert.throws(()=>api.prepareIndex([invalid],'https://example.test',metadata));
}
{
 const prepared=api.prepareIndex([{url:'/prefix/item/',title:'É',description:'Text'}],'https://example.test',metadata);
 assert.equal(prepared[0].language,'neutral');assert.ok(Object.isFrozen(prepared[0].tags));assert.ok(Object.isFrozen(prepared[0]));
 assert.equal(api.normalizeSlug(' C++ / C# '),'c-c');
 assert.equal(api.normalizeSlug('Some Tag'),'some-tag');
 assert.equal(api.normalizeSlug('日本語'),'');
}
for(const batchSize of [0,-1,1.5,NaN,Infinity,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>fixture({batchSize}),/batch size/);
{
 const f=fixture();await assert.rejects(f.controller.search(null),/must be text/);f.controller.dispose();
}
{
 let fail=true;const f=fixture({load:async()=>{if(fail)throw new Error('offline');return rows;}});
 await f.controller.search('title');assert.equal(f.events.failed.length,1);
 fail=false;await f.controller.search('title');assert.equal(f.events.published[0].count,503);f.controller.dispose();
}
{
 let fail=true;const f=fixture({match:items=>fail?{}:items});
 await f.controller.search('title');assert.equal(f.events.failed.length,1);
 fail=false;await f.controller.search('title');assert.equal(f.events.published[0].count,503);f.controller.dispose();
}
{
 const pending=deferred();let loads=0;
 const f=fixture({load:()=>{loads++;return pending.promise;}});
 const first=f.controller.search('absent'),last=f.controller.search('title');
 pending.resolve(rows);await Promise.all([first,last]);
 assert.equal(loads,1);assert.equal(f.events.published.length,1);assert.equal(f.events.published[0].count,503);f.controller.dispose();
}
{
 const pending=deferred();const f=fixture({load:()=>pending.promise});
 const work=f.controller.search('title');await Promise.resolve();f.controller.dispose();pending.resolve(rows);await work;
 assert.equal(f.events.prepared,0);assert.equal(f.events.published.length,0);
}
{
 const f=fixture();const work=f.controller.search('title');f.controller.dispose();await work;
 assert.equal(f.events.loads,1);assert.equal(f.events.published.length,0);
}
{
 let controller,prepared=0;
 const f=fixture({prepare(item,url){prepared++;controller.dispose();return metadata(item,url);}});controller=f.controller;
 await controller.search('title');assert.equal(prepared,1);assert.equal(f.events.published.length,0);
}
{
 let controller;
 const f=fixture({select(items){controller.dispose();return items;}});controller=f.controller;
 await controller.search('title');assert.equal(f.events.published.length,0);
}
{
 let controller;
 const f=fixture({prepare(item,url){controller.dispose();return metadata(item,url);},load:async()=>rows.slice(0,1)});controller=f.controller;
 await controller.search('title');assert.equal(f.events.published.length,0);
}
{
 let controller;
 const f=fixture({renderer:{...fixture().options.renderer,loading(){controller.reset();}}});controller=f.controller;
 await controller.search('title');assert.equal(f.events.loads,0);
}
{
 let controller,appended=0,published=0;
 const f=fixture({renderer:{clear(){},loading(){},failed(error){throw error;},create(){return [];},
  append(){appended++;controller.reset();},publish(){published++;}}});controller=f.controller;
 await controller.search('title');assert.equal(appended,1);assert.equal(published,0);controller.dispose();
}
{
 const pending=deferred();const f=fixture({schedule:()=>pending.promise,batchSize:2});
 const work=f.controller.search('title');
 while(f.events.appended.length<2)await new Promise(resolve=>setImmediate(resolve));
 f.controller.reset();pending.resolve();await work;
 assert.equal(f.events.appended.length,2);assert.equal(f.events.published.length,0);f.controller.dispose();
}
{
 let controller,appended=0;
 const f=fixture({batchSize:2,renderer:{clear(){},loading(){},failed(error){throw error;},create(){return [];},
  append(){appended++;if(appended===2)controller.dispose();},publish(){throw new Error('late publish');}}});controller=f.controller;
 await controller.search('title');assert.equal(appended,2);
}
{
 let controller;
 const f=fixture({batchSize:2,renderer:{clear(){},loading(){},failed(error){throw error;},create(){return [];},
  append(){queueMicrotask(()=>controller.dispose());},publish(){throw new Error('late publish');}}});controller=f.controller;
 await controller.search('title');
}
{
 const native=globalThis.MessageChannel;
 globalThis.MessageChannel=class extends native{constructor(){super();this.port2.postMessage=()=>{throw new Error('post fault');};}};
 try{const f=fixture({batchSize:2});await f.controller.search('title');assert.equal(f.events.failed.length,1);f.controller.dispose();}
 finally{globalThis.MessageChannel=native;}
}
console.log('THEME-002 neutral search consumer and lifecycle passed');

{
 let admitted=false;
 const f=fixture({load:()=>{admitted=true;return Promise.resolve(rows);}});
 const work=f.controller.search('title');
 assert.ok(admitted,'THEME-002 preserves synchronous load admission');
 await work;f.controller.dispose();
}
{
 let fail=true;
 const f=fixture({load(){if(fail)throw new Error('synchronous loader failure');return Promise.resolve(rows);}});
 await f.controller.search('title');assert.equal(f.events.failed.length,1);
 fail=false;await f.controller.search('title');assert.equal(f.events.published[0].count,503);f.controller.dispose();
}

{
 const native=globalThis.MessageChannel, admitted=deferred();
 globalThis.MessageChannel=class extends native{
  constructor(){super();this.port2.postMessage=()=>admitted.resolve();}
 };
 try {
  const f=fixture();
  const work=f.controller.search('title');
  await admitted.promise;
  assert.equal(f.events.prepared,200);
  assert.equal(f.events.selected,0);
  f.controller.dispose();
  await work;
  assert.equal(f.events.prepared,200);
  assert.equal(f.events.published.length,0);
 } finally {
  globalThis.MessageChannel=native;
 }
}
{
 const f=fixture({load:async()=>null});
 await f.controller.search('title');
 assert.match(f.events.failed[0].message,/Invalid search index/);
 f.controller.dispose();
}
{
 const sparse=rows.slice(0,2);delete sparse[0];
 const f=fixture({load:async()=>sparse,match:items=>items.filter(Boolean)});
 await f.controller.search('title');
 assert.equal(f.events.prepared,1);
 assert.equal(f.events.published[0].count,1);
 f.controller.dispose();
}

// AUDIT26-11: a synchronous loader can trigger a second query.
{
 let calls=0, nested;
 const pending=deferred();
 const f=fixture({load(){
  if (++calls===1) nested=f.controller.search('description');
  return pending.promise;
 }});
 const first=f.controller.search('title');
 assert.equal(calls,1);
 pending.resolve(rows.slice(0,1));
 await Promise.all([first,nested]);
 await f.controller.search('title');
 assert.equal(calls,1);
 assert.deepEqual(f.events.published.map(result=>result.count),[1,1]);
 f.controller.dispose();
}

{
  let controller, creates = 0;
  const f = fixture({
    match(items) { controller.reset(); return items; },
    renderer: {...fixture().options.renderer, create() { creates++; return []; }}
  });
  controller = f.controller;
  await controller.search('title');
  assert.equal(creates, 0, 'REVIEW27-15 reset during matching stops renderer admission');
  controller.dispose();
}

{
 const item={url:'/original',title:'Title',description:'Text',tags:['tag']};
 const [record]=api.prepareIndex([item],'https://example.test',(raw,url)=>{
  raw.url='/different';raw.title=null;raw.description=42;raw.tags.push('changed');
  return {destination:url.pathname};
 });
 assert.deepEqual(record,{destination:'/original',url:'/original',title:'Title',
  description:'Text',tags:['tag'],haystack:'title text tag'},'REVIEW29-20 retain validated row fields');
}

{
 const row={url:'/item',title:'Item',description:'Text',tags:[]};
 for(const size of [1,2,7]){
  for(let index=0;index<size;index++){
   const sparse=Array(size).fill('tag');delete sparse[index];
   assert.throws(()=>api.prepareIndex([{...row,tags:sparse}],'https://example.test',metadata),
    /Invalid search entry/,'REVIEW29-21 every tag slot must contain a string');
  }
 }
 for(const tags of [[],[''],['a','']]){
  assert.deepEqual(api.prepareIndex([{...row,tags}],'https://example.test',metadata)[0].tags,tags);
 }
}

// REV-064: union native execution across page loads, without excluding any asset.
import assert from 'node:assert/strict';
import {parseJavaScript} from './javascript-syntax.mjs';

// Capture on scriptParsed, before navigation can destroy the owning context.
// Cache by native ID, never by URL: each measured version must match exactly.
function scriptSources(command, expected, socket) {
  const sources = new Map();
  function retain(scriptId) {
    if (!sources.has(scriptId)) {
      sources.set(scriptId, command('Debugger.getScriptSource', {scriptId})
        .then(result => ({source:result.scriptSource}), error => ({error})));
    }
    return sources.get(scriptId);
  }
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method !== 'Debugger.scriptParsed') return;
    const script = message.params;
    if (!script.url.startsWith('http')) return;
    if (expected.has(new URL(script.url).pathname)) retain(script.scriptId);
  });
  return async scriptId => {
    const result = await retain(scriptId);
    if (result.error) throw result.error;
    return result.source;
  };
}

export function collector(command, expectedFiles, socket) {
  const expected = new Set(expectedFiles);
  const files = new Map();
  const sourceFor = scriptSources(command, expected, socket);
  async function capture() {
    const precise = await command('Profiler.takePreciseCoverage');
    for (const script of precise.result) {
      if (!script.url.startsWith('http')) continue;
      const file = new URL(script.url).pathname;
      if (!expected.has(file)) continue;
      const source = await sourceFor(script.scriptId);
      if (!files.has(file)) files.set(file, {source, runs:[]});
      assert.equal(files.get(file).source, source, `REV-064 source changed during measurement: ${file}`);
      files.get(file).runs.push(script.functions);
    }
  }
  function report() {
    assert.deepEqual([...files.keys()].sort(), [...expected].sort(), 'REV-064 missing native counters for a production asset');
    return coverageRows(files);
  }

  return {capture, report};
}

function sourceLines(source) {
  let offset=0;
  return source.split('\n').map(text=>{
    const begin=offset;offset+=text.length+1;
    return {text,begin};
  });
}

function executablePosition(line, outer) {
  if (line.begin+line.text.length<=outer.startOffset || line.begin>=outer.endOffset) return null;
  if (!line.text.trim() || /^\s*(\/\/|\/\*|\*|[{}()[\];,]+\s*$)/.test(line.text)) return null;
  return Math.max(outer.startOffset,line.begin+line.text.search(/\S/));
}

function childOwns(children, outer, position) {
  return children.some(child=>child.startOffset>outer.startOffset && child.endOffset<=outer.endOffset && child.startOffset<=position && child.endOffset>position);
}

function tightestRange(fn, position) {
  return fn.ranges.filter(range=>range.startOffset<=position && position<range.endOffset)
    .sort((a,b)=>(a.endOffset-a.startOffset)-(b.endOffset-b.startOffset))[0] || fn.ranges[0];
}

function measureFunction(measured, fn, lines, children) {
  const outer=fn.ranges[0];
  measured.called ||= outer.count>0;
  for (let index=0;index<lines.length;index++) {
    const position=executablePosition(lines[index],outer);
    if (position===null || childOwns(children,outer,position)) continue;
    const range=tightestRange(fn,position);
    measured.executable.add(index);
    if (range.count>0) measured.covered.add(index);
  }
}

function recordFunction(file,source,fn,functions,lines,children,identity) {
  const outer=fn.ranges[0],key=`${file}:${identity}`;
  if (!functions.has(key)) functions.set(key,{file,function:fn.functionName || '(module/callback)',
    line:source.slice(0,outer.startOffset).split('\n').length,executable:new Set(),covered:new Set(),called:false});
  measureFunction(functions.get(key),fn,lines,children);
}

function functionRow(fn) {
  return {file:fn.file,function:fn.function,line:fn.line,covered:fn.covered.size,executable:fn.executable.size,
    percent:fn.executable.size ? fn.covered.size*100/fn.executable.size : (fn.called ? 100 : 0)};
}

export function coverageRows(files) {
  const functions=new Map();
  for (const [file,{source,runs}] of files) {
    const lines=sourceLines(source);
    const children=sourceFunctions(source);
    const counters=completeCounters(source,runs,children);
    for (const {fn,identity} of counters) recordFunction(file,source,fn,functions,lines,children,identity);
  }
  const coverage=[...functions.values()].map(functionRow);
  for (const fn of coverage) assert.ok(fn.percent>=80,`Per-function coverage below 80%: ${JSON.stringify(fn)}`);
  return coverage;
}

function methodStart(node,parent,tokens) {
  if (parent?.type==='MethodDefinition') {
    return parent.static ? tokens.find(token=>token.start>parent.start).start : parent.start;
  }
  if (parent?.type==='Property' && (parent.method || parent.kind!=='init')) return parent.start;
  return node.start;
}

function sourceFunctions(source) {
  const {tree,tokens}=parseJavaScript(source), pending=[[tree,null]], functions=[];
  while (pending.length) {
    const [node,parent]=pending.pop();
    assert.ok(!['PropertyDefinition','StaticBlock'].includes(node.type),'Native coverage for implicit class scopes is unsupported');
    if (['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(node.type)) {
      functions.push({startOffset:methodStart(node,parent,tokens),endOffset:node.end});
    }
    for (const child of syntaxChildren(node)) pending.push([child,node]);
  }
  return functions;
}

function syntaxChildren(node) {
  return Object.values(node).flat().filter(value=>value && typeof value==='object' && typeof value.type==='string');
}

function checkedRange(range,length) {
  assert.ok(Number.isSafeInteger(range.startOffset) && Number.isSafeInteger(range.endOffset),'Invalid native counter offsets');
  assert.ok(range.startOffset>=0 && (range.startOffset<range.endOffset || length===0) && range.endOffset<=length,'Invalid native counter bounds');
  assert.ok(Number.isSafeInteger(range.count) && range.count>=0,'Invalid native counter count');
}

function checkedFunction(fn,length) {
  assert.equal(typeof fn.functionName,'string','Invalid native function name');
  assert.ok(Array.isArray(fn.ranges) && fn.ranges.length>0,'Invalid native counter ranges');
  const parents=[];
  for (const range of fn.ranges) {
    checkedRange(range,length);
    while (parents.length && range.startOffset>=parents.at(-1).endOffset) parents.pop();
    if (parents.length) {
      const parent=parents.at(-1);
      assert.ok(range.startOffset>=parent.startOffset && range.endOffset<=parent.endOffset,'Invalid native counter nesting');
      assert.ok(range.startOffset!==parent.startOffset || range.endOffset!==parent.endOffset,'Invalid native counter duplicate range');
    }
    parents.push(range);
  }
  const outer=fn.ranges[0];
  assert.ok(fn.ranges.every(range=>range.startOffset>=outer.startOffset && range.endOffset<=outer.endOffset),'Invalid native counter containment');
}

function rangeIdentity(range) {
  return `${range.startOffset}:${range.endOffset}`;
}

function counterIdentity(fn,index,length) {
  const range=fn.ranges[0];
  if (index===0 && fn.functionName==='' && range.startOffset===0 && range.endOffset===length) return 'module';
  return rangeIdentity(range);
}

function runCounters(run,length,expected,seen) {
  const current=new Set();
  return run.map((fn,index)=>{
    checkedFunction(fn,length);
    const identity=counterIdentity(fn,index,length);
    assert.ok(identity==='module' || expected.has(identity),'Unexpected native function boundary');
    assert.ok(!current.has(identity),'Duplicate native function counter');
    current.add(identity);seen.add(identity);
    return {fn,identity};
  });
}

function completeCounters(source,runs,functions) {
  const expected=new Set(functions.map(rangeIdentity)),seen=new Set();
  const counters=runs.flatMap(run=>runCounters(run,source.length,expected,seen));
  for (const identity of expected) assert.ok(seen.has(identity),`Missing native counters for function ${identity}`);
  assert.ok(seen.has('module'),'Missing native counters for module');
  return counters;
}

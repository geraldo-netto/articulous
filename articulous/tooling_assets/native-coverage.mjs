// REV-064: union native execution across page loads, without excluding any asset.
import assert from 'node:assert/strict';

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

function recordFunction(file,source,fn,functions,lines,children) {
  const outer=fn.ranges[0],key=`${file}:${outer.startOffset}:${outer.endOffset}`;
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
    const children=runs.flat().map(fn=>fn.ranges[0]);
    for (const fn of runs.flat()) recordFunction(file,source,fn,functions,lines,children);
  }
  const coverage=[...functions.values()].map(functionRow);
  for (const fn of coverage) assert.ok(fn.percent>=80,`Per-function coverage below 80%: ${JSON.stringify(fn)}`);
  return coverage;
}

import {readFileSync} from 'node:fs';
const {coverageRows}=await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
const files=new Map();
for(const path of process.argv.slice(2))for(const script of JSON.parse(readFileSync(path,'utf8'))){
 if(!files.has(script.name))files.set(script.name,{source:script.source,runs:[]});
 if(files.get(script.name).source!==script.source)throw new Error('Native source identity changed');
 files.get(script.name).runs.push(script.functions);
}
if(files.size!==3)throw new Error('Missing native tooling counters');
console.log(JSON.stringify(coverageRows(files)));

import {readFileSync} from 'node:fs';
const {coverageRows}=await import(process.env.ARTICULOUS_NATIVE_COVERAGE);
const scripts=JSON.parse(readFileSync(process.argv[2],'utf8')).filter(script=>script.name==='search-client.js');
if(scripts.length!==1)throw new Error('Missing native search counters');
console.log(JSON.stringify(coverageRows(new Map(scripts.map(script=>[script.name,{source:script.source,runs:[script.functions]}])))));

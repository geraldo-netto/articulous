import {createRequire} from 'node:module';

const {parse} = createRequire(import.meta.url)(process.env.ARTICULOUS_ACORN || 'acorn');

export function parseJavaScript(source) {
  const tokens = [];
  const tree = parse(source, {ecmaVersion:2022, sourceType:'module', locations:true, onToken:tokens});
  return {tree, tokens};
}

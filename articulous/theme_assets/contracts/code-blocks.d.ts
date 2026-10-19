/** Prism owns rendering, toolbar generation and copy. Dispose fences callbacks
 * and retires library controls before reusing the same code/pre identities. */
export interface CodeBlockController { dispose(): void; }
export interface CodeBlocksAPI {
  language(code: HTMLElement): string;
  mount(pre: HTMLPreElement | null): CodeBlockController | null;
  init(doc: Document, selector?: string): CodeBlockController[];
}

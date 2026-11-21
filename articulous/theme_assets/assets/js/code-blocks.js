/* Prism owns tokenization, theme markup, toolbar and clipboard writes.
 * This adapter supplies author language hints and an explicit teardown boundary. */
const CodeBlocks = (() => {
  const owners = new WeakMap();
  const aliases = {cmd:'batch', vb:'visual-basic', xml:'markup', js:'javascript'};

  function grammarName(hint) {
    const name = Object.hasOwn(aliases, hint) ? aliases[hint] : hint;
    if (!Object.hasOwn(Prism.languages, name)) return null;
    return Prism.util.type(Prism.languages[name]) === 'Object' ? name : null;
  }

  function language(code) {
    const classes = [...code.classList];
    const labelled = classes.find(name => name.startsWith('language-'));
    if (labelled) return grammarName(labelled.slice(9).toLowerCase()) || 'none';
    for (const name of classes) {
      const grammar = grammarName(name);
      if (grammar) return grammar;
    }
    return 'none';
  }

  function codeElement(pre) {
    const code = pre.querySelector(':scope > code') || pre.ownerDocument.createElement('code');
    const leading = pre.ownerDocument.createDocumentFragment();
    while (pre.firstChild && pre.firstChild !== code) leading.append(pre.firstChild);
    code.prepend(leading);
    while (code.nextSibling) code.append(code.nextSibling);
    if (!code.parentNode) pre.append(code);
    return code;
  }

  function mount(pre) {
    if (pre?.nodeName !== 'PRE' || !pre.isConnected) return null;
    owners.get(pre)?.dispose();
    const code = codeElement(pre);
    Prism.util.setLanguage(code, language(code));
    code.classList.add('drop-tokens');
    const parent = pre.parentElement;
    Prism.highlightElement(code);
    const wrapper = pre.parentElement !== parent ? pre.parentElement : null;
    const toolbar = wrapper?.querySelector(':scope > .toolbar');
    const controller = {dispose};
    owners.set(pre, controller);

    function dispose() {
      if (owners.get(pre) !== controller) return;
      owners.delete(pre);
      if (!wrapper) return;
      Prism.plugins.copyToClipboard.dispose(code);
      if (pre.parentElement !== wrapper || !wrapper.classList.contains('code-toolbar')) return;
      if (toolbar?.parentElement === wrapper) toolbar.remove();
      if (!wrapper.parentNode) return;
      const content = pre.ownerDocument.createDocumentFragment();
      while (wrapper.firstChild) content.append(wrapper.firstChild);
      wrapper.replaceWith(content);
    }
    return controller;
  }

  function init(doc, selector = 'pre') {
    return [...doc.querySelectorAll(selector)].map(mount).filter(Boolean);
  }
  return {language, mount, init};
})();


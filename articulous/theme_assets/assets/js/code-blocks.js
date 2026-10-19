/* Prism owns tokenization, theme markup, toolbar and clipboard writes.
 * This adapter supplies author language hints and an explicit teardown boundary. */
const CodeBlocks = (() => {
  const owners = new WeakMap();
  const aliases = {cmd:'batch', vb:'visual-basic', xml:'markup', js:'javascript'};

  function language(code) {
    const classes = [...code.classList];
    const labelled = classes.find(name => name.startsWith('language-'));
    const hint = labelled ? labelled.slice(9) : classes.find(name => Prism.languages[aliases[name] || name]);
    return aliases[hint] || hint || 'none';
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
    Prism.highlightElement(code);
    const wrapper = pre.parentElement;
    const controller = {dispose};
    owners.set(pre, controller);

    function dispose() {
      if (owners.get(pre) !== controller) return;
      owners.delete(pre);
      Prism.plugins.copyToClipboard.dispose(code);
      if (pre.parentElement !== wrapper || !wrapper.classList.contains('code-toolbar')) return;
      wrapper.replaceWith(pre);
    }
    return controller;
  }

  function init(doc, selector = 'pre') {
    return [...doc.querySelectorAll(selector)].map(mount).filter(Boolean);
  }
  return {language, mount, init};
})();


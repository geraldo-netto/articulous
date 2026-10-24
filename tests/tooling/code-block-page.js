const CodeTest = (() => {
  const mode = new URL(location.href).searchParams.get('mode');
  const requests = [];
  let throwClipboard = false;
  if (mode !== 'missing-prism') globalThis.Prism = {manual:true};
  Object.defineProperty(navigator, 'clipboard', {
    configurable:true, value:mode === 'unsupported' ? undefined : {writeText},
  });

  function writeText(text) {
    if (throwClipboard) throw new Error('clipboard rejected synchronously');
    let resolve, reject;
    const promise = new Promise((yes,no) => {resolve=yes;reject=no;});
    requests.push({text,resolve,reject});
    return promise;
  }

  function check(value, message) {
    if (!value) throw new Error(message);
  }

  function tick() {
    return new Promise(resolve => setTimeout(resolve, 0));
  }

  function fixture(content='  exact &amp; text\n', settings=true) {
    const pre = document.createElement('pre');
    pre.innerHTML = content;
    if (settings) {
      pre.setAttribute('data-prismjs-copy', 'Copiar');
      pre.setAttribute('data-prismjs-copy-success', 'Listo');
      pre.setAttribute('data-prismjs-copy-error', 'Error');
      pre.setAttribute('data-prismjs-copy-timeout', '20');
    }
    document.body.append(pre);
    const controller = CodeBlocks.mount(pre);
    const wrapper = pre.parentElement;
    return {pre,controller,wrapper,code:pre.querySelector('code'),button:wrapper.querySelector('button')};
  }

  async function release(fixture) {
    fixture.controller.dispose();
    fixture.pre.remove();
    fixture.wrapper.remove();
    for (const request of requests.splice(0)) request.resolve();
    throwClipboard = false;
    await tick();
  }

  async function waitState(button, state) {
    while (button.dataset.copyState !== state) await tick();
  }

  function admission() {
    for (const input of [null, undefined, false, 0, '', [], {}, document.createElement('div'), document.createElement('pre')]) {
      check(CodeBlocks.mount(input) === null, 'invalid/detached admission');
    }
    const code = document.createElement('code');
    for (const [classes,expected] of [['language-js','javascript'],['language-xml','markup'],['cmd','batch'],['vb','visual-basic'],['unknown','none'],['','none']]) {
      code.className = classes;
      check(CodeBlocks.language(code) === expected, 'language hint: '+classes);
    }
  }

  async function normalization() {
    const f = fixture('before <code class="js">const x = <b>1</b>;</code> after');
    try {
      check(f.pre.children.length === 1, 'one normalized code element');
      check(f.code.textContent === 'before const x = 1; after', 'exact normalized text');
      check(f.code.classList.contains('language-javascript'), 'language normalization');
      check(f.code.querySelector('b')?.textContent === '1', 'kept authored markup');
      check(f.code.querySelector('.token'), 'real Prism tokenization');
      check(f.button.getAttribute('type') === 'button', 'button type');
      check(f.button.querySelector('span').getAttribute('aria-live') === 'polite', 'announcement contract');
    } finally {await release(f);}
  }

  async function success() {
    const f = fixture();
    try {
      f.button.click();
      await tick();
      check(requests.length === 1, 'single clipboard admission');
      check(requests[0].text === '  exact & text\n', 'exact clipboard text');
      check(f.button.disabled, 'pending write disables button');
      f.button.dispatchEvent(new Event('click'));
      check(requests.length === 1, 'disabled synthetic click rejected');
      requests[0].resolve();
      await tick();
      check(f.button.textContent === 'Listo', 'success label');
      check(!f.button.disabled, 'settled write re-enables button');
      await waitState(f.button, 'copy');
      check(f.button.textContent === 'Copiar', 'owned reset timer');
    } finally {await release(f);}
  }

  async function rejection() {
    const f = fixture();
    try {
      f.button.click();await tick();
      requests[0].reject(new Error('clipboard denied'));
      await tick();
      check(f.button.textContent === 'Error', 'rejection label');
      check(!f.button.disabled, 'rejection settles disabled state');
      await waitState(f.button, 'copy');
      throwClipboard = true;
      f.button.click();await tick();
      check(f.button.textContent === 'Error', 'synchronous clipboard rejection');
    } finally {await release(f);}
  }

  async function defaultLabels() {
    const f = fixture('default text', false);
    try {
      check(f.button.textContent === 'Copy', 'default copy label');
      f.button.click();await tick();requests[0].resolve();await tick();
      check(f.button.textContent === 'Copied!', 'default success label');
    } finally {await release(f);}
  }

  async function cutoffBeforeWrite() {
    const f = fixture();
    try {
      f.button.click();f.controller.dispose();await tick();
      check(requests.length === 0, 'disposed controller cannot start native write');
      f.button.dispatchEvent(new Event('click'));await tick();
      check(requests.length === 0, 'aborted listener cannot admit work');
    } finally {await release(f);}
  }

  async function staleSettlement(reject) {
    const f = fixture();
    try {
      f.button.click();await tick();
      const request = requests[0], previous = f.controller, oldButton = f.button;
      f.controller = CodeBlocks.mount(f.pre);
      f.wrapper = f.pre.parentElement;
      f.button = f.wrapper.querySelector('button');
      previous.dispose();
      check(f.pre.parentElement === f.wrapper, 'stale dispose preserves current wrapper');
      if (reject) request.reject(new Error('late denial'));else request.resolve();
      await tick();
      check(oldButton.disabled, 'retired button remains disabled');
      check(f.button.textContent === 'Copiar', 'late settlement preserves replacement label');
      check(!f.button.disabled, 'late settlement preserves replacement admission');
      f.button.click();await tick();
      check(requests.length === 2, 'replacement remains usable');
    } finally {await release(f);}
  }

  async function detachedAdmission() {
    const f = fixture();
    try {
      f.pre.remove();
      f.button.dispatchEvent(new Event('click'));await tick();
      check(requests.length === 0, 'detached code cannot admit clipboard work');
    } finally {await release(f);}
  }

  async function movedWrapper() {
    const f = fixture();
    try {
      document.body.append(f.pre);
      f.controller.dispose();
      check(f.wrapper.isConnected, 'foreign wrapper relation preserved');
      check(f.pre.parentElement === document.body, 'moved pre preserved');
    } finally {await release(f);}
  }

  async function changedWrapperClass() {
    const f = fixture();
    try {
      f.wrapper.classList.remove('code-toolbar');
      f.controller.dispose();
      check(f.pre.parentElement === f.wrapper, 'changed wrapper preserved');
    } finally {await release(f);}
  }

  async function staleTimer() {
    const f = fixture();
    try {
      f.button.click();await tick();requests[0].resolve();await tick();
      check(f.button.dataset.copyState === 'copy-success', 'timer admitted');
      f.pre.remove();
      await new Promise(resolve => setTimeout(resolve, 40));
      check(f.button.dataset.copyState === 'copy-success', 'stale timer cannot mutate DOM');
    } finally {await release(f);}
  }

  async function initialization() {
    const host = document.createElement('section');
    host.id = 'code-admission';
    host.innerHTML = '<pre>first</pre><pre><code>second</code></pre><div>skip</div>';
    document.body.append(host);
    const initial = CodeBlocks.init(document);
    const controllers = CodeBlocks.init(document, '#code-admission pre,#code-admission div');
    try {
      check(controllers.length === 2, 'init filters invalid nodes');
      check(host.querySelectorAll('.copy-to-clipboard-button').length === 2, 'init wired toolbar');
    } finally {
      for (const controller of controllers) controller.dispose();
      for (const controller of initial) controller.dispose();
      host.remove();
    }
  }

  async function normal() {
    const cases = [admission,normalization,success,rejection,defaultLabels,cutoffBeforeWrite,
      detachedAdmission,movedWrapper,changedWrapperClass,staleTimer,initialization];
    for (const run of cases) {
      await run();
      console.log('[BUILD-013] settled '+run.name);
    }
    await staleSettlement(false);await staleSettlement(true);
    return [...cases.map(run=>run.name), 'stale-success', 'stale-error'];
  }

  async function run() {
    if (mode === 'missing-prism') {
      check(typeof Prism === 'undefined', 'missing Prism guard');return [mode];
    }
    if (mode === 'missing-toolbar') {
      check(!Prism.plugins.copyToClipboard, 'missing toolbar guard');return [mode];
    }
    if (mode === 'unsupported') {
      const f = fixture();
      try {check(!f.button, 'unsupported clipboard has no copy button');}
      finally {await release(f);}
      return [mode];
    }
    return normal();
  }
  return {run};
})();

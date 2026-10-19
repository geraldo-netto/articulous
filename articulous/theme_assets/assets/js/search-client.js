/* Optional search controller. Callers own paths, matching, rendering and UI text. */
globalThis.SearchClient = (() => {
  function validTags(tags) {
    return tags == null || (Array.isArray(tags) && tags.every(tag => typeof tag === 'string'));
  }

  function validateRow(item) {
    if (!item || typeof item.url !== 'string' || !item.url.trim() ||
        typeof item.title !== 'string' || typeof item.description !== 'string' || !validTags(item.tags)) {
      throw new Error('Invalid search entry');
    }
  }

  function prepareRow(item, origin, prepare) {
    validateRow(item);
    const url = new URL(item.url, origin);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Invalid search URL');
    const tags = Object.freeze([...(item.tags || [])]);
    const metadata = prepare(item, url);
    return Object.freeze({...metadata, url:item.url, title:item.title, description:item.description, tags,
      haystack:[item.title, item.description, ...tags].join(' ').toLocaleLowerCase()});
  }

  function prepareIndex(data, origin, prepare) {
    if (!Array.isArray(data)) throw new Error('Invalid search index');
    return Object.freeze(data.map(item => prepareRow(item, origin, prepare)));
  }

  function normalizeSlug(name) {
    return String(name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
  }

  function yieldTask(signal) {
    return new Promise((resolve,reject) => {
      const channel = new MessageChannel();
      function finish(error) {
        channel.port1.onmessage = null;
        channel.port1.close(); channel.port2.close();
        signal.removeEventListener('abort', abort);
        error ? reject(error) : resolve();
      }
      const abort = () => finish();
      channel.port1.onmessage = () => finish();
      signal.addEventListener('abort', abort, {once:true});
      try {
        if (signal.aborted) finish();
        else channel.port2.postMessage(null);
      } catch (error) { finish(error); }
    });
  }

  function create({origin, load, prepare, select, match, renderer, batchSize=200, schedule=yieldTask}) {
    if (!Number.isSafeInteger(batchSize) || batchSize < 1) throw new RangeError('Invalid search batch size');
    const lifetime = new AbortController();
    let entries, request, revision=0, closed=false;
    const active = current => !closed && current === revision;

    function reset() {
      if (closed) return;
      revision++;
      renderer.clear();
    }

    function dispose() {
      if (closed) return;
      closed=true;revision++;
      lifetime.abort();
      entries=undefined;request=null;renderer=null;
      load=null;prepare=null;select=null;match=null;schedule=null;
    }

    function prepareActive(item, url) {
      if (closed) throw new Error('Search disposed');
      return prepare(item, url);
    }

    function selectedIndex(data) {
      if (closed) throw new Error('Search disposed');
      const prepared=prepareIndex(data, origin, prepareActive);
      if (closed) throw new Error('Search disposed');
      return select(prepared);
    }

    function startLoad() {
      try {return Promise.resolve(load(lifetime.signal));}
      catch (error) {return Promise.reject(error);}
    }

    function loadEntries() {
      if (entries !== undefined) return Promise.resolve(entries);
      request ||= startLoad().then(selectedIndex).then(items => {
        if (!closed) entries=items;
        return items;
      }).catch(error => { request=null;throw error; });
      return request;
    }

    function matching(items, query) {
      const matches = match(items, query);
      if (!Array.isArray(matches)) throw new TypeError('Search matching must return an array');
      return matches;
    }

    function appendBatch(container, items, current) {
      for (const item of items) {
        if (!active(current)) return false;
        renderer.append(container, item);
      }
      return true;
    }

    async function renderMatches(matches, current) {
      const container = renderer.create();
      for (let offset=0;offset<matches.length;offset+=batchSize) {
        if (!active(current)) return null;
        if (offset) await schedule(lifetime.signal);
        if (!active(current)) return null;
        if (!appendBatch(container, matches.slice(offset,offset+batchSize),current)) return null;
      }
      return container;
    }

    async function search(query) {
      if (closed) return;
      if (typeof query !== 'string') throw new TypeError('Search query must be text');
      if (!query) {reset();return;}
      const current=++revision;
      renderer.loading();
      try {
        if (!active(current)) return;
        const items=await loadEntries();
        if (!active(current)) return;
        const matches=matching(items,query);
        const container=await renderMatches(matches,current);
        if (active(current)) renderer.publish(container,matches.length);
      } catch (error) {
        if (active(current)) renderer.failed(error);
      }
    }
    return {search,reset,dispose};
  }
  return {create,prepareIndex,normalizeSlug};
})();

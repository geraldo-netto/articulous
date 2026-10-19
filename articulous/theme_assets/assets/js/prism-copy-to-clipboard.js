(function () {

	if (typeof Prism === 'undefined' || typeof document === 'undefined') {
		return;
	}

	if (!Prism.plugins.toolbar) {
		console.warn('Copy to Clipboard plugin loaded before Toolbar plugin.');

		return;
	}

	/**
	 * When the given elements is clicked by the user, the given text will be copied to clipboard.
	 *
	 * @param {HTMLElement} element
	 * @param {CopyInfo} copyInfo
	 *
	 * @typedef CopyInfo
	 * @property {() => string} getText
	 * @property {() => void} success
	 * @property {(reason: unknown) => void} error
	 */
	function registerClipboard(element, copyInfo, signal) {
		element.addEventListener('click', function () {
			if (!copyInfo.active() || element.disabled) { return; }
			element.disabled = true;
			copyTextToClipboard(copyInfo).finally(function () {
				if (copyInfo.active()) { element.disabled = false; }
			});
		}, { signal: signal });
	}

	function copyTextToClipboard(copyInfo) {
		return Promise.resolve().then(function () {
			if (copyInfo.active()) {
				return navigator.clipboard.writeText(copyInfo.getText());
			}
		}).then(copyInfo.success, copyInfo.error);
	}

	var owners = new WeakMap();
	Prism.plugins.copyToClipboard = {
		dispose: function (element) {
			var owner = owners.get(element);
			if (owner) { owner.dispose(); }
		}
	};

	/**
	 * Traverses up the DOM tree to find data attributes that override the default plugin settings.
	 *
	 * @param {Element} startElement An element to start from.
	 * @returns {Settings} The plugin settings.
	 * @typedef {Record<"copy" | "copy-error" | "copy-success" | "copy-timeout", string | number>} Settings
	 */
	function getSettings(startElement) {
		/** @type {Settings} */
		var settings = {
			'copy': 'Copy',
			'copy-error': 'Press Ctrl+C to copy',
			'copy-success': 'Copied!',
			'copy-timeout': 5000
		};

		var prefix = 'data-prismjs-';
		for (var key in settings) {
			var attr = prefix + key;
			var element = startElement;
			while (element && !element.hasAttribute(attr)) {
				element = element.parentElement;
			}
			if (element) {
				settings[key] = element.getAttribute(attr);
			}
		}
		return settings;
	}

	Prism.plugins.toolbar.registerButton('copy-to-clipboard', function (env) {
		if (typeof navigator.clipboard?.writeText !== 'function') { return; }
		var element = env.element;
		var pre = element.parentElement;
		var wrapper = pre.parentElement;
		Prism.plugins.copyToClipboard.dispose(element);
		var settings = getSettings(element);
		var linkCopy = document.createElement('button');
		linkCopy.className = 'copy-to-clipboard-button';
		linkCopy.setAttribute('type', 'button');
		var linkSpan = document.createElement('span');
		linkSpan.setAttribute('aria-live', 'polite');
		linkCopy.appendChild(linkSpan);
		var listener = new AbortController();
		var timer;
		var owner = { dispose: dispose };
		owners.set(element, owner);
		setState('copy');

		registerClipboard(linkCopy, {
			active: active,
			getText: function () { return element.textContent; },
			success: function () {
				if (!active()) { return; }
				setState('copy-success');
				resetText();
			},
			error: function () {
				if (!active()) { return; }
				setState('copy-error');
				resetText();
			}
		}, listener.signal);
		return linkCopy;

		function active() {
			return owners.get(element) === owner && element.isConnected && linkCopy.isConnected
				&& element.parentElement === pre && pre.parentElement === wrapper && wrapper.contains(linkCopy);
		}

		function dispose() {
			listener.abort();
			clearTimeout(timer);
			linkCopy.disabled = true;
			if (owners.get(element) === owner) { owners.delete(element); }
		}

		function resetText() {
			clearTimeout(timer);
			timer = setTimeout(function () {
				if (active()) { setState('copy'); }
			}, settings['copy-timeout']);
		}

		function setState(state) {
			linkSpan.textContent = settings[state];
			linkCopy.setAttribute('data-copy-state', state);
		}
	});
}());

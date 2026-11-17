/* Shared transport for synchronized slides and the mobile remote. */
(() => {
  const presenter = new URLSearchParams(location.search).get('presenter') === '1';
  const isDeck = !!document.querySelector('.slide');
  let state = null;
  let connected = false;
  let queue = Promise.resolve();
  let receivedAt = 0;
  const listeners = new Set();

  async function request(path, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(path, {
        method: payload === undefined ? 'GET' : 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: payload === undefined ? {} : { 'Content-Type': 'application/json', 'X-Mdslides': '1' },
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error || `Erreur HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Le serveur ne repond pas.');
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  const status = document.createElement('div');
  if (isDeck) {
    const style = document.createElement('style');
    style.textContent = `
      body { overflow: hidden; }
      .slide { touch-action: none; }
      .network-status { position: fixed; bottom: 12px; left: 12px; z-index: 10000;
        padding: 8px 12px; border-radius: 8px; background: #172033; color: white;
        font: 14px system-ui; }
      .network-status:empty { display: none; }
      body.network-audience :is(.notes-toggle, .notes-panel, .toc-toggle, .toc-panel) { display: none !important; }
      body.network-audience .timer-toggle { pointer-events: none; }
      @media print { .network-status { display: none; } }
    `;
    document.head.append(style);
    status.className = 'network-status';
    status.setAttribute('role', 'status');
    status.dataset.noNav = 'true';
    document.body.append(status);
    document.body.classList.toggle('network-audience', !presenter);
  }

  function notify(error = '') {
    if (isDeck) {
      status.textContent = error || (
        presenter && !state?.authorized ? 'Acces presentateur non authentifie. Ouvrez le lien indique dans le terminal.' : ''
      );
    }
    for (const listener of listeners) listener(state, connected, error);
  }

  function accept(next) {
    if (state && next.instance === state.instance && next.revision < state.revision) return;
    state = next;
    receivedAt = performance.now();
    connected = true;
    if (isDeck) {
      network.applying = true;
      try {
        // Private notes are only rendered in an authenticated presenter view.
        window.mdslides.applyState(presenter ? next : { ...next, notes: undefined });
      } finally {
        network.applying = false;
      }
    }
    notify();
  }

  const network = {
    applying: false,
    request,
    get state() { return state; },
    get connected() { return connected; },
    get elapsed() {
      return state ? state.elapsed + (state.running ? (performance.now() - receivedAt) / 1000 : 0) : 0;
    },
    subscribe(listener) {
      listeners.add(listener);
      if (state) listener(state, connected, '');
    },
    refresh: async () => {
      accept(await request('/api/state'));
      return state;
    },
    command(payload) {
      if (!connected || !state?.authorized || (isDeck && !presenter)) return Promise.resolve();
      // Serialize clicks; "next" is evaluated atomically on the server.
      const pending = queue.then(async () => {
        try {
          accept(await request('/api/command', payload));
        } catch (error) {
          connected = false;
          notify(error.message);
          throw error;
        }
      });
      queue = pending.catch(() => {});
      // Event handlers do not consume promises; failures are shown by notify.
      return pending.catch(() => {});
    },
    navigate(index) {
      if (!state) return;
      if (presenter && state.authorized) {
        network.command({ action: 'goto', index: Math.max(0, Math.min(index, state.total - 1)) });
      } else {
        network.applying = true;
        try { window.mdslides.applyState({ ...state, notes: undefined }); } finally { network.applying = false; }
      }
    },
  };
  window.mdslidesNetwork = network;

  async function poll() {
    try {
      await network.refresh();
    } catch (error) {
      connected = false;
      notify(`Connexion perdue : ${error.message} Reconnexion automatique...`);
    }
    setTimeout(poll, 300);
  }
  poll();
})();

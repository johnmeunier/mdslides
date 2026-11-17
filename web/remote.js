(() => {
  const network = window.mdslidesNetwork;
  const login = document.querySelector('#login');
  const controls = document.querySelector('#controls');
  const status = document.querySelector('#status');
  const timer = document.querySelector('#timer');
  const password = document.querySelector('#password');
  const notes = document.querySelector('#notes');
  const presenter = new URLSearchParams(location.search).get('mode') === 'presenter';
  let authenticating = false;
  let redirecting = false;
  let authError = '';
  let notesIndex = null;
  // Fragment credentials are never sent in URLs or referrers.
  const token = new URLSearchParams(location.hash.slice(1)).get('token');
  history.replaceState(null, '', location.pathname + location.search);

  function update(state, connected, error) {
    const authorized = !!state?.authorized;
    login.hidden = authorized || authenticating;
    controls.hidden = !authorized || presenter;
    status.textContent = authError || error || (authorized ? '' : 'Connectez-vous pour acceder aux commandes et aux notes.');
    status.hidden = !status.textContent;
    for (const button of controls.querySelectorAll('button')) button.disabled = !connected || !authorized;
    if (!authorized) {
      notes.textContent = '';
      notesIndex = null;
      return;
    }
    if (presenter) {
      if (!redirecting) {
        redirecting = true;
        location.replace('/slides?presenter=1');
      }
      return;
    }
    document.querySelector('#position').textContent = `Slide ${state.index + 1} / ${state.total}`;
    const text = state.notes.length
      ? state.notes.join('\n\n') : 'Aucune note pour cette slide.';
    if (notes.textContent !== text) notes.textContent = text;
    if (notesIndex !== state.index) notes.scrollTop = 0;
    notesIndex = state.index;
    const actions = controls.querySelectorAll('[data-action]');
    for (const button of actions) {
      const atStart = state.index === 0 && ['previous', 'first'].includes(button.dataset.action);
      const atEnd = state.index === state.total - 1 && ['next', 'last'].includes(button.dataset.action);
      button.disabled = !connected || atStart || atEnd || (button === timer && !state.duration);
    }
    renderTimer();
  }

  async function authenticate(payload) {
    authenticating = true;
    authError = '';
    login.hidden = true;
    status.hidden = false;
    status.textContent = 'Authentification...';
    try {
      await network.request('/api/auth', payload);
      password.value = '';
      await network.refresh();
    } catch (error) {
      authError = error.message;
    } finally {
      authenticating = false;
      update(network.state, network.connected, '');
    }
  }

  network.subscribe(update);
  login.addEventListener('submit', event => {
    event.preventDefault();
    authenticate({ password: password.value });
  });
  controls.addEventListener('click', event => {
    const button = event.target.closest('[data-action]');
    if (button) network.command({ action: button.dataset.action });
  });
  function renderTimer() {
    const state = network.state;
    if (!state?.authorized || !state.duration) {
      timer.textContent = 'Sans timer';
      timer.classList.remove('expired');
      return;
    }
    const seconds = Math.ceil(Math.max(0, state.duration - network.elapsed));
    timer.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    timer.classList.toggle('expired', seconds === 0);
  }
  setInterval(renderTimer, 200);
  if (token) authenticate({ token });
})();

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../web/client.js', import.meta.url), 'utf8');

async function client({ deck = true, presenter = false, authorized = true } = {}) {
  let serverState = {
    index: 0, total: 3, duration: 60, elapsed: 0, running: false,
    revision: 0, instance: 'first-server', authorized, notes: ['Private note'],
  };
  const applied = [];
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  let failure = false;
  const window = { mdslides: { applyState: state => applied.push(structuredClone(state)) } };
  const element = () => ({ setAttribute() {}, dataset: {}, textContent: '' });
  const context = vm.createContext({
    window, location: { search: presenter ? '?presenter=1' : '' },
    document: {
      querySelector: () => deck ? {} : null,
      createElement: element, head: { append() {} },
      body: { append() {}, classList: { toggle() {} } },
    },
    URLSearchParams, AbortController, performance: { now: () => 0 },
    setTimeout(callback, delay) { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(path, options) {
      if (failure) throw new Error('Offline');
      if (path === '/api/command') {
        const payload = JSON.parse(options.body);
        requests.push(payload);
        serverState = { ...serverState, index: serverState.index + 1, revision: serverState.revision + 1 };
      }
      return { ok: true, status: 200, json: async () => structuredClone(serverState) };
    },
  });
  vm.runInContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return {
    network: window.mdslidesNetwork, applied, requests,
    setState(state) { serverState = { ...serverState, ...state }; },
    fail(value) { failure = value; },
    async poll() {
      const [id, timer] = [...timers].find(([, value]) => value.delay === 300);
      timers.delete(id);
      await timer.callback();
    },
  };
}

test('audience stays read-only and never renders notes, including after manual scrolling', async () => {
  const viewer = await client();
  assert.equal(viewer.applied.at(-1).notes, undefined);
  await viewer.network.command({ action: 'next' });
  viewer.network.navigate(1);
  assert.deepEqual(viewer.requests, []);
  assert.equal(viewer.applied.at(-1).index, 0);
  assert.equal(viewer.applied.at(-1).notes, undefined);
});

test('authenticated presenter renders notes and serializes rapid navigation commands', async () => {
  const presenter = await client({ presenter: true });
  assert.deepEqual(presenter.applied.at(-1).notes, ['Private note']);
  await Promise.all([
    presenter.network.command({ action: 'next' }),
    presenter.network.command({ action: 'next' }),
  ]);
  assert.equal(presenter.network.state.index, 2);
  assert.equal(presenter.requests.length, 2);
});

test('old responses cannot rewind slides, but a restarted server resets state', async () => {
  const viewer = await client();
  viewer.setState({ index: 2, revision: 8 });
  await viewer.poll();
  viewer.setState({ index: 1, revision: 7 });
  await viewer.poll();
  assert.equal(viewer.network.state.index, 2);
  viewer.setState({ index: 0, revision: 0, instance: 'restarted-server' });
  await viewer.poll();
  assert.equal(viewer.network.state.index, 0);
  assert.equal(viewer.applied.at(-1).index, 0);
});

test('connection failure is surfaced, blocks commands, and polling reconnects automatically', async () => {
  const remote = await client({ deck: false });
  let message = '';
  remote.network.subscribe((_state, _connected, error) => { message = error; });
  remote.fail(true);
  await remote.poll();
  assert.equal(remote.network.connected, false);
  assert.match(message, /Offline/);
  await remote.network.command({ action: 'next' });
  assert.equal(remote.requests.length, 0);
  remote.fail(false);
  await remote.poll();
  assert.equal(remote.network.connected, true);
  assert.equal(message, '');
  await remote.network.command({ action: 'next' });
  assert.equal(remote.network.state.index, 1);
});

function remote() {
  const elements = new Map();
  for (const id of ['login', 'controls', 'status', 'timer', 'password', 'notes', 'position']) {
    elements.set(`#${id}`, {
      textContent: '', hidden: false, disabled: false, scrollTop: 0,
      classList: { remove() {}, toggle() {} },
      handlers: {},
      addEventListener(event, handler) { this.handlers[event] = handler; },
    });
  }
  const timer = elements.get('#timer');
  timer.dataset = { action: 'reset_timer' };
  const buttons = [timer, ...['first', 'previous', 'next', 'last'].map(action => ({
    dataset: { action }, disabled: false,
  }))];
  elements.get('#controls').querySelectorAll = () => buttons;
  let subscriber;
  const commands = [];
  const network = {
    state: null, elapsed: 15,
    subscribe(callback) { subscriber = callback; },
    command(payload) { commands.push(payload); },
  };
  vm.runInNewContext(readFileSync(new URL('../web/remote.js', import.meta.url), 'utf8'), {
    window: { mdslidesNetwork: network },
    document: { querySelector: selector => elements.get(selector) },
    location: { search: '?mode=remote', hash: '', pathname: '/' },
    history: { replaceState() {} }, URLSearchParams, setInterval() {},
  });
  return {
    elements, buttons, commands,
    update(overrides = {}, connected = true, error = '') {
      network.state = { authorized: true, index: 1, total: 3, duration: 60, notes: ['Private'], ...overrides };
      subscriber(network.state, connected, error);
    },
  };
}

test('remote resets timer by clicking its display and shows errors only when needed', () => {
  const view = remote();
  view.update();
  assert.equal(view.elements.get('#status').hidden, true);
  assert.equal(view.elements.get('#timer').textContent, '0:45');
  assert.equal(view.elements.get('#position').textContent, 'Slide 2 / 3');
  const timer = view.elements.get('#timer');
  view.elements.get('#controls').handlers.click({ target: { closest: () => timer } });
  assert.equal(view.commands[0].action, 'reset_timer');
  view.update({}, false, 'Connexion perdue');
  assert.equal(view.elements.get('#status').hidden, false);
  assert.equal(view.elements.get('#status').textContent, 'Connexion perdue');
  assert.ok(view.buttons.every(button => button.disabled));
  view.update({ duration: 0 });
  assert.equal(timer.disabled, true);
  assert.equal(timer.textContent, 'Sans timer');
});

test('remote preserves notes scroll during synchronization and resets it on slide changes', () => {
  const view = remote();
  const notes = view.elements.get('#notes');
  view.update();
  notes.scrollTop = 150;
  view.update();
  assert.equal(notes.scrollTop, 150);
  view.update({ index: 2 });
  assert.equal(notes.scrollTop, 0);
  view.update({ authorized: false });
  assert.equal(notes.textContent, '');
  assert.equal(view.elements.get('#controls').hidden, true);
  assert.equal(view.elements.get('#login').hidden, false);
});

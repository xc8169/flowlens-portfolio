/** Controller integration with a small DOM adapter; no browser/network required. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setImmediate as settle } from 'node:timers/promises';

class Node {
  constructor(id = '') { this.id = id; this.children = []; this.listeners = {}; this.attributes = {}; this.hidden = false; this.value = ''; this.textContent = ''; }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key]; }
  removeAttribute(key) { delete this.attributes[key]; }
  append(node) { this.children.push(node); }
  replaceChildren() { this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  async fire(name) { await this.listeners[name]?.({ target: this }); await settle(); }
}

test('viewer controller loads real exports, navigates, imports, and preserves results on errors', async () => {
  const nodes = new Map();
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, new Node(id));
    return nodes.get(id);
  };
  get('profile').attributes.viewBox = '0 0 440 300';
  get('interface-chart').attributes.viewBox = '0 0 600 230';
  globalThis.document = { getElementById: get, createElementNS: () => new Node() };
  globalThis.window = { addEventListener() {} };
  const data = JSON.parse(readFileSync(new URL('../demo/timeline.json', import.meta.url), 'utf8'));
  globalThis.fetch = async () => ({ ok: true, json: async () => structuredClone(data) });
  await import('../app.js');
  await settle();
  assert.match(get('motion').textContent, /^2\.000 px\/frame$/);
  assert.match(get('pair-info').textContent, /Pair 1 \/ 12/);
  assert.equal(get('previous').disabled, true);
  assert.ok(get('profile').children.some((node) => node.attributes.d));
  await get('next').fire('click');
  assert.match(get('pair-info').textContent, /Pair 2 \/ 12/);
  await get('toggle').fire('click');
  assert.match(get('frame-info').textContent, /selected pair B/);
  get('pair').value = '4'; await get('pair').fire('input');
  assert.match(get('pair-info').textContent, /Pair 5 \/ 12/);
  assert.match(get('frame-info').textContent, /selected pair A/);

  const file = (name, value) => ({ name, size: 200, text: async () => JSON.stringify(value) });
  const frame = { frame: 5, original_frame: 5, seconds_from_start: 0, median_row_px: 42,
    coverage: 0.8, x: [0, 100], y: [42, 43] };
  get('files').files = [file('timeline.json', data), file('interface.json', {
    frames: [frame], runtime: { device: 'cpu', fallback_reason: 'CUDA unavailable' },
  })];
  await get('files').fire('change');
  assert.equal(get('device').textContent, 'CPU');
  assert.equal(get('fallback').textContent, 'CUDA unavailable');
  assert.match(get('interface-info').textContent, /Frame A boundary row: 42.0/);
  assert.equal(get('frame-missing').hidden, false);
  const previous = get('pair-info').textContent;
  get('files').files = [file('timeline.json', { bad: true })];
  await get('files').fire('change');
  assert.equal(get('error').hidden, false);
  assert.equal(get('pair-info').textContent, previous);

  // An old slow demo fetch cannot overwrite a newer local file selection.
  let release;
  globalThis.fetch = () => new Promise((resolve) => { release = resolve; });
  const pending = get('demo').fire('click');
  get('files').files = [file('timeline.json', data), file('interface.json', { frames: [frame], runtime: { device: 'cpu' } })];
  await get('files').fire('change');
  release({ ok: true, json: async () => structuredClone(data) });
  await pending;
  assert.equal(get('device').textContent, 'CPU');
});

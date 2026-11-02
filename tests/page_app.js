// The page in an app (?app), run in node with a small stand-in for the browser: what it tells the
// app, and how it draws what the app gives it. tests/test_page_app.py runs it; it prints the
// results as JSON.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const web = path.join(__dirname, '..', 'plugins', 'page', 'web');
const theme = process.argv[2] || 'orb';

// --- A small DOM: elements with attributes, classes, children, styles and listeners ---
class Element {
  constructor(tag, attrs) {
    this.tagName = tag.toUpperCase();
    this.attrs = Object.assign({}, attrs || {});
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.hidden = false;
    this.style = { setProperty() {}, removeProperty() {} };
    this._text = '';
    this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0;
    this.classList = {
      set: new Set(),
      add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); },
      contains(c) { return this.set.has(c); },
      toggle(c, on) { if (on === undefined) on = !this.set.has(c); if (on) this.set.add(c); else this.set.delete(c); return on; }
    };
  }
  get id() { return this.attrs.id || ''; }
  set id(v) { this.attrs.id = v; }
  get className() { return [...this.classList.set].join(' '); }
  set className(v) { this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; }
  get firstChild() { return this.children[0] || null; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(html) {  // only what themes and theme.js write: elements with data-block / data-part
    this.children = [];
    this._text = '';
    const found = /<(\w+)([^>]*)>/g;
    let m;
    while ((m = found.exec(html))) {
      const attrs = {};
      m[2].replace(/([\w-]+)="([^"]*)"/g, (_, k, v) => { attrs[k] = v; });
      if (attrs['data-block'] || attrs['data-part'] || m[1] === 'img' || m[1] === 'video') this.appendChild(new Element(m[1], attrs));
    }
  }
  get innerHTML() { return ''; }
  addEventListener(type, f) { (this.listeners[type] = this.listeners[type] || []).push(f); }
  dispatch(type, ev) { (this.listeners[type] || []).forEach((f) => f(ev)); if (this['on' + type]) this['on' + type](ev); }
  all() { return this.children.reduce((list, c) => list.concat([c], c.all()), []); }
  querySelectorAll(selector) {
    const tests = selector.split(',').map((s) => s.trim()).map((s) => {
      const m = /^\[([\w-]+)="([^"]*)"\]$/.exec(s);
      if (m) return (e) => e.attrs[m[1]] === m[2];
      const tag = /^(\w+)$/.exec(s);
      if (tag) return (e) => e.tagName === tag[1].toUpperCase();
      const attr = /^\[([\w-]+)\]$/.exec(s);
      if (attr) return (e) => attr[1] in e.attrs;
      throw new Error('selector ' + s);
    });
    return this.all().filter((e) => tests.some((t) => t(e)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest() { return null; }
  getBoundingClientRect() { return { top: 100, bottom: 200, left: 10, right: 330, width: 320, height: 100 }; }
  get offsetParent() { return this.hidden ? null : {}; }
  getClientRects() { return []; }
}

const body = new Element('body');
const html = new Element('html');
const byId = {};
['start', 'pair', 'pair-prompt', 'pair-code', 'pair-button', 'pair-error', 'screen', 'speaker', 'theme-css']
  .forEach((id) => { byId[id] = body.appendChild(new Element(id === 'screen' ? 'div' : 'p', { id })); });
byId.screen.hidden = true;

const sent = [];  // what the page told the app
const config = {
  lang: 'es', ui: { asleep: 'Di «{wake}»', thinking: 'Pensando…', connecting: 'Conectando…' },
  name: 'Eva', wake_phrase: 'Oye, Eva', screen: { show_heard: true, show_answer: true, history: 2 },
  theme: { name: theme, version: 1, css: '/theme/' + theme + '/theme.css', options: {}, texts: {}, ui: {},
           html: '<div data-block="face"></div><p data-block="status"></p><div data-block="timers"></div>' +
                 '<div data-block="captions"></div>' }
};
const fetched = [];

const timers = [];
const context = {
  console,
  location: { search: '?app&theme=' + theme, pathname: '/' },
  URLSearchParams,
  JSON, Math, Date, String, Number, Object, Array, Error, Promise, Set, Uint8Array, parseFloat,
  setTimeout: (f, ms) => { timers.push({ f, ms }); return timers.length; },
  clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].f = null; },
  setInterval: () => 0,
  clearInterval: () => {},
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: () => {},
  addEventListener: () => {},
  getComputedStyle: () => ({ lineHeight: '20px', fontSize: '16px' }),
  innerWidth: 400, innerHeight: 800,
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  navigator: {},
  performance: { now: () => 0 },
  fetch: (url) => { fetched.push(url); return Promise.resolve({ json: () => Promise.resolve(config) }); },
  webkit: { messageHandlers: { anyassistant: { postMessage: (m) => sent.push(JSON.parse(JSON.stringify(m))) } } },
  document: {
    body, documentElement: Object.assign(html, { style: { setProperty() {} } }),
    getElementById: (id) => byId[id] || null,
    createElement: (tag) => new Element(tag),
    createRange: () => ({ setStart() {}, setEnd() {}, getClientRects: () => [] }),
    addEventListener: () => {},
    fullscreenElement: null
  }
};
context.window = context;
vm.createContext(context);
for (const file of ['theme.js', 'app.js']) vm.runInContext(fs.readFileSync(path.join(web, file), 'utf8'), context, { filename: file });

const later = (f) => new Promise((resolve) => setImmediate(() => resolve(f())));
const block = (name) => byId.screen.querySelector('[data-block="' + name + '"]');

later(() => null).then(() => later(() => {
  const out = { fetched, sent: sent.slice(), screenShown: !byId.screen.hidden, appClass: body.classList.contains('app') };
  const receive = context.AnyAssistant.receive;
  receive({ type: 'state', state: 'thinking' });
  out.thinking = { state: body.getAttribute('data-state'), status: block('status').textContent };
  receive({ type: 'text', text: '¿Qué hora es?' });
  receive({ type: 'text', text: 'Son las diez.', author: 'assistant', id: 7 });
  out.captions = block('captions').children.map((p) => [p.textContent, p.className]);
  receive({ type: 'problem', text: 'Buscando el servidor…' });
  out.problem = { state: body.getAttribute('data-state'), status: block('status').textContent };
  receive({ type: 'problem', text: null });
  out.cleared = { state: body.getAttribute('data-state'), status: block('status').textContent };
  receive({ type: 'state', state: 'asleep' });
  out.asleep = block('status').textContent;
  receive({ type: 'state', state: 'awake' });
  sent.length = 0;
  receive({ type: 'camera', on: true });
  receive({ type: 'camera', on: false });
  out.cameraMessages = sent.slice();
  receive({ type: 'levels', voice: 0.5, speech: 0.25 });
  sent.length = 0;
  byId.screen.dispatch('click', {});
  out.tap = sent.slice();
  sent.length = 0;
  byId.screen.dispatch('touchstart', { touches: [{ clientX: 50, clientY: 50 }] });
  timers.filter((t) => t.f && t.ms === 800).forEach((t) => { const f = t.f; t.f = null; f(); });
  byId.screen.dispatch('click', {});
  out.held = sent.slice();
  return out;
})).then((out) => {
  process.stdout.write(JSON.stringify(out));
}).catch((e) => { console.error(e); process.exit(1); });

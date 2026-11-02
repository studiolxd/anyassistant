// AnyAssistant's admin page (/admin): what the Mac app shows, for Windows, Linux and a Linux with
// no screen. Over the same routes (/admin/settings, /admin/plugins, /devices, /pairing,
// /admin/voices, /admin/mail). Texts: English as the key, the server's language from /admin/me.

var texts = {};
function T(english) { return texts[english] || english; }
function $(selector, root) { return (root || document).querySelector(selector); }
function el(tag, attributes, children) {
  var made = document.createElement(tag);
  Object.keys(attributes || {}).forEach(function (key) {
    if (key === 'text') made.textContent = attributes[key];
    else if (key.slice(0, 2) === 'on') made.addEventListener(key.slice(2), attributes[key]);
    else if (attributes[key] !== null && attributes[key] !== undefined && attributes[key] !== false) made.setAttribute(key, attributes[key]);
  });
  (children || []).forEach(function (child) {
    if (child !== null && child !== undefined) made.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  });
  return made;
}
function api(method, path, body) {
  return fetch(path, {
    method: method, credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (r.status === 403 && data.owner === false) { showLogin(); throw new Error('not the owner'); }
      data._status = r.status;
      return data;
    });
  });
}
function ago(seconds) {
  if (!seconds) return '';
  var s = Date.now() / 1000 - seconds;
  if (s < 90) return T('just now');
  if (s < 5400) return Math.round(s / 60) + ' min';
  if (s < 129600) return Math.round(s / 3600) + ' h';
  return Math.round(s / 86400) + ' ' + T('days');
}
function toggle(checked, disabled, onchange) {
  var input = el('input', { type: 'checkbox' });
  input.checked = !!checked;
  input.disabled = !!disabled;
  input.addEventListener('change', function () { onchange(input.checked, input); });
  return el('label', { class: 'switch' }, [input, el('span')]);
}
function flash(field, ok) {
  field.classList.remove('saved', 'bad');
  field.classList.add(ok ? 'saved' : 'bad');
  if (ok) setTimeout(function () { field.classList.remove('saved'); }, 1500);
}

// --- Restarting ---

function needsRestart(why) {
  var banner = $('#banner');
  banner.hidden = false;
  banner.innerHTML = '';
  banner.appendChild(el('span', { text: why || T('Some changes apply when it restarts.') }));
  banner.appendChild(el('button', { text: T('Restart now'), onclick: restart }));
}
function restart() {
  $('#banner').hidden = false;
  $('#banner').textContent = T('Restarting…');
  api('POST', '/admin/restart').catch(function () {});
  var tries = 0;
  var wait = setInterval(function () {
    fetch('/admin/me').then(function (r) {
      if (r.ok) { clearInterval(wait); $('#banner').hidden = true; show(current); }
    }).catch(function () {});
    if (++tries > 120) clearInterval(wait);
  }, 1500);
}

// --- Logging in with an admin code ---

function showLogin() {
  $('#app').hidden = true;
  $('#restart').hidden = true;
  var box = $('#login');
  box.hidden = false;
  $('h1', box).textContent = T('Administer AnyAssistant');
  $('p', box).textContent = T('Type the admin code. On the computer with the server: this page, Admins → «A code for another browser»; or in its terminal: bin/anyassistant admin-code.');
  $('button', box).textContent = T('Enter');
  $('form', box).onsubmit = function (e) {
    e.preventDefault();
    fetch('/admin/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ code: $('input', box).value }) })
      .then(function (r) {
        if (r.ok) location.reload();
        else $('.error', box).textContent = T('That code isn\'t right (or it\'s too old): ask for another.');
      });
  };
  $('input', box).focus();
}

// --- The sections ---

// Settings: the core's by topic; Plugins: each one's page (#plugin/<id>) with its options and, for
// the mail and the voices, their accounts and known voices; Community: themes and plugins other
// people share, to install.
var SECTIONS = [
  ['pair', 'Pair a device'], ['devices', 'Devices'], ['settings', 'Settings'], ['plugins', 'Plugins'],
  ['community', 'Community'], ['admins', 'Admins']
];
var current = 'pair';
var timer = null;

function show(id) {
  current = id;
  if (timer) { clearInterval(timer); timer = null; }
  var section = id.indexOf('plugin/') === 0 ? 'plugins' : id;
  Array.prototype.forEach.call(document.querySelectorAll('nav button'), function (b) {
    b.classList.toggle('on', b.dataset.id === section);
  });
  var main = $('main');
  main.innerHTML = '';
  if (section !== id) pluginPage(main, id.slice(7));
  else ({ pair: pair, devices: devices, settings: settingsPage, plugins: plugins, community: community, admins: adminsPage })[id](main);
  history.replaceState(null, '', '#' + id);
}

// Pairing a device: the page's address as a QR (with the code: it pairs by itself), the
// certificate first if HTTPS is on, the address for old devices that don't open .local names.
function pair(main) {
  main.appendChild(el('h1', { text: T('Pair a device') }));
  main.appendChild(el('p', { class: 'lead', text: T('A tablet or phone: scan the code with its camera, or open the address. The iPhone, Android and Apple Watch apps ask for the 6 digits.') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  Promise.all([api('GET', '/admin/status'), api('POST', '/pairing')]).then(function (found) {
    var status = found[0], pairing = found[1];
    var code = pairing.code;
    var old = false, step = 0;
    function draw() {
      box.innerHTML = '';
      var host = old ? (status.addresses[0] || location.hostname) : 'anyassistant.local';
      var page = status.https_port ? 'https://' + host + (status.https_port === 443 ? '' : ':' + status.https_port)
                                  : 'http://' + host + ':' + status.port;
      var certificate = 'http://' + host + ':' + status.port + '/https/ca.crt';
      var showing = status.https_port && step === 0 ? certificate : (code ? page + '/?code=' + code : page);
      if (status.https_port) {
        var tabs = el('div', { class: 'tabs' }, [
          el('button', { text: T('1. The certificate'), class: step === 0 ? 'on' : null, onclick: function () { step = 0; draw(); } }),
          el('button', { text: T('2. The page'), class: step === 1 ? 'on' : null, onclick: function () { step = 1; draw(); } })
        ]);
        box.appendChild(el('div', { style: 'padding-top:14px' }, [tabs]));
      }
      var words = [];
      if (status.https_port && step === 0) {
        words = [el('h2', { text: T('Install the certificate') }),
                 el('p', { text: T('Once per device: scan it, or open this address, to download it.') }),
                 el('p', { class: 'mono', text: certificate }),
                 el('p', { class: 'muted', text: T('If it doesn\'t install by itself, on Android: Settings → Security → Install from storage → AnyAssistant.crt (as «VPN and apps»).') }),
                 el('button', { text: T('Done: the page'), onclick: function () { step = 1; draw(); } })];
      } else {
        words = [el('h2', { text: T('Open the page') }),
                 el('p', { text: T('Scan it with the tablet or phone: it pairs by itself. Or open') }),
                 el('p', { class: 'mono', text: page })];
        if (code) {
          words.push(el('p', { text: T('and type the code') }), el('div', { class: 'code', text: code }),
                     el('p', { class: 'muted', text: T('Valid for 5 minutes, for one device.') }),
                     el('button', { class: 'quiet', text: T('Another code'), onclick: function () { show('pair'); } }));
        } else {
          words.push(el('p', { class: 'muted', text: T('No code needed: pairing is off.') }));
        }
      }
      box.appendChild(el('div', { class: 'pair' }, [
        el('img', { src: '/admin/qr?text=' + encodeURIComponent(showing), alt: showing }),
        el('div', { style: 'flex:1;min-width:240px' }, words)
      ]));
      var oldBox = el('label', { class: 'muted', style: 'display:block;padding-bottom:14px' }, [
        el('input', { type: 'checkbox', onchange: function (e) { old = e.target.checked; draw(); } }),
        ' ' + T('An old device (it doesn\'t open .local names): use the address')
      ]);
      $('input', oldBox).checked = old;
      box.appendChild(oldBox);
    }
    draw();
  });
}

function devices(main) {
  main.appendChild(el('h1', { text: T('Devices') }));
  main.appendChild(el('p', { class: 'lead', text: T('Its name and room: «dile a la cocina…», and where alarms ring.') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  var editing = false;
  function load() {
    if (editing) return;
    api('GET', '/devices').then(function (data) {
      box.innerHTML = '';
      if (!data.devices.length) box.appendChild(el('p', { class: 'muted', text: T('None yet: pair one.') }));
      data.devices.forEach(function (d) {
        var state = d.connected ? el('span', { class: 'pill ok', text: d.current ? T('talking to you') : T('connected') })
                    : d.press ? el('span', { class: 'pill', text: T('press to talk') + (d.seen ? ' · ' + ago(d.seen) : '') })
                    : el('span', { class: 'pill', text: d.seen ? T('seen') + ' ' + ago(d.seen) : T('not connected') });
        var name = el('input', { value: d.name, placeholder: T('Name') });
        var room = el('input', { value: d.room, placeholder: T('Room') });
        // Its own LLM, or the general one: from its next question.
        var llm = el('select', { title: T('Its LLM') }, [el('option', { value: '', text: T('The general one') + ' (' + T(LLM_NAMES[data.general] || data.general) + ')' })]
          .concat((data.llms || []).map(function (l) {  // fixed, whatever the default becomes
            return el('option', { value: l, text: T(LLM_NAMES[l] || l) });
          })));
        llm.value = d.llm || '';
        llm.addEventListener('focus', function () { editing = true; });
        llm.addEventListener('blur', function () { editing = false; });
        llm.addEventListener('change', function () {
          api('POST', '/devices', { id: d.id, llm: llm.value }).then(function (r) { flash(llm, !r.error); });
        });
        [name, room].forEach(function (field) {
          field.addEventListener('focus', function () { editing = true; });
          field.addEventListener('change', function () {
            api('POST', '/devices', { id: d.id, name: name.value, room: room.value }).then(function (r) {
              flash(field, !r.error);
              if (r.error) alert(r.error);
            });
          });
          field.addEventListener('blur', function () { editing = false; });
        });
        box.appendChild(el('div', { class: 'row' }, [
          el('div', { class: 'what' }, [name, ' ', room, ' ', llm, state]),
          el('button', { class: 'danger', text: T('Forget'), onclick: function () {
            if (confirm(T('Forget this device? It will need a new code if pairing is on.'))) {
              api('POST', '/devices', { id: d.id, forget: true }).then(load);
            }
          } })
        ]));
      });
    });
  }
  load();
  timer = setInterval(load, 5000);
}

function settingsPage(main) {
  main.appendChild(el('h1', { text: T('Settings') }));
  main.appendChild(el('p', { class: 'lead', text: T('They are saved as you change them. A plugin\'s are on its page (Plugins).') }));
  var search = el('input', { type: 'search', placeholder: T('Search'), class: 'search' });
  main.appendChild(search);
  var list = el('div');
  main.appendChild(list);
  Promise.all([api('GET', '/admin/settings'), api('GET', '/admin/plugins')]).then(function (found) {
    var data = found[0], all = found[1].plugins;
    var names = {};
    all.forEach(function (p) { names[p.id] = p.name; });
    function draw() {
      list.innerHTML = '';
      var words = search.value.trim().toLowerCase();
      if (!words) {  // the core's, by topic
        data.groups.forEach(function (group) {
          var mine = data.options.filter(function (o) { return o.group === group.id && !o.plugin; });
          if (!mine.length) return;
          list.appendChild(el('h2', { text: group.title }));
          var box = el('div', { class: 'card' });
          list.appendChild(box);
          mine.forEach(function (o) { box.appendChild(option(o)); });
        });
        return;
      }
      // A search: every option that has it, wherever it lives, and the plugins.
      var hits = all.filter(function (p) { return (p.name + ' ' + p.description).toLowerCase().indexOf(words) >= 0; });
      if (hits.length) {
        list.appendChild(el('h2', { text: T('Plugins') }));
        var pbox = el('div', { class: 'card' });
        list.appendChild(pbox);
        hits.forEach(function (p) { pbox.appendChild(pluginRow(p)); });
      }
      var places = {};
      data.options.filter(function (o) { return o.group !== 'plugins' && (o.title + ' ' + o.help + ' ' + o.name).toLowerCase().indexOf(words) >= 0; })
        .forEach(function (o) { var at = o.plugin ? names[o.plugin] || o.plugin : (data.groups.filter(function (g) { return g.id === o.group; })[0] || {}).title || o.group; (places[at] = places[at] || []).push(o); });
      Object.keys(places).sort().forEach(function (at) {
        list.appendChild(el('h2', { text: at }));
        var box = el('div', { class: 'card' });
        list.appendChild(box);
        places[at].forEach(function (o) { box.appendChild(option(o)); });
      });
      if (!hits.length && !Object.keys(places).length) list.appendChild(el('p', { class: 'muted', text: T('No results') }));
    }
    search.addEventListener('input', draw);
    draw();
  });
}

function option(o) {
  var field;
  function save(value) {
    var change = {};
    change[o.name] = value;
    api('POST', '/admin/settings', change).then(function (r) {
      flash(field.querySelector ? (field.querySelector('input,select,textarea') || field) : field, !r.error);
      if (r.error) alert(r.error);
      if (r.restart) needsRestart();
    });
  }
  var value = o.value;
  if (o.kind === 'bool') {
    field = toggle(value === null ? o.default : value, false, function (on) { save(on); });
  } else if (o.kind === 'choice' && o.choices) {
    field = el('select');
    var none = value === null || value === undefined;
    o.choices.forEach(function (c) {
      var item = el('option', { value: String(c), text: (o.labels && o.labels[String(c)]) || String(c) });
      if ((none ? o.default : value) === c) item.selected = true;
      field.appendChild(item);
    });
    field.addEventListener('change', function () {
      var chosen = o.choices.filter(function (c) { return String(c) === field.value; })[0];
      save(chosen);
    });
  } else if (o.kind === 'secret') {  // to the keychain; what it has never comes back
    field = el('input', { type: 'password', autocomplete: 'off',
                          placeholder: o.set ? T('Saved in the keychain') : T('Not set') });
    field.addEventListener('change', function () {
      var text = field.value.trim();
      if (!text) return;
      save(text);
      field.value = '';
      field.placeholder = T('Saved in the keychain');
    });
  } else if (o.kind === 'json' || o.kind === 'dict' || o.kind === 'longtext') {
    var shown = value === null || value === undefined ? '' : (typeof value === 'string' && o.kind === 'longtext' ? value : JSON.stringify(value, null, 2));
    field = el('textarea', { placeholder: o.empty || '' });
    field.value = shown;
    field.addEventListener('change', function () {
      var text = field.value.trim();
      if (!text) return save(null);
      if (o.kind === 'longtext') {
        try { return save(JSON.parse(text)); } catch (e) { return save(text); }
      }
      try { save(JSON.parse(text)); } catch (e) {
        if (o.kind === 'json') return save(text);  // a plain value («Mónica»)
        flash(field, false);
      }
    });
  } else {
    var number = o.kind === 'int' || o.kind === 'float';
    field = el('input', { type: number ? 'number' : 'text', step: o.kind === 'float' ? 'any' : null,
                          placeholder: o.empty || (o.default !== null ? String(o.default) : '') });
    field.value = value === null || value === undefined ? '' : (typeof value === 'object' ? JSON.stringify(value) : value);
    field.addEventListener('change', function () {
      var text = field.value.trim();
      if (!text) return save(null);
      save(number ? Number(text) : text);
    });
  }
  return el('div', { class: 'row' }, [
    el('div', { class: 'what', title: o.name }, [el('b', { text: o.title || o.help }),
      o.live ? null : el('span', { class: 'pill', text: T('restarts') }),
      o.title && o.help ? el('div', { class: 'muted', text: o.help }) : null]),
    el('div', { class: 'field' }, [field])
  ]);
}

// An LLM's name as its maker writes it.
var LLM_NAMES = { claude: 'Claude', codex: 'Codex', gemini: 'Gemini', opencode: 'OpenCode', openai: 'OpenAI-compatible',
                  ollama: 'Ollama', hermes: 'Hermes', apple: 'Apple' };

var KINDS = { brain: 'How it works', stt: 'Speech recognition', wake: 'Wake word', llm: 'LLM', tts: 'Voice',
              vad: 'Voice detection', skill: 'Skills', feature: 'Features', library: 'Libraries' };

function plugins(main) {
  main.appendChild(el('h1', { text: T('Plugins') }));
  main.appendChild(el('p', { class: 'lead', text: T('What it can do. Each one\'s page has its options.') }));
  api('GET', '/admin/plugins').then(function (data) {
    Object.keys(KINDS).forEach(function (kind) {
      // The ones that are on first; each opens its page.
      var mine = data.plugins.filter(function (p) { return p.kind === kind; })
        .sort(function (a, b) { return (b.wanted ? 1 : 0) - (a.wanted ? 1 : 0); });
      if (!mine.length) return;
      main.appendChild(el('h2', { text: T(KINDS[kind]) }));
      var box = el('div', { class: 'card' });
      main.appendChild(box);
      mine.forEach(function (p) { box.appendChild(pluginRow(p)); });
    });
  });
}

// A plugin in a list: its name, what it does, on or off; a click opens its page.
function pluginRow(p) {
  return el('div', { class: 'row link', onclick: function () { show('plugin/' + p.id); } }, [
    el('div', { class: 'what' }, [el('b', { text: p.name }),
      p.security ? el('span', { class: 'pill warn', text: T('security') }) : null,
      p.yours ? el('span', { class: 'pill', text: T('yours') }) : null,
      el('div', { class: 'muted', text: p.description })]),
    el('span', { class: 'pill' + (p.wanted ? ' ok' : ''), text: p.wanted ? T('On') : T('Off') })
  ]);
}

// A plugin's page: on or off, what it does, what it lacks, its options; the mail's accounts, the voices.
function pluginPage(main, id) {
  Promise.all([api('GET', '/admin/plugins'), api('GET', '/admin/settings')]).then(function (found) {
    var p = found[0].plugins.filter(function (x) { return x.id === id; })[0];
    if (!p) { main.appendChild(el('p', { class: 'muted', text: T('No results') })); return; }
    main.appendChild(el('button', { class: 'quiet', text: '‹ ' + T('Plugins'), onclick: function () { show('plugins'); } }));
    main.appendChild(el('h1', { text: p.name }));
    main.appendChild(el('p', { class: 'lead', text: p.description }));
    var notes = (p.unfit || []).concat((p.commands_missing || []).map(function (c) { return T('command not found:') + ' ' + c; }));
    var elsewhere = (p.unfit || []).some(function (w) { return w.indexOf('only on') === 0; });
    var head = el('div', { class: 'card' }, [el('div', { class: 'row' }, [
      el('div', { class: 'what' }, [el('b', { text: T('On') }),
        notes.length ? el('div', { class: 'muted', style: 'color:var(--warn)', text: notes.join('; ') }) : null]),
      toggle(p.wanted, elsewhere, function (on, input) {
        if (!on && p.locked && !confirm(T('It is a security plugin, or one it needs to work. Turn it off anyway?'))) {
          input.checked = true;
          return;
        }
        var change = {};
        change[p.id] = on;
        api('POST', '/admin/plugins', change).then(function (r) {
          if (r.packages) needsRestart(T('It needs its packages: bin/anyassistant setup packages, then restart.'));
          else if (r.restart) needsRestart();
        });
      })
    ])]);
    main.appendChild(head);
    var mine = found[1].options.filter(function (o) { return o.plugin === id; });
    if (mine.length) {
      main.appendChild(el('h2', { text: T('Options') }));
      var box = el('div', { class: 'card' });
      main.appendChild(box);
      mine.forEach(function (o) { box.appendChild(option(o)); });
    }
    if (id === 'mail') mail(main, true);
    if (id === 'voices') voices(main, true);
  });
}

function voices(main, inPage) {
  main.appendChild(el(inPage ? 'h2' : 'h1', { text: inPage ? T('Known voices') : T('Voices') }));
  main.appendChild(el('p', { class: 'lead', text: T('Who is speaking. While nobody is known, it listens to everyone; on a device you can also say «aprende mi voz».') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  function draw(data) {
    box.innerHTML = '';
    if (data._status === 404) { box.appendChild(el('p', { class: 'muted', text: T('Turn on the plugin «Voices» to teach it who you are.') })); return; }
    if (!data.people.length) box.appendChild(el('p', { class: 'muted', text: T('Nobody yet: while nobody is known, it listens to everyone.') }));
    data.people.forEach(function (p) {
      box.appendChild(el('div', { class: 'row' }, [
        el('div', { class: 'what' }, [el('b', { text: p.name }), el('div', { class: 'muted', text: p.samples + ' ' + T('phrases') + ' · ' + ago(p.since) })]),
        el('button', { class: 'danger', text: T('Forget'), onclick: function () { api('POST', '/admin/voices', { forget: p.name }).then(draw); } })
      ]));
    });
  }
  api('GET', '/admin/voices').then(draw);
  main.appendChild(el('h2', { text: T('Learn a voice') }));
  var learn = el('div', { class: 'card' });
  main.appendChild(learn);
  learn.appendChild(el('p', { class: 'muted', text: T('Stand in front of the device you talk to most: its microphone is the one that will hear you. Then read the phrases shown here, one at a time.') }));
  var empty = el('p', { class: 'muted', text: T('No device connected: open one and come back.') });
  var device = el('select');
  // The connected devices, as they are now (renamed, connected), while choosing.
  function listDevices() {
    api('GET', '/devices').then(function (data) {
      var connected = data.devices.filter(function (d) { return d.connected; });
      var chosen = device.value;
      device.innerHTML = '';
      connected.forEach(function (d) {
        device.appendChild(el('option', { value: d.id, text: d.room ? d.name + ' (' + d.room + ')' : d.name || d.id }));
      });
      if (chosen) device.value = chosen;
      empty.hidden = connected.length > 0;
      form.hidden = !connected.length || following;
    });
  }
  var following = false;
  {
    var name = el('input', { placeholder: T('the person\'s: «Suvi»') });
    var note = el('span', { class: 'muted' });
    var form = el('form', { class: 'inline', onsubmit: function (e) {
      e.preventDefault();
      api('POST', '/admin/voices', { learn: device.value, name: name.value }).then(function (r) {
        if (r.error) { note.textContent = r.error; return; }
        guide(device.value);
      });
    } }, [device, name, el('button', { text: T('Start learning') }), note]);
    learn.appendChild(empty);
    learn.appendChild(form);
    listDevices();
    timer = setInterval(function () { if (!following) listDevices(); }, 3000);

    // The guide: the phrase to read now, which one, and what happens, until it ends.
    function guide(id) {
      following = true;
      form.hidden = true;
      var box = el('div', { style: 'padding:16px 0' });
      learn.appendChild(box);
      var follow = setInterval(function () {
        api('GET', '/admin/voices').then(function (r) {
          var now = (r.learning || {})[id];
          if (!now) return;
          box.innerHTML = '';
          if (now.step === 'name') {
            box.appendChild(el('h2', { text: T('Tell it your name') }));
            box.appendChild(el('p', { text: T('Say it to the device: «Me llamo Suvi».') }));
          } else if (now.step === 'phrase') {
            box.appendChild(el('b', { text: T('Phrase') + ' ' + now.number + ' / ' + now.total }));
            box.appendChild(el('progress', { value: now.number - 1, max: now.total, style: 'display:block;width:100%;margin:8px 0' }));
            box.appendChild(el('p', { class: 'muted', text: T('Read it out loud:') }));
            box.appendChild(el('p', { style: 'font-size:28px;font-weight:600;line-height:1.3;margin:6px 0 12px', text: now.phrase }));
            if (now.again) box.appendChild(el('p', { style: 'color:var(--warn)', text: T('A little longer: say the whole phrase again.') }));
            box.appendChild(el('p', { class: 'muted', text: T('When it hears you, it goes on to the next one.') }));
          } else {
            clearInterval(follow);
            box.appendChild(el('h2', { text: now.step === 'done' ? T('Done, %s: it knows your voice.').replace('%s', now.name)
                                                                 : T('Cancelled: nothing was learnt.') }));
            box.appendChild(el('button', { class: 'quiet', text: T('Learn another'), onclick: function () { show('voices'); } }));
            api('GET', '/admin/voices').then(draw);
            return;
          }
          box.appendChild(el('button', { class: 'danger', text: T('Cancel'), onclick: function () {
            api('POST', '/admin/voices', { cancel: id });
          } }));
        });
      }, 700);
      clearInterval(timer);
      timer = follow;  // leaving the section stops it
    }
  }
}

function mail(main, inPage) {
  main.appendChild(el(inPage ? 'h2' : 'h1', { text: inPage ? T('Mail accounts') : T('Mail') }));
  main.appendChild(el('p', { class: 'lead', text: T('Accounts besides Gmail (IMAP and SMTP): new email notices, the morning count, and for the LLM to read and send (with your «yes»). The password goes to the system\'s keychain.') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  function draw(data) {
    box.innerHTML = '';
    if (data._status === 404) { box.appendChild(el('p', { class: 'muted', text: T('Turn on the plugin «Mail».') })); return; }
    if (data.problems && data.problems.length) alert(data.problems.join('\n'));
    if (!data.accounts.length) box.appendChild(el('p', { class: 'muted', text: T('None yet.') }));
    data.accounts.forEach(function (a) {
      box.appendChild(el('div', { class: 'row' }, [
        el('div', { class: 'what' }, [el('b', { text: a.name || a.address }),
          a.password ? null : el('span', { class: 'pill warn', text: T('no password') }),
          el('div', { class: 'muted', text: a.address + ' · ' + a.imap + ' · ' + a.smtp })]),
        el('button', { class: 'quiet', text: T('Test'), onclick: function () {
          api('POST', '/admin/mail', { test: a.address }).then(function (r) {
            alert(r.problems && r.problems.length ? r.problems.join('\n') : T('It works.'));
          });
        } }),
        el('button', { class: 'danger', text: T('Remove'), onclick: function () {
          if (confirm(T('Remove this account?'))) api('POST', '/admin/mail', { remove: a.address }).then(draw);
        } })
      ]));
    });
  }
  api('GET', '/admin/mail').then(draw);
  main.appendChild(el('h2', { text: T('Add an account') }));
  var address = el('input', { placeholder: 'yo@dominio.com', type: 'text' });
  var secret = el('input', { type: 'password', placeholder: T('Password (an app password if it has one)') });
  var label = el('input', { placeholder: T('Name (optional)') });
  var imap = el('input', { placeholder: 'imap.dominio.com:993' });
  var smtp = el('input', { placeholder: 'smtp.dominio.com:465' });
  var note = el('span', { class: 'error' });
  address.addEventListener('change', function () {
    if (address.value.indexOf('@') < 0) return;
    api('GET', '/admin/mail?guess=' + encodeURIComponent(address.value)).then(function (r) {
      if (!imap.value && r.imap) imap.value = r.imap;
      if (!smtp.value && r.smtp) smtp.value = r.smtp;
    });
  });
  main.appendChild(el('div', { class: 'card' }, [el('form', { class: 'inline', onsubmit: function (e) {
    e.preventDefault();
    note.textContent = T('Trying it…');
    api('POST', '/admin/mail', { add: { address: address.value, password: secret.value, name: label.value, imap: imap.value, smtp: smtp.value } })
      .then(function (r) {
        if (r.problems || r.error) { note.textContent = (r.problems || [r.error]).join('; '); return; }
        note.textContent = '';
        [address, secret, label, imap, smtp].forEach(function (f) { f.value = ''; });
        draw(r);
      });
  } }, [address, secret, label, imap, smtp, el('button', { text: T('Add') }), note])]));
}

// The community (the plugin «community»): themes and plugins other people share, from a public
// catalog: what is installed and whether an update exists; install (a plugin asks first, and
// starts off), update, remove. Themes show their screenshot (fetched by the server).
function community(main) {
  main.appendChild(el('h1', { text: T('Community') }));
  main.appendChild(el('p', { class: 'lead', text: T('Themes and plugins other people share, from a public catalog. Every package is reviewed before it is listed.') }));
  var box = el('div');
  main.appendChild(box);
  function load(refresh) {
    api('GET', '/admin/community' + (refresh ? '?refresh=1' : '')).then(function (data) {
      box.innerHTML = '';
      if (data._status === 404) {
        box.appendChild(el('div', { class: 'card' }, [el('p', { class: 'muted', text: T('Turn on the plugin «Community».') })]));
        return;
      }
      if (data.error) box.appendChild(el('div', { class: 'card' }, [el('p', { class: 'error', text: data.error })]));
      ['theme', 'plugin'].forEach(function (kind) {
        var mine = (data.packages || []).filter(function (p) { return p.kind === kind; });
        box.appendChild(el('h2', { text: kind === 'theme' ? T('Themes') : T('Plugins') }));
        var card = el('div', { class: 'card' });
        box.appendChild(card);
        if (!mine.length) card.appendChild(el('p', { class: 'muted', text: T('Nothing to install yet.') }));
        mine.forEach(function (p) { card.appendChild(packageRow(p, load)); });
      });
      box.appendChild(el('p', {}, [el('button', { class: 'quiet', text: T('Reload the catalog'), onclick: function () { load(true); } })]));
    });
  }
  load(false);
}

// A package of the catalog: what it is, what is installed, and what can be done with it.
function packageRow(p, reload) {
  var busy = el('span', { class: 'muted' });
  function install() {
    if (p.kind === 'plugin' && !confirm(T('Install «%s»?').replace('%s', p.name) + '\n\n' +
        T('A plugin is code that runs on this server with your permissions. Install it only if you trust its author. It starts off: turn it on in Plugins when you want to use it.'))) return;
    busy.textContent = T('Installing…');
    api('POST', '/admin/community', { install: { kind: p.kind, id: p.id }, confirm: p.kind === 'plugin' }).then(function (r) {
      busy.textContent = '';
      if (r.error) { alert(r.error); return; }
      if (r.restart) needsRestart(r.updated ? T('Updated. It applies after restarting.') : T('Installed. It is off: turn it on in Plugins after restarting.'));
      reload(false);
    });
  }
  function remove() {
    if (!confirm(T('Remove «%s»?').replace('%s', p.name))) return;
    api('POST', '/admin/community', { remove: { kind: p.kind, id: p.id } }).then(function (r) {
      if (r.error) { alert(r.error); return; }
      if (r.restart) needsRestart(T('Removed. It applies after restarting.'));
      reload(false);
    });
  }
  var buttons = [];
  if (p.installed) {
    if (p.update && p.can) buttons.push(el('button', { text: T('Update'), onclick: install }));
    buttons.push(el('button', { class: 'danger', text: T('Remove'), onclick: remove }));
  } else if (p.can) {
    buttons.push(el('button', { text: T('Install'), onclick: install }));
  }
  var state = p.installed
    ? el('span', { class: 'pill' + (p.update ? ' warn' : ' ok'), text: p.update ? T('update available') : T('installed') + ' ' + p.installed })
    : null;
  return el('div', { class: 'row' }, [
    p.kind === 'theme' && p.screenshot
      ? el('img', { class: 'shot', src: '/admin/community/image?kind=theme&id=' + encodeURIComponent(p.id), alt: '' })
      : null,
    el('div', { class: 'what' }, [el('b', { text: p.name }), state,
      el('div', { class: 'muted', text: [p.author ? T('by') + ' ' + p.author : '', T('version') + ' ' + p.version].filter(Boolean).join(' · ') }),
      el('div', { class: 'muted', text: p.description }),
      p.can ? null : el('div', { class: 'muted', style: 'color:var(--warn)', text: p.why })]),
    busy
  ].concat(buttons));
}

function adminsPage(main) {
  main.appendChild(el('h1', { text: T('Admins') }));
  main.appendChild(el('p', { class: 'lead', text: T('The browsers that may change all this, besides this computer itself. A device paired to talk can\'t.') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  function draw(data) {
    box.innerHTML = '';
    if (!data.admins.length) box.appendChild(el('p', { class: 'muted', text: T('Only this computer.') }));
    data.admins.forEach(function (a) {
      box.appendChild(el('div', { class: 'row' }, [
        el('div', { class: 'what' }, [el('b', { text: a.name.slice(0, 90) }), a.you ? el('span', { class: 'pill ok', text: T('this browser') }) : null,
          el('div', { class: 'muted', text: T('since') + ' ' + ago(a.since) })]),
        el('button', { class: 'danger', text: a.you ? T('Log out') : T('Revoke'), onclick: function () {
          api('POST', '/admin/admins', a.you ? { logout: true } : { forget: a.id }).then(function (r) {
            if (a.you) location.reload(); else draw(r);
          });
        } })
      ]));
    });
  }
  api('GET', '/admin/admins').then(draw);
  main.appendChild(el('h2', { text: T('A code for another browser') }));
  var shown = el('div');
  main.appendChild(el('div', { class: 'card' }, [el('div', { style: 'padding:14px 0' }, [
    el('button', { text: T('Make a code'), onclick: function () {
      api('POST', '/admin/code').then(function (r) {
        shown.innerHTML = '';
        shown.appendChild(el('p', { text: T('On the other computer or phone, open') }));
        shown.appendChild(el('p', { class: 'mono', text: location.origin.replace('127.0.0.1', 'anyassistant.local').replace('localhost', 'anyassistant.local') + '/admin' }));
        shown.appendChild(el('p', { text: T('and type') }));
        shown.appendChild(el('div', { class: 'code', text: r.code }));
        shown.appendChild(el('p', { class: 'muted', text: T('Valid for 5 minutes, for one browser.') }));
      });
    } }), shown])]));
}

// --- Start ---

fetch('/admin/me', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (me) {
  texts = me.texts || {};
  document.documentElement.lang = me.lang || 'en';
  if (!me.owner) return showLogin();
  $('#app').hidden = false;
  var restartButton = $('#restart');
  restartButton.hidden = false;
  restartButton.textContent = T('Restart');
  restartButton.onclick = function () { if (confirm(T('Restart the server now?'))) restart(); };
  api('GET', '/admin/status').then(function (s) {
    $('#title').textContent = s.name;
    $('#subtitle').textContent = s.computer + ' · ' + s.version;
    document.title = s.name + ' · ' + T('Admin');
  });
  var nav = $('nav');
  SECTIONS.forEach(function (section) {
    nav.appendChild(el('button', { text: T(section[1]), 'data-id': section[0], onclick: function () { show(section[0]); } }));
  });
  var wanted = location.hash.slice(1);
  show(SECTIONS.some(function (s) { return s[0] === wanted; }) || wanted.indexOf('plugin/') === 0 ? wanted : 'pair');
});

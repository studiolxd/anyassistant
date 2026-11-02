// AnyAssistant's admin page (/admin): what the Mac app shows, for Windows, Linux and a Linux with
// no screen, with the same structure and words. Over the same routes (/admin/settings,
// /admin/plugins, /devices, /pairing, /admin/voices, /admin/memory, /admin/mail). Texts: English as the key, the
// server's language from /admin/me. The Windows and Linux app opens it in a window per part
// (?window=settings|devices|pair, as the Mac's windows): only that part, no header nor other sections.

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
// A route of the server's; when it doesn't answer at all, the page says so in the middle (unavailable).
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
  }, function () {
    unavailable();
    throw new Error('unavailable');
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
// What couldn't be saved, by its field (a line under it; gone once it saves).
function problem(where, text) {
  var old = $('.problem', where);
  if (old) old.remove();
  if (text) where.appendChild(el('div', { class: 'problem', text: text }));
}
function svg(paths, size) {
  var icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('width', size || 22);
  icon.setAttribute('height', size || 22);
  icon.setAttribute('fill', 'none');
  icon.setAttribute('stroke', 'currentColor');
  icon.setAttribute('stroke-width', '1.6');
  icon.setAttribute('stroke-linecap', 'round');
  icon.setAttribute('stroke-linejoin', 'round');
  paths.forEach(function (d) {
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    icon.appendChild(path);
  });
  return icon;
}
// A device's icon, by its kind («iPhone», «Mac»…), as the Mac draws it.
var DEVICE_ICONS = {
  'iPhone': ['M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z', 'M10 19h4'],
  'Android phone': ['M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z', 'M10 19h4'],
  'iPad': ['M5 2h14a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z', 'M11 19h2'],
  'Android tablet': ['M5 2h14a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z', 'M11 19h2'],
  'Mac': ['M4 5h16a1 1 0 0 1 1 1v9H3V6a1 1 0 0 1 1-1z', 'M2 18h20v1H2z'],
  'Apple Watch': ['M7 7h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z', 'M9 7V3h6v4', 'M9 17v4h6v-4'],
  'PC': ['M9 3h10a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z', 'M11 7h6', 'M11 10h6'],
  'device': ['M3 4h18a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z', 'M8 21h8', 'M12 17v4']
};
function deviceIcon(kind, size) { return svg(DEVICE_ICONS[kind] || DEVICE_ICONS.device, size); }
var LOCK = ['M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5l8-3z', 'M9 12h6v4H9z', 'M10 12v-2a2 2 0 0 1 4 0v2'];

// --- Restarting ---

function needsRestart(why) {
  var banner = $('#banner');
  banner.hidden = false;
  banner.innerHTML = '';
  banner.appendChild(el('span', { text: why || T('Some changes apply after restarting.') }));
  banner.appendChild(el('button', { text: T('Restart'), onclick: restart }));
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

// --- The server doesn't answer: in the middle, what is wrong and what to do (as the Mac's windows) ---

function unavailable() {
  if (timer) { clearInterval(timer); timer = null; }
  var main = $('main');
  main.innerHTML = '';
  main.appendChild(el('div', { class: 'unavailable' }, [
    el('div', { class: 'symbol', text: '⚡' }),
    el('h1', { text: T('The server isn\'t responding') }),
    el('p', { class: 'muted', text: T('Make sure AnyAssistant is running.') }),
    el('button', { class: 'secondary', text: T('Try Again'), onclick: function () { show(current); } })
  ]));
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

// As the Mac's windows: «Connect another device», «Devices», and Settings («General», the core's
// by topic: group/<id>; «Plugins», each one's page: plugin/<id>, with the mail's accounts and the
// known voices as pages of their own; «Memory», what it remembers), plus «Admins» (the browsers that may administer: only
// here). A search (the field over the sidebar) finds options and plugins wherever they live.
var WINDOW = new URLSearchParams(location.search).get('window');  // the app's window: only that part
var groups = [];  // the General sections, from /admin/settings
var current = 'pair';
var timer = null;

function section(id) {
  if (id.indexOf('group/') === 0) return id;
  if (id.indexOf('plugin/') === 0 || id === 'plugins' || id === 'community' || id === 'mail' || id === 'voices') return 'plugins';
  if (id.indexOf('device/') === 0) return 'devices';
  return id;
}

function show(id) {
  if (id === 'settings') id = groups.length ? 'group/' + groups[0].id : 'plugins';
  current = id;
  if (timer) { clearInterval(timer); timer = null; }
  var search = $('nav input');
  if (search && id !== 'search') search.value = '';
  Array.prototype.forEach.call(document.querySelectorAll('nav button'), function (b) {
    b.classList.toggle('on', b.dataset.id === section(id));
  });
  var main = $('main');
  main.innerHTML = '';
  if (id === 'search') searchResults(main);
  else if (id.indexOf('group/') === 0) groupPage(main, id.slice(6));
  else if (id.indexOf('plugin/') === 0) pluginPage(main, id.slice(7));
  else if (id.indexOf('device/') === 0) devicePage(main, id.slice(7));
  else if (id === 'mail') mailPage(main);
  else if (id === 'voices') voicesPage(main);
  else if (id === 'memory') memoryPage(main);
  else if (id === 'community') plugins(main, true);
  else ({ pair: pair, devices: devices, plugins: plugins, admins: adminsPage })[id](main);
  // #community is a way in, kept as #plugins: asked again (the app's notification), it is a change the page hears
  if (id !== 'search') history.replaceState(null, '', '#' + (id === 'community' ? 'plugins' : id));
}
window.addEventListener('hashchange', function () {
  if (location.hash === '#community' && !$('#app').hidden && WINDOW !== 'devices' && WINDOW !== 'pair') show('community');
});

/// Over a page: the way back to where it hangs from (as the Mac's back button over a page).
function back(main, id, title) {
  main.appendChild(el('button', { class: 'secondary back', text: '‹ ' + title, onclick: function () { show(id); } }));
}

// Connecting a device, as the Mac app's window: one QR for everything (the server itself by its
// address now, /connect with the code: the app pairs by itself, a browser goes on to the page), the
// code big, and «Other ways to connect» folded: the app's choice, the browser's addresses (the certificate
// first, for the browser only, with HTTPS; the IP for old devices that don't open .local names).
function pair(main) {
  main.appendChild(el('h1', { text: T('Pair a device') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  Promise.all([api('GET', '/admin/status'), api('POST', '/pairing')]).then(function (found) {
    var status = found[0], code = found[1].code;
    var address = status.address || location.hostname;
    var connect = (status.connect || 'http://' + address + ':' + status.port + '/connect') + (code ? '?code=' + code : '');
    var words = [el('p', { text: T('Scan the code with the device\'s camera. With the app installed, it connects by itself; otherwise, it goes on in the browser.') })];
    if (code) {
      words.push(el('h2', { text: T('Pairing code') }), el('div', { class: 'code', text: code }),
                 el('p', { class: 'muted' }, [T('Valid for 5 minutes') + ' · ',
                   el('a', { href: '#pair', text: T('Another code'), onclick: function (e) { e.preventDefault(); show('pair'); } })]));
    } else {
      words.push(el('p', { class: 'muted', text: T('No code needed: pairing is off.') }));
    }
    box.appendChild(el('div', { class: 'pair' }, [
      el('img', { src: '/admin/qr?text=' + encodeURIComponent(connect), alt: connect }),
      el('div', { class: 'grow' }, words)
    ]));
    function step(title, how) {
      return el('div', { class: 'step' }, [el('b', { text: title }), el('div', {}, how)]);
    }
    var browser = [];
    if (status.certificate) {
      browser.push(el('p', { text: T('First, install the certificate:') }), el('p', { class: 'mono', text: status.certificate }),
                   el('p', { class: 'muted', text: T('If it doesn\'t install by itself, on Android, go to Settings → Security → Install from storage and choose AnyAssistant.crt.') }),
                   el('p', { text: T('Then, open:') }));
    }
    browser.push(el('p', { class: 'mono', text: status.local || 'http://anyassistant.local:' + status.port }),
                 el('p', { class: 'mono muted', text: T('On old devices: %s').replace('%s', 'http://' + address + ':' + status.port) }));
    box.appendChild(el('details', { class: 'hand' }, [
      el('summary', { text: T('Connect by hand') }),
      step(T('App'), [el('p', { text: T('Choose «%s on %s»').replace('%s', status.name).replace('%s', status.computer)
                                    + (status.pairing ? ' ' + T('and type the code') : '') })]),
      step(T('Browser'), browser)
    ]));
  }).catch(function () {});
}

// The devices, as the Mac app lists them: a row each (its icon, name, room and state; the connected
// ones first) that opens its page (#device/<id>): its state, name and room, its language model,
// its room's noise, forget it.
function deviceState(d) {
  if (d.connected) return d.current ? T('Connected · talking to you') : T('Connected');
  var state = d.press ? T('Press to talk') : T('Not connected');
  return d.seen ? state + ' · ' + ago(d.seen) : state;
}

function devices(main) {
  main.appendChild(el('h1', { text: T('Devices') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  function load() {
    api('GET', '/devices').then(function (data) {
      box.innerHTML = '';
      if (data._status === 404) { box.appendChild(el('p', { class: 'muted', text: T('Turn on the plugin «Devices» in the settings to see them here.') })); return; }
      if (!data.devices.length) box.appendChild(el('p', { class: 'muted', text: T('No device has connected yet.') }));
      data.devices.slice().sort(function (a, b) { return (b.connected ? 1 : 0) - (a.connected ? 1 : 0) || a.name.localeCompare(b.name); })
        .forEach(function (d) {
          box.appendChild(el('div', { class: 'row link', onclick: function () { show('device/' + d.id); } }, [
            el('span', { class: 'kind' + (d.connected ? ' on' : '') }, [deviceIcon(d.kind, 26)]),
            el('div', { class: 'what' }, [el('b', { text: d.name || T('Unnamed device') }),
              el('div', { class: 'muted', text: [d.room, deviceState(d)].filter(Boolean).join(' · ') })]),
            d.connected ? el('span', { class: 'dot ok' }) : null,
            el('span', { class: 'chevron', text: '›' })
          ]));
        });
    }).catch(function () {});
  }
  load();
  // In the app's Devices window, «Connect another device…» is a window of its own (as on the Mac).
  var connect = WINDOW ? function () { window.open('/admin?window=pair#pair'); } : function () { show('pair'); };
  main.appendChild(el('div', { class: 'card' }, [el('div', { class: 'row link', onclick: connect }, [
    el('div', { class: 'what accent', text: T('Connect another device…') })])]));
  timer = setInterval(load, 3000);
}

// A device's page: its state, name and room, its language model, its room's noise («Calibrate»),
// «Forget This Device». What can't be saved (a name already taken) goes by the fields.
function devicePage(main, id) {
  api('GET', '/devices').then(function (data) {
    var d = data.devices.filter(function (x) { return x.id === id; })[0];
    back(main, 'devices', T('Devices'));
    if (!d) { main.appendChild(el('p', { class: 'muted', text: T('No results') })); return; }
    main.appendChild(el('div', { class: 'head' }, [
      el('span', { class: 'kind big' + (d.connected ? ' on' : '') }, [deviceIcon(d.kind, 40)]),
      el('div', {}, [el('h1', { text: d.name || T('Unnamed device') }), el('p', { class: 'lead', text: deviceState(d) })])
    ]));
    var name = el('input', { value: d.name, placeholder: T('Name') });
    var room = el('input', { value: d.room, placeholder: T('Not set yet') });
    var fields = el('div', { class: 'card' });
    [name, room].forEach(function (field) {
      field.addEventListener('change', function () {
        api('POST', '/devices', { id: d.id, name: name.value, room: room.value }).then(function (r) {
          flash(field, !r.error);
          problem(fields, r.error ? (r._status === 400 ? T('Another device already has that name.') : T('It couldn\'t be saved.')) : '');
        });
      });
    });
    var llm = el('select', {}, [el('option', { value: '', text: T('The general one (%s)').replace('%s', T(LLM_NAMES[data.general] || data.general)) })]
      .concat((data.llms || []).map(function (l) {  // fixed, whatever the default becomes
        return el('option', { value: l, text: T(LLM_NAMES[l] || l) });
      })));
    llm.value = d.llm || '';
    llm.addEventListener('change', function () {
      api('POST', '/devices', { id: d.id, llm: llm.value }).then(function (r) { flash(llm, !r.error); });
    });
    function row(title, help, field) {
      return el('div', { class: 'row' }, [el('div', { class: 'what' }, [el('b', { text: title }),
        help ? el('div', { class: 'muted', text: help }) : null]), el('div', { class: 'control' }, [field])]);
    }
    fields.appendChild(row(T('Name'), '', name));
    fields.appendChild(row(T('Room'), T('The room is how you say it by voice: «pon una alarma en la cocina». It can also be changed by voice from the device itself: «esta es la de la cocina».'), room));
    main.appendChild(fields);
    // Its interface's language (its page, its app's face): apart from the one the assistant speaks.
    var ui = el('select', {}, [el('option', { value: 'auto', text: T('Automatic') })]
      .concat(Object.keys(data.ui_languages || {}).map(function (c) { return el('option', { value: c, text: data.ui_languages[c] }); })));
    ui.value = d.ui_language || 'auto';
    ui.addEventListener('change', function () {
      api('POST', '/devices', { id: d.id, ui_language: ui.value }).then(function (r) { flash(ui, !r.error); });
    });
    main.appendChild(el('div', { class: 'card' }, [row(T('Language model'), T('The one that answers on this device.'), llm),
      row(T('Interface Language'), T('The language of its screen and its app. The assistant speaks the one in General.'), ui)]));
    // Its room's noise (the plugin «calibration»): measured, or a calibration going on there.
    var noise = d.noise || {};
    var levels = { quiet: 'Quiet', some: 'Some noise', noisy: 'Noisy' };
    var noiseText = noise.step === 'asking' ? T('Getting ready: keep silent near the device…')
                  : noise.step === 'measuring' ? T('Measuring… %d').replace('%d', Math.max(1, Math.ceil(noise.left || 0)))
                  : noise.step === 'talking' ? T('It heard talking: try again in silence.')
                  : !noise.noise ? T('Not measured')
                  : T(levels[noise.noise] || noise.noise) + (noise.db !== undefined ? ' (' + Math.round(noise.db) + ' dB)' : '');
    var noiseCard = el('div', { class: 'card' });
    var calibrate = d.connected && !d.press ? el('button', { class: 'secondary', text: T('Calibrate'),
      disabled: noise.step === 'asking' || noise.step === 'measuring' ? 'disabled' : null,
      onclick: function (e) {
        e.target.disabled = true;
        api('POST', '/admin/calibration', { calibrate: d.id }).then(function (r) {
          if (r.error || r._status === 404) { problem(noiseCard, T('It couldn\'t start the calibration. Turn on the plugin «Calibration».')); e.target.disabled = false; }
          else setTimeout(function () { show('device/' + d.id); }, 500);  // it follows the calibration
        });
      } }) : el('span');
    if (noise.step === 'asking' || noise.step === 'measuring') {  // the countdown: again in half a second
      setTimeout(function () { if (location.hash === '#device/' + d.id) show('device/' + d.id); }, 500);
    }
    noiseCard.appendChild(row(T('Room noise'), T('A few seconds of silence measured on the device: how it tells your voice from the room\'s noise.'),
      el('span', {}, [el('span', { class: 'muted' + (noise.step === 'talking' ? ' warn' : ''), text: noiseText + ' ' }), calibrate])));
    main.appendChild(noiseCard);
    main.appendChild(el('div', { class: 'card' }, [row(T('Forget This Device'), T('It is forgotten here; if it connects again it is a new device.'),
      el('button', { class: 'danger', text: T('Forget'), onclick: function () {
        if (confirm(T('Forget this device?') + '\n\n' + T('It is forgotten here; if it connects again it is a new device.'))) {
          api('POST', '/devices', { id: d.id, forget: true }).then(function () { show('devices'); });
        }
      } }))]));
  }).catch(function () {});
}

// --- Settings: «General», the core's by topic; the search over everything ---

function groupPage(main, id) {
  var group = groups.filter(function (g) { return g.id === id; })[0];
  if (!WINDOW && group) main.appendChild(el('h1', { text: group.title }));
  api('GET', '/admin/settings').then(function (data) {
    var box = el('div', { class: 'card' });
    main.appendChild(box);
    data.options.filter(function (o) { return o.group === id && !o.plugin; }).forEach(function (o) { box.appendChild(option(o)); });
  }).catch(function () {});
}

// A search: the options whose text or name has it (wherever they live) and the plugins.
function searchResults(main) {
  var words = ($('nav input').value || '').trim().toLowerCase();
  if (!words) return show(current === 'search' ? 'settings' : current);
  Promise.all([api('GET', '/admin/settings'), api('GET', '/admin/plugins')]).then(function (found) {
    var data = found[0], all = found[1].plugins;
    var names = {};
    all.forEach(function (p) { names[p.id] = p.name; });
    var hits = all.filter(function (p) { return (p.name + ' ' + p.description).toLowerCase().indexOf(words) >= 0; });
    if (hits.length) {
      main.appendChild(el('h2', { text: T('Plugins') }));
      var pbox = el('div', { class: 'card' });
      main.appendChild(pbox);
      hits.forEach(function (p) { pbox.appendChild(pluginRow(p)); });
    }
    var places = {};
    data.options.filter(function (o) { return o.group !== 'plugins' && (o.title + ' ' + o.help + ' ' + o.name).toLowerCase().indexOf(words) >= 0; })
      .forEach(function (o) { var at = o.plugin ? names[o.plugin] || o.plugin : (data.groups.filter(function (g) { return g.id === o.group; })[0] || {}).title || o.group; (places[at] = places[at] || []).push(o); });
    Object.keys(places).sort().forEach(function (at) {
      main.appendChild(el('h2', { text: at }));
      var box = el('div', { class: 'card' });
      main.appendChild(box);
      places[at].forEach(function (o) { box.appendChild(option(o)); });
    });
    if (!hits.length && !Object.keys(places).length) main.appendChild(el('p', { class: 'muted', text: T('No results') }));
  }).catch(function () {});
}

// An option: its title («Hora en reposo»; without one, its help as the title), its field, and under
// it its help and whether it applies after restarting. What can't be saved: by the field.
function option(o) {
  var field, row;
  function save(value) {
    var change = {};
    change[o.name] = value;
    api('POST', '/admin/settings', change).then(function (r) {
      flash(field.querySelector ? (field.querySelector('input,select,textarea') || field) : field, !r.error);
      problem($('.what', row), r.error ? (r.error || T('It couldn\'t be saved.')) : '');
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
    if (o.voices && o.voices.length) field = voicePicker(o, field, save);
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
  var note = [o.title ? o.help : '', o.live ? '' : T('Applies after restarting.')].filter(Boolean).join(' ');
  row = el('div', { class: 'row' }, [
    el('div', { class: 'what', title: o.name }, [el('b', { text: o.title || o.help }),
      note ? el('div', { class: 'muted', text: note }) : null]),
    el('div', { class: 'control' }, [field])
  ]);
  return row;
}

// «voice»: the voice engine in use's voices in this language, under its field. Picking one sets that
// language's voice (one for every language, «Mónica», becomes this language's), as the Mac's menu.
function voicePicker(o, text, save) {
  var pick = el('select', {}, [el('option', { value: '', text: T('Choose a voice') })]);
  o.voices.forEach(function (v) {
    pick.appendChild(el('option', { value: v.name, text: v.label === v.name ? v.name : v.label + ' · ' + v.name }));
  });
  pick.addEventListener('change', function () {
    var voice = o.voices.filter(function (v) { return v.name === pick.value; })[0];
    if (!voice) return;
    var chosen = {};
    try { chosen = JSON.parse(text.value); } catch (e) {}  // as the field says now
    if (!chosen || typeof chosen !== 'object' || Array.isArray(chosen)) chosen = {};
    chosen[voice.language] = voice.name;
    text.value = JSON.stringify(chosen, null, 2);
    pick.value = '';
    save(chosen);
  });
  return el('div', { class: 'stack' }, [text, pick]);
}

// An LLM's name as its maker writes it.
var LLM_NAMES = { claude: 'Claude', codex: 'Codex', gemini: 'Gemini', opencode: 'OpenCode', openai: 'OpenAI-compatible',
                  ollama: 'Ollama', hermes: 'Hermes', apple: 'Apple' };

// The plugins by kind, in the Mac's order and with its titles.
var KINDS = [['feature', 'Features'], ['skill', 'Skills'], ['library', 'Libraries'], ['brain', 'Brain'], ['llm', 'LLMs'],
             ['stt', 'Speech recognition'], ['tts', 'Voices'], ['wake', 'Wake word'], ['vad', 'Voice detection']];

// #community (an update announced by the app): Plugins, scrolled to «From the community».
function plugins(main, toCommunity) {
  if (!WINDOW) main.appendChild(el('h1', { text: T('Plugins') }));
  api('GET', '/admin/plugins').then(function (data) {
    KINDS.forEach(function (kind) {
      // The ones that are on first; each opens its page.
      var mine = data.plugins.filter(function (p) { return p.kind === kind[0]; })
        .sort(function (a, b) { return (b.wanted ? 1 : 0) - (a.wanted ? 1 : 0); });
      if (!mine.length) return;
      main.appendChild(el('h2', { text: T(kind[1]) }));
      var box = el('div', { class: 'card' });
      main.appendChild(box);
      mine.forEach(function (p) { box.appendChild(pluginRow(p)); });
    });
    community(main, toCommunity);  // the catalog's plugins, after the installed ones
  }).catch(function () {});
}

// A plugin in a list: its name, what it does, on or off; a click opens its page.
function pluginRow(p) {
  return el('div', { class: 'row link', onclick: function () { show('plugin/' + p.id); } }, [
    el('div', { class: 'what' }, [el('b', { text: p.name }),
      p.security ? el('span', { class: 'lock', title: T('security') }, [svg(LOCK, 14)]) : null,
      p.yours ? el('span', { class: 'badge', text: T('yours') }) : null,
      el('div', { class: 'muted', text: p.description })]),
    el('span', { class: 'muted', text: p.wanted ? T('On') : T('Off') }),
    el('span', { class: 'chevron', text: '›' })
  ]);
}

// A plugin's page: on or off, what it does, what it lacks, its options (greyed while it is off); the
// mail's accounts and the known voices, as pages of their own.
function pluginPage(main, id) {
  Promise.all([api('GET', '/admin/plugins'), api('GET', '/admin/settings')]).then(function (found) {
    var p = found[0].plugins.filter(function (x) { return x.id === id; })[0];
    back(main, 'plugins', T('Plugins'));
    if (!p) { main.appendChild(el('p', { class: 'muted', text: T('No results') })); return; }
    main.appendChild(el('h1', { text: p.name }));
    var notes = (p.unfit || []).concat((p.commands_missing || []).map(function (c) { return T('command not found:') + ' ' + c; }));
    var elsewhere = (p.unfit || []).some(function (w) { return w.indexOf('only on') === 0; });
    var options = null;
    var head = el('div', { class: 'card' }, [el('div', { class: 'row' }, [
      el('div', { class: 'what' }, [el('b', { text: p.name }), p.security ? el('span', { class: 'lock' }, [svg(LOCK, 14)]) : null,
        el('div', { class: 'muted', text: p.description }),
        notes.length ? el('div', { class: 'muted warn', text: notes.join('; ') }) : null]),
      toggle(p.wanted, elsewhere, function (on, input) {
        if (!on && p.locked && !confirm(T('Turn it off?') + '\n\n' + (p.security ? T('It is a security plugin: without it, that protection is gone.') : T('AnyAssistant needs it to work as usual.')))) {
          input.checked = true;
          return;
        }
        var change = {};
        change[p.id] = on;
        api('POST', '/admin/plugins', change).then(function (r) {
          if (r.error) { input.checked = !on; problem($('.what', head), r.error); return; }
          if (options) options.classList.toggle('off', !on);
          if (r.packages) needsRestart(T('It needs its packages: bin/anyassistant setup packages, then restart.'));
          else if (r.restart) needsRestart();
        });
      })
    ])]);
    main.appendChild(head);
    if (id === 'mail') main.appendChild(el('div', { class: 'card' }, [el('div', { class: 'row link', onclick: function () { show('mail'); } }, [el('div', { class: 'what', text: T('Mail accounts') }), el('span', { class: 'chevron', text: '›' })])]));
    if (id === 'voices') main.appendChild(el('div', { class: 'card' }, [el('div', { class: 'row link', onclick: function () { show('voices'); } }, [el('div', { class: 'what', text: T('Known voices') }), el('span', { class: 'chevron', text: '›' })])]));
    if (id === 'memory') main.appendChild(el('div', { class: 'card' }, [el('div', { class: 'row link', onclick: function () { show('memory'); } }, [el('div', { class: 'what', text: T('What it remembers') }), el('span', { class: 'chevron', text: '›' })])]));
    var mine = found[1].options.filter(function (o) { return o.plugin === id; });
    if (mine.length) {
      main.appendChild(el('h2', { text: T('Options') }));
      options = el('div', { class: 'card' + (p.wanted ? '' : ' off') });
      main.appendChild(options);
      mine.forEach(function (o) { options.appendChild(option(o)); });
    }
  }).catch(function () {});
}

// --- The known voices (the plugin «voices»), and learning one on a device: the guide ---

function voicesPage(main) {
  back(main, 'plugin/voices', T('Voices'));
  main.appendChild(el('h1', { text: T('Known voices') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  var asking = null;  // whose voice is being forgotten, while it asks about what it remembers of them
  var renaming = null;  // whose name is being changed
  function forget(name, memory) {
    asking = null;
    api('POST', '/admin/voices', memory ? { forget: name, memory: memory } : { forget: name }).then(draw);
  }
  function draw(data) {
    box.innerHTML = '';
    if (data._status === 404) { box.appendChild(el('p', { class: 'muted', text: T('Turn on the plugin «Voices» to teach it who you are.') })); return; }
    if (!data.people.length) box.appendChild(el('p', { class: 'muted', text: T('Nobody yet: while nobody is known, it listens to everyone.') }));
    data.people.forEach(function (p) {
      // Their score there has dropped lately (the microphone moved, a cold…): said once as a notice.
      var warnings = (p.relearn || []).map(function (device) {
        return el('div', { class: 'muted warn', text: T('It would be good to learn their voice again on %s.').replace('%s', device) });
      });
      if (asking === p.name) {  // it remembers things about them: delete those too, or keep them under the name
        box.appendChild(el('div', { class: 'row' }, [
          el('div', { class: 'what' }, [el('b', { text: T('Also erase what it remembers about %s?').replace('%s', p.name) }),
            el('div', { class: 'muted', text: T('If you keep it and its voice is learnt again under the same name, it remembers it again.') })]),
          el('button', { class: 'secondary', text: T('Cancel'), onclick: function () { asking = null; api('GET', '/admin/voices').then(draw); } }),
          el('button', { class: 'secondary', text: T('Keep'), onclick: function () { forget(p.name, 'keep'); } }),
          el('button', { class: 'danger', text: T('Erase'), onclick: function () { forget(p.name, 'delete'); } })
        ]));
        return;
      }
      if (renaming === p.name) {  // its new name, in the row («Subi» → «Suvi»; an existing name: one voice)
        var field = el('input', { type: 'text', value: p.name });
        var save = function () {
          var to = field.value.trim();
          renaming = null;
          if (to && to !== p.name) api('POST', '/admin/voices', { rename: p.name, to: to }).then(draw);
          else api('GET', '/admin/voices').then(draw);
        };
        field.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') save(); if (ev.key === 'Escape') { renaming = null; api('GET', '/admin/voices').then(draw); } });
        box.appendChild(el('div', { class: 'row' }, [
          el('div', { class: 'what' }, [field, el('div', { class: 'muted', text: T('What it remembers about them keeps the new name too.') })]),
          el('button', { class: 'secondary', text: T('Cancel'), onclick: function () { renaming = null; api('GET', '/admin/voices').then(draw); } }),
          el('button', { text: T('Rename'), onclick: save })
        ]));
        setTimeout(function () { field.focus(); field.select(); }, 0);
        return;
      }
      box.appendChild(el('div', { class: 'row' }, [
        el('div', { class: 'what' }, [el('b', { text: p.name })].concat(warnings)),
        el('button', { class: 'secondary', text: T('Rename…'), onclick: function () { renaming = p.name; api('GET', '/admin/voices').then(draw); } }),
        el('button', { class: 'danger', text: T('Forget'), onclick: function () {
          if (p.facts) { asking = p.name; api('GET', '/admin/voices').then(draw); } else forget(p.name);
        } })
      ]));
    });
  }
  api('GET', '/admin/voices').then(function (data) {
    draw(data);
    if (data._status === 404) return;
    main.appendChild(el('p', { class: 'muted', text: T('What needs a known voice is in Settings → Security («voice_check»). On a device you can also say «aprende mi voz».') }));
    main.appendChild(el('h2', { text: T('Learn a voice') }));
    var learn = el('div', { class: 'card' });
    main.appendChild(learn);
    learn.appendChild(el('div', { class: 'row' }, [
      el('div', { class: 'what muted', text: T('A guide shows each phrase to read, one at a time.') }),
      el('button', { class: 'secondary', text: T('Learn a voice…'), onclick: function () { guide(learn, draw); } })
    ]));
    timer = setInterval(function () { api('GET', '/admin/voices').then(draw).catch(function () {}); }, 3000);  // a voice learnt on a device shows up here
  }).catch(function () {});
}

// The guide: on which device (a connected one) and whose; then the phrase to read now, which one,
// and what happens, until it ends.
function guide(learn, drawPeople) {
  learn.innerHTML = '';
  var box = el('div', { class: 'padded' });
  learn.appendChild(box);
  var device = el('select');
  var name = el('input', { placeholder: T('the person\'s: «Suvi»') });
  var note = el('p', { class: 'error' });
  var start = el('button', { text: T('Start learning'), disabled: 'disabled' });
  function row(title, field) {
    return el('div', { class: 'row' }, [el('div', { class: 'what', text: title }), el('div', { class: 'control' }, [field])]);
  }
  box.appendChild(el('h2', { class: 'tight', text: T('Learn a voice') }));
  box.appendChild(el('p', { class: 'muted', text: T('Stand in front of the device you talk to most: its microphone is the one that will hear you. Then read the phrases this window shows, one at a time.') }));
  box.appendChild(row(T('On the device'), device));
  box.appendChild(row(T('Name'), name));
  box.appendChild(note);
  box.appendChild(el('p', { class: 'end' }, [start]));
  // The connected devices, as they are now (renamed, connected), while choosing.
  function listDevices() {
    api('GET', '/devices').then(function (data) {
      var connected = data.devices.filter(function (d) { return d.connected; });
      var chosen = device.value;
      device.innerHTML = '';
      device.appendChild(el('option', { value: '', text: T('Choose one') }));
      connected.forEach(function (d) {
        device.appendChild(el('option', { value: d.id, text: d.room ? d.name + ' (' + d.room + ')' : d.name || d.id }));
      });
      device.value = chosen || '';
      start.disabled = !device.value;
    }).catch(function () {});
  }
  device.addEventListener('change', function () { start.disabled = !device.value; });
  listDevices();
  if (timer) clearInterval(timer);
  timer = setInterval(listDevices, 3000);
  start.onclick = function () {
    note.textContent = '';
    api('POST', '/admin/voices', { learn: device.value, name: name.value }).then(function (r) {
      if (r.error) { note.textContent = r.error; return; }
      follow(device.value);
    });
  };
  function follow(id) {
    clearInterval(timer);
    box.innerHTML = '';
    var cancel = el('button', { class: 'secondary', text: T('Cancel'), onclick: function () { api('POST', '/admin/voices', { cancel: id }); } });
    timer = setInterval(function () {
      api('GET', '/admin/voices').then(function (r) {
        var now = (r.learning || {})[id];
        if (!now) return;
        box.innerHTML = '';
        if (now.step === 'name') {
          box.appendChild(el('div', { class: 'between' }, [el('h2', { text: T('Tell it your name') }), cancel]));
          box.appendChild(el('p', { text: T('Say it to the device: «Me llamo Suvi».') }));
          box.appendChild(el('p', { class: 'muted', text: T('Listening on the device…') }));
        } else if (now.step === 'phrase') {
          box.appendChild(el('div', { class: 'between' }, [el('b', { text: T('Phrase %d of %d').replace('%d', now.number).replace('%d', now.total) }), cancel]));
          box.appendChild(el('progress', { value: now.number - 1, max: now.total, class: 'progress' }));
          box.appendChild(el('p', { class: 'muted', text: T('Read it out loud:') }));
          box.appendChild(el('p', { class: 'phrase', text: now.phrase }));
          if (now.again) box.appendChild(el('p', { class: 'warn', text: T('A little longer: say the whole phrase again.') }));
          box.appendChild(el('p', { class: 'muted', text: T('When it hears you, it goes on to the next one.') }));
        } else {
          clearInterval(timer);
          timer = null;
          box.appendChild(el('h2', { text: now.step === 'done' ? T('Done, %s: it knows your voice.').replace('%s', now.name)
                                                               : T('Cancelled: nothing was learnt.') }));
          box.appendChild(el('p', {}, [
            el('button', { class: 'secondary', text: T('Learn another'), onclick: function () { guide(learn, drawPeople); } }), ' ',
            el('button', { text: T('Close'), onclick: function () { show('voices'); } })
          ]));
          api('GET', '/admin/voices').then(drawPeople).catch(function () {});
        }
      }).catch(function () {});
    }, 700);
  }
}

// --- What it remembers (from the plugin «memory»'s page), what the plugin «memory» remembers: the shared facts and each person's; each one edited in place,
// deleted or moved to someone else ---

function memoryPage(main) {
  main.appendChild(el('h1', { text: T('What it remembers') }));
  var box = el('div');
  main.appendChild(box);
  function change(who, fact, what) {
    var body = { who: who, fact: fact };
    Object.keys(what).forEach(function (k) { body[k] = what[k]; });
    return api('POST', '/admin/memory', body).then(function (r) { draw(r); if (r.error) problem(box, r.error); });
  }
  function row(who, fact, names) {
    var text = el('input', { type: 'text', value: fact, class: 'field wide' });
    text.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') text.blur();
      if (e.key === 'Escape') { text.value = fact; text.blur(); }
    });
    text.addEventListener('change', function () {
      if (text.value.trim() === fact) return;
      if (!text.value.trim()) { text.value = fact; return; }
      change(who, fact, { edit: text.value });
    });
    var move = el('select', {}, [el('option', { value: '', text: T('Move to…') })]);
    if (who !== null) move.appendChild(el('option', { value: '\u0000', text: T('Shared') }));
    names.filter(function (n) { return n !== who; }).forEach(function (n) { move.appendChild(el('option', { value: n, text: n })); });
    move.addEventListener('change', function () {
      if (move.value) change(who, fact, { move: move.value === '\u0000' ? null : move.value });
    });
    return el('div', { class: 'row' }, [
      el('div', { class: 'what' }, [text]),
      move,
      el('button', { class: 'danger', text: T('Delete'), onclick: function () { change(who, fact, { delete: true }); } })
    ]);
  }
  function group(title, who, facts, names) {
    box.appendChild(el('h2', { text: title }));
    var card = el('div', { class: 'card' });
    facts.forEach(function (f) { card.appendChild(row(who, f, names)); });
    box.appendChild(card);
  }
  function draw(data) {
    box.innerHTML = '';
    if (data._status === 404 && !data.people) { box.appendChild(el('div', { class: 'card' }, [el('p', { class: 'muted', text: T('Turn on the plugin «Memory» so it remembers you from one conversation to the next.') })])); return; }
    var names = data.people.map(function (p) { return p.name; });
    var people = data.people.filter(function (p) { return p.facts.length; });
    if (!data.shared.length && !people.length) {
      box.appendChild(el('div', { class: 'card' }, [el('p', { class: 'muted', text: T('It doesn\'t remember anything yet.') })]));
    }
    if (data.shared.length) group(T('Shared'), null, data.shared, names);
    people.forEach(function (p) { group(p.name, p.name, p.facts, names); });
    box.appendChild(el('p', { class: 'muted', text: T('What is shared goes into every conversation; what is about someone, only when it recognises their voice.') }));
  }
  api('GET', '/admin/memory').then(draw).catch(function () {});
}

// --- Mail accounts besides Gmail (the plugin «mail»): add one (tried before saving), try, remove ---

function mailPage(main) {
  back(main, 'plugin/mail', T('Mail'));
  main.appendChild(el('h1', { text: T('Mail accounts') }));
  var box = el('div', { class: 'card' });
  main.appendChild(box);
  var problems = {};  // per address, what failed
  var fine = {};  // tried and working
  function draw(data) {
    box.innerHTML = '';
    if (data._status === 404) { box.appendChild(el('p', { class: 'muted', text: T('Turn on the plugin «Mail (IMAP and SMTP)» to add accounts besides Gmail.') })); return; }
    if (!data.accounts.length) box.appendChild(el('p', { class: 'muted', text: T('No accounts yet. Gmail doesn\'t go here: it works through Google (gog).') }));
    data.accounts.forEach(function (a) {
      var busy = el('span', { class: 'muted' });
      box.appendChild(el('div', { class: 'row' }, [
        el('div', { class: 'what' }, [el('b', { text: a.name || a.address }),
          el('div', { class: 'muted', text: a.address }),
          el('div', { class: 'muted small', text: 'IMAP ' + a.imap + ' · SMTP ' + a.smtp })]
          .concat((problems[a.address] || []).map(function (p) { return el('div', { class: 'problem', text: p }); }))),
        !a.password ? el('span', { class: 'error', text: T('No password') }) : fine[a.address] ? el('span', { class: 'ok', text: '✓' }) : null,
        busy,
        el('button', { class: 'secondary', text: T('Try'), onclick: function (e) {
          busy.textContent = '…';
          api('POST', '/admin/mail', { test: a.address }).then(function (r) {
            var found = r.problems || [];
            problems[a.address] = found.length ? found : null;
            fine[a.address] = !found.length;
            draw(data);
          });
        } }),
        el('button', { class: 'danger', text: T('Remove'), onclick: function () {
          api('POST', '/admin/mail', { remove: a.address }).then(draw);
        } })
      ]));
    });
    box.appendChild(el('p', { class: 'muted', text: T('New emails get a notice, the morning summary counts them, and the assistant can read them and send (with your «yes»). The password is kept in the Keychain.') }));
  }
  api('GET', '/admin/mail').then(function (data) {
    draw(data);
    if (data._status === 404) return;
    main.appendChild(el('h2', { text: T('Add an account') }));
    var address = el('input', { placeholder: 'tu@dominio.com', type: 'text' });
    var label = el('input', { placeholder: T('as you\'ll call it: «Trabajo»') });
    var secret = el('input', { type: 'password', placeholder: T('an app password, if your provider has them') });
    var imap = el('input', { placeholder: 'imap.dominio.com:993' });
    var smtp = el('input', { placeholder: 'smtp.dominio.com:465' });
    var user = el('input', { placeholder: T('the address') });
    var note = el('div');
    var busy = el('span', { class: 'muted' });
    var add = el('button', { text: T('Try and add'), disabled: 'disabled' });
    function row(title, field) {
      return el('div', { class: 'row' }, [el('div', { class: 'what', text: title }), el('div', { class: 'control' }, [field])]);
    }
    function ready() { add.disabled = address.value.indexOf('@') < 0 || !secret.value; }
    [address, secret].forEach(function (f) { f.addEventListener('input', ready); });
    address.addEventListener('change', function () {
      if (address.value.indexOf('@') < 0) return;
      api('GET', '/admin/mail?guess=' + encodeURIComponent(address.value)).then(function (r) {
        if (!imap.value && r.imap) imap.value = r.imap;
        if (!smtp.value && r.smtp) smtp.value = r.smtp;
      }).catch(function () {});
    });
    add.onclick = function () {
      busy.textContent = '…';
      add.disabled = true;
      api('POST', '/admin/mail', { add: { address: address.value, password: secret.value, name: label.value, imap: imap.value, smtp: smtp.value, user: user.value } })
        .then(function (r) {
          busy.textContent = '';
          add.disabled = false;
          note.innerHTML = '';
          if (r.problems || r.error) { (r.problems || [r.error]).forEach(function (p) { note.appendChild(el('div', { class: 'problem', text: p })); }); return; }
          [address, secret, label, imap, smtp, user].forEach(function (f) { f.value = ''; });
          draw(r);
        });
    };
    main.appendChild(el('div', { class: 'card' }, [
      row(T('Address'), address), row(T('Name'), label), row(T('Password'), secret),
      el('details', { class: 'hand' }, [el('summary', { text: T('Servers') }), row('IMAP', imap), row('SMTP', smtp), row(T('Login'), user)]),
      note,
      el('p', { class: 'end' }, [busy, ' ', add])
    ]));
  }).catch(function () {});
}

// The community (the plugin «community»): the catalog's plugins, under Plugins, «From the community»:
// what is installed and whether an update exists; install (a plugin asks first, and starts off), update,
// remove. Its themes are in the Themes page.
function community(main, toCommunity) {
  var heading = el('h2', { id: 'community', text: T('From the community') });
  main.appendChild(heading);
  if (toCommunity) heading.scrollIntoView({ block: 'start' });
  var box = el('div');
  main.appendChild(box);
  function load(refresh) {
    api('GET', '/admin/community' + (refresh ? '?refresh=1' : '')).then(function (data) {
      box.innerHTML = '';
      var card = el('div', { class: 'card' });
      box.appendChild(card);
      if (data._status === 404) { card.appendChild(el('p', { class: 'muted', text: T('Turn on the plugin «Community».') })); return; }
      if (data.error) card.appendChild(el('p', { class: 'warn', text: data.error }));
      var mine = (data.packages || []).filter(function (p) { return p.kind === 'plugin'; });
      if (!mine.length && !data.error) card.appendChild(el('p', { class: 'muted', text: T('Nothing to install yet.') }));
      mine.forEach(function (p) { card.appendChild(packageRow(p, load)); });
      card.appendChild(el('p', {}, [el('a', { href: '#plugins', text: T('Reload the catalog'), onclick: function (e) { e.preventDefault(); load(true); } })]));
      box.appendChild(el('p', { class: 'muted', text: T('Plugins other people share, from a public catalog. Every package is reviewed before it is listed. A plugin runs on this server with your permissions.') }));
    }).catch(function () {});
  }
  load(false);
}

// A package of the catalog: what it is, what is installed, and what can be done with it.
function packageRow(p, reload) {
  var busy = el('span', { class: 'muted' });
  var what = el('div', { class: 'what' });
  function install() {
    if (p.kind === 'plugin' && !confirm((p.installed ? T('Update «%s»?') : T('Install «%s»?')).replace('%s', p.name) + '\n\n' +
        T('A plugin is code that runs on this server with your permissions. Install it only if you trust its author. It starts off: turn it on in Plugins when you want to use it.'))) return;
    busy.textContent = T('Installing…');
    api('POST', '/admin/community', { install: { kind: p.kind, id: p.id }, confirm: p.kind === 'plugin' }).then(function (r) {
      busy.textContent = '';
      if (r.error) { problem(what, r.error); return; }
      if (r.restart) needsRestart(r.updated ? T('Updated. It applies after restarting.') : T('Installed. It is off: turn it on in Plugins after restarting.'));
      reload(false);
    });
  }
  function remove() {
    if (!confirm(T('Remove «%s»?').replace('%s', p.name))) return;
    api('POST', '/admin/community', { remove: { kind: p.kind, id: p.id } }).then(function (r) {
      if (r.error) { problem(what, r.error); return; }
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
    ? el('span', { class: 'badge ' + (p.update ? 'warning' : 'success'), text: p.update ? T('update available') : T('installed') + ' ' + p.installed })
    : null;
  [el('b', { text: p.name }), state,
   el('div', { class: 'muted', text: [p.author ? T('by') + ' ' + p.author : '', T('version') + ' ' + p.version].filter(Boolean).join(' · ') }),
   el('div', { class: 'muted', text: p.description }),
   p.can ? null : el('div', { class: 'muted warn', text: p.why })].forEach(function (c) { if (c) what.appendChild(c); });
  return el('div', { class: 'row' }, [what, busy].concat(buttons));
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
        el('div', { class: 'what' }, [el('b', { text: a.name.slice(0, 90) }), a.you ? el('span', { class: 'badge success', text: T('this browser') }) : null,
          el('div', { class: 'muted', text: T('since') + ' ' + ago(a.since) })]),
        el('button', { class: 'danger', text: a.you ? T('Log out') : T('Revoke'), onclick: function () {
          api('POST', '/admin/admins', a.you ? { logout: true } : { forget: a.id }).then(function (r) {
            if (a.you) location.reload(); else draw(r);
          });
        } })
      ]));
    });
  }
  api('GET', '/admin/admins').then(draw).catch(function () {});
  main.appendChild(el('h2', { text: T('A code for another browser') }));
  var shown = el('div');
  main.appendChild(el('div', { class: 'card' }, [el('div', { class: 'padded' }, [
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

// --- The sidebar: the search on top; the sections, as the Mac's windows ---

function sidebar() {
  var nav = $('nav');
  nav.innerHTML = '';
  function item(id, title) {
    nav.appendChild(el('button', { text: title, 'data-id': id, onclick: function () { show(id); } }));
  }
  if (WINDOW === 'settings' || !WINDOW) {
    var search = el('input', { type: 'search', placeholder: T('Search'), class: 'search' });
    search.addEventListener('input', function () { show(search.value.trim() ? 'search' : (current === 'search' ? 'settings' : current)); });
    nav.appendChild(search);
  }
  if (!WINDOW) { item('pair', T('Pair a device')); item('devices', T('Devices')); }
  if (WINDOW === 'settings' || !WINDOW) {
    nav.appendChild(el('div', { class: 'group', text: T('General') }));
    groups.forEach(function (g) { item('group/' + g.id, g.title); });
    nav.appendChild(el('div', { class: 'group' }));
    item('plugins', T('Plugins'));
  }
  if (!WINDOW) { nav.appendChild(el('div', { class: 'group' })); item('admins', T('Admins')); }
}

// This browser's interface language (a cookie: the themes page and the device's page here follow
// it too); Automatic: the browser's own. Not the one the assistant speaks (General).
function languagePicker(me) {
  var pick = el('select', { 'aria-label': T('Interface Language') }, [el('option', { value: 'auto', text: T('Automatic') })]
    .concat(Object.keys(me.ui_languages || {}).map(function (c) { return el('option', { value: c, text: me.ui_languages[c] }); })));
  pick.value = me.ui_language || 'auto';
  pick.addEventListener('change', function () {
    document.cookie = 'ui_language=' + pick.value + '; path=/; SameSite=Lax; max-age=' + (pick.value === 'auto' ? 0 : 31536000);
    location.reload();
  });
  return el('label', { class: 'language' }, [el('span', { text: T('Interface Language') }), pick]);
}

// --- Start ---

fetch('/admin/me', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (me) {
  texts = me.texts || {};
  document.documentElement.lang = me.lang || 'en';
  if (!me.owner) return showLogin();
  if (WINDOW) document.body.classList.add('window', 'window-' + WINDOW);
  $('#app').hidden = false;
  var restartButton = $('#restart');
  restartButton.hidden = Boolean(WINDOW);
  restartButton.textContent = T('Restart');
  restartButton.onclick = function () { if (confirm(T('Restart the server now?'))) restart(); };
  // In the Windows and Linux app's Settings too: the app follows the cookie (its menu, its face's device).
  if (!WINDOW || WINDOW === 'settings') $('aside .foot').insertBefore(languagePicker(me), restartButton);
  api('GET', '/admin/status').then(function (s) {
    $('#title').textContent = s.name;
    $('#subtitle').textContent = s.computer + ' · ' + s.version;
    document.title = WINDOW ? T({ settings: 'Settings', devices: 'Devices', pair: 'Pair a device' }[WINDOW] || 'Admin') : 'AnyAssistant · ' + T('Admin');
  }).catch(function () {});
  api('GET', '/admin/settings').then(function (data) {
    groups = data.groups || [];
  }).catch(function () {}).then(function () {
    sidebar();
    var wanted = location.hash.slice(1);
    var known = ['pair', 'devices', 'settings', 'plugins', 'community', 'admins', 'mail', 'voices', 'memory'];
    var allowed = WINDOW === 'devices' ? function (id) { return section(id) === 'devices'; }
                : WINDOW === 'pair' ? function (id) { return id === 'pair'; }
                : WINDOW === 'settings' ? function (id) { return ['pair', 'devices', 'admins'].indexOf(section(id)) < 0; }
                : function () { return true; };
    var fits = (known.indexOf(wanted) >= 0 || /^(plugin|device|group)\//.test(wanted)) && allowed(wanted);
    show(fits ? wanted : (WINDOW === 'devices' ? 'devices' : WINDOW === 'settings' ? 'settings' : 'pair'));
  });
}).catch(unavailable);

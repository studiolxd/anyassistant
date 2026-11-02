// The themes: every state of a theme at once (each view is the page in ?demo=<state>),
// reloading them when the theme's files change. Open it on the Mac while you design one.

var STATES = ['asleep', 'awake', 'hearing', 'transcribing', 'thinking', 'looking', 'speaking', 'question', 'alarm', 'error'];
var select = document.getElementById('theme');
var version = null;

function views(name) {
  var main = document.getElementById('states');
  main.innerHTML = '';
  STATES.forEach(function (state) {
    var figure = document.createElement('figure');
    var frame = document.createElement('div');
    frame.className = 'frame';
    var iframe = document.createElement('iframe');
    iframe.src = '/?demo=' + state + '&theme=' + encodeURIComponent(name);
    frame.appendChild(iframe);
    // A cover over the view (the page inside would take the tap): it opens it full screen.
    var cover = document.createElement('div');
    cover.className = 'cover';
    cover.onclick = function () { open(STATES.indexOf(state)); };
    frame.appendChild(cover);
    var caption = document.createElement('figcaption');
    caption.textContent = state;
    figure.appendChild(frame);
    figure.appendChild(caption);
    main.appendChild(figure);
  });
}

function config(name) {
  return fetch('/config?theme=' + encodeURIComponent(name)).then(function (r) { return r.json(); });
}

function fill(data) {
  select.innerHTML = '';
  data.themes.forEach(function (theme) {
    var option = document.createElement('option');
    option.value = theme.name;
    option.textContent = theme.title + ' (' + theme.name + ')';
    select.appendChild(option);
  });
  select.value = data.theme.name;
}

config(new URLSearchParams(location.search).get('theme') || '').then(function (data) {
  fill(data);
  show(data);
  community();
});

function show(data) {
  version = data.theme.version;
  var about = data.themes.filter(function (s) { return s.name === data.theme.name; })[0];
  document.getElementById('about').textContent = about ? about.description : '';
  history.replaceState(null, '', '/themes?theme=' + encodeURIComponent(data.theme.name));
  views(data.theme.name);
  sounds(data.theme.name);
}

// Its sounds (when it wakes, falls asleep, an alarm rings): a button each to hear it, as it
// plays (/sounds/<kind>.wav), marked when it is the theme's own (sounds/<kind>.wav in it).
var SOUNDS = ['wake', 'sleep', 'alarm'];
function soundName(kind) {
  return kind === 'wake' ? T('When it wakes') : kind === 'sleep' ? T('When it falls asleep') : T('Alarm');
}
var player = new Audio();
function sounds(name) {
  var row = document.getElementById('sounds');
  row.innerHTML = '';
  var title = document.createElement('span');
  title.textContent = T('Sounds');
  row.appendChild(title);
  SOUNDS.forEach(function (sound) {
    var url = '/sounds/' + sound + '.wav?theme=' + encodeURIComponent(name) + '&v=' + version;
    var button = document.createElement('button');
    button.className = 'secondary';
    button.textContent = '▶ ' + soundName(sound);
    button.onclick = function () { player.pause(); player.src = url; player.play().catch(function () {}); };
    row.appendChild(button);
    fetch(url).then(function (r) {
      if (!r.ok) { button.hidden = true; return; }
      var own = r.headers.get('X-Theme-Sound') === '1';
      if (own) button.className = 'secondary own';
      var whose = document.createElement('small');
      whose.textContent = own ? T('the theme\'s') : T('the system\'s');
      button.appendChild(whose);
    });
  });
}

select.onchange = function () { config(select.value).then(show); };

// When a file of the theme changes, the views reload.
setInterval(function () {
  config(select.value).then(function (data) {
    if (data.theme.version === version) return;
    show(data);
    var note = document.getElementById('reloaded');
    note.textContent = 'reloaded ' + new Date().toLocaleTimeString();
    setTimeout(function () { note.textContent = ''; }, 3000);
  });
}, 1500);

// One state full screen, as on the device (this screen's own size and orientation):
// ✕ or Esc goes back to all of them; ‹ › or the arrows go through the states.
var full = document.getElementById('full');
var current = 0;

function open(index) {
  current = (index + STATES.length) % STATES.length;
  document.getElementById('full-view').src = '/?demo=' + STATES[current] + '&theme=' + encodeURIComponent(select.value);
  document.getElementById('full-state').textContent = STATES[current];
  full.hidden = false;
}

function close() {
  full.hidden = true;
  document.getElementById('full-view').src = 'about:blank';
}

document.getElementById('full-close').onclick = close;
document.getElementById('full-previous').onclick = function () { open(current - 1); };
document.getElementById('full-next').onclick = function () { open(current + 1); };
document.addEventListener('keydown', function (ev) {
  if (full.hidden) return;
  if (ev.key === 'Escape') close();
  else if (ev.key === 'ArrowLeft') open(current - 1);
  else if (ev.key === 'ArrowRight') open(current + 1);
});

// From the community (the plugin «community», for the owner: this computer or an admin's
// browser): the catalog's themes, what is installed and whether an update exists; install,
// update, remove. An installed theme is shown at once.
var texts = {};
function T(english) { return texts[english] || english; }

// «Instalados» (the theme, its sounds and states) and «De la comunidad» (the catalog).
function tabs() {
  var installed = document.getElementById('tab-installed');
  var catalog = document.getElementById('tab-community');
  installed.textContent = T('Installed themes');
  catalog.textContent = T('From the community');
  installed.onclick = function () { showTab(false); };
  catalog.onclick = function () { showTab(true); };
}
function showTab(community) {
  document.body.classList.toggle('community', community);
  document.getElementById('community').hidden = !community;
  document.getElementById('tab-installed').classList.toggle('on', !community);
  document.getElementById('tab-community').classList.toggle('on', community);
}

// /themes#community (an update announced by the app): straight to «From the community». The #part
// goes once shown, so asking again (the same address) is a change the page hears.
function asked() {
  if (location.hash !== '#community' || document.getElementById('tabs').hidden) return;  // tabs: the owner's
  history.replaceState(null, '', location.pathname + location.search);
  showTab(true);
}
window.addEventListener('hashchange', asked);

function community() {
  var section = document.getElementById('community');
  var search = document.getElementById('community-search');
  var PER_PAGE = 8;  // themes a page
  var all = [];  // the catalog's themes
  var page = 0;
  var installing = {};  // ids being installed: their button says so, off
  search.oninput = function () { page = 0; draw(); };
  document.getElementById('pager-previous').onclick = function () { page -= 1; draw(); };
  document.getElementById('pager-next').onclick = function () { page += 1; draw(); };
  fetch('/admin/me', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (me) {
    if (!me.owner) return;
    texts = me.texts || {};
    sounds(select.value);  // in its language
    document.getElementById('theme-label').textContent = T('Theme');
    document.title = 'AnyAssistant · ' + T('Themes');
    tabs();
    document.getElementById('community-title').textContent = T('Community themes');
    search.placeholder = T('Search');
    load();
  }).catch(function () {});

  function call(method, path, body) {
    return fetch(path, { method: method, credentials: 'same-origin',
                         headers: body ? { 'Content-Type': 'application/json' } : {},
                         body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (data) { data._status = r.status; return data; }); });
  }

  function load() {
    call('GET', '/admin/community').then(function (data) {
      if (data._status !== 200) return;  // the plugin is off, or not the owner
      document.getElementById('tabs').hidden = false;
      asked();
      section.querySelector('.error').textContent = data.error || '';
      all = (data.packages || []).filter(function (p) { return p.kind === 'theme'; });
      draw();
    });
  }

  // The themes that match the search, a page of them, and the pager.
  function draw() {
    var words = search.value.trim().toLowerCase();
    var found = all.filter(function (p) {
      return !words || [p.name, p.description, p.author].join(' ').toLowerCase().indexOf(words) >= 0;
    });
    var pages = Math.max(1, Math.ceil(found.length / PER_PAGE));
    page = Math.min(Math.max(page, 0), pages - 1);
    var list = document.getElementById('packages');
    list.innerHTML = '';
    if (!found.length) {
      var none = document.createElement('p');
      none.className = 'muted';
      none.textContent = all.length ? T('No results') : T('Nothing to install yet.');
      list.appendChild(none);
    } else {
      var card = document.createElement('div');
      card.className = 'card';
      found.slice(page * PER_PAGE, (page + 1) * PER_PAGE).forEach(function (p) { card.appendChild(row(p)); });
      list.appendChild(card);
    }
    document.getElementById('pager').hidden = pages < 2;
    // The pages around this one: two before and two after, those there are; this one marked.
    var numbers = document.getElementById('pager-pages');
    numbers.innerHTML = '';
    for (var n = Math.max(0, page - 2); n <= Math.min(pages - 1, page + 2); n++) {
      var b = document.createElement('button');
      b.className = n === page ? 'button' : 'button secondary';
      b.textContent = n + 1;
      if (n === page) b.setAttribute('aria-current', 'page');
      b.onclick = (function (to) { return function () { page = to; draw(); }; })(n);
      numbers.appendChild(b);
    }
    document.getElementById('pager-previous').disabled = page === 0;
    document.getElementById('pager-next').disabled = page >= pages - 1;
  }

  function row(p) {
    var made = document.createElement('div');
    made.className = 'row pkg';
    if (p.screenshot) {
      var img = document.createElement('img');
      img.src = '/admin/community/image?kind=theme&id=' + encodeURIComponent(p.id);
      img.alt = p.name;
      img.className = 'zoomable';
      img.onclick = function () { enlarge(img.src, p.name); };
      made.appendChild(img);
    }
    var about = document.createElement('div');
    about.className = 'about';
    var title = document.createElement('b');
    title.textContent = p.name;
    about.appendChild(title);
    if (p.installed) {  // the version you have; with a newer one, «1.0.0 → 1.1.0»
      var version = document.createElement('span');
      version.className = 'badge ' + (p.update ? 'warning' : 'success');
      version.textContent = p.update ? p.installed + ' → ' + p.version : p.installed;
      if (p.update) version.title = T('update available');
      about.appendChild(version);
    }
    var meta = document.createElement('div');
    meta.className = 'muted';
    meta.textContent = [p.author ? T('by') + ' ' + p.author : '', T('version') + ' ' + p.version].filter(Boolean).join(' · ');
    about.appendChild(meta);
    var text = document.createElement('div');
    text.className = 'muted';
    text.textContent = p.can ? p.description : p.description + ' — ' + p.why;
    about.appendChild(text);
    made.appendChild(about);
    function button(label, className, action, off) {
      var b = document.createElement('button');
      b.textContent = label;
      b.className = 'button' + (className ? ' ' + className : '');
      b.disabled = !!off;
      b.onclick = action;
      made.appendChild(b);
    }
    // Installing it: its button says so, off, until it's done; it stays on this tab (the selector
    // on the other gets it).
    function install() {
      installing[p.id] = true;
      draw();
      call('POST', '/admin/community', { install: { kind: 'theme', id: p.id } }).then(function (r) {
        delete installing[p.id];
        if (r.error) alert(r.error);
        config(select.value).then(fill);
        load();
      });
    }
    function uninstall() {
      if (!confirm(T('Uninstall «%s»?').replace('%s', p.name))) return;
      call('POST', '/admin/community', { remove: { kind: 'theme', id: p.id } }).then(function (r) {
        if (r.error) { alert(r.error); return; }
        var shown = select.value === p.id;
        config(shown ? '' : select.value).then(function (data) { fill(data); if (shown) show(data); });
        load();
      });
    }
    if (installing[p.id]) {
      button(T('Installing…'), '', null, true);
    } else if (p.installed) {
      if (p.update && p.can) button(T('Update'), '', install);
      button(T('Uninstall'), 'danger', uninstall);
    } else if (p.can) {
      button(T('Install'), '', install);
    }
    return made;
  }
}

// A screenshot, large (the design system's lightbox): a tap, Esc or ✕ closes it.
function enlarge(src, name) {
  var box = document.createElement('div');
  box.className = 'lightbox';
  var img = document.createElement('img');
  img.src = src;
  img.alt = name;
  var bar = document.createElement('div');  // as the states' full view: ✕ in the lightbox's bar
  bar.className = 'bar';
  var close = document.createElement('button');
  close.textContent = '✕';
  close.setAttribute('aria-label', T('Close'));
  bar.appendChild(close);
  box.appendChild(img);
  box.appendChild(bar);
  var done = function () {
    document.removeEventListener('keydown', esc);
    box.remove();
  };
  var esc = function (ev) { if (ev.key === 'Escape') done(); };
  box.onclick = done;
  document.addEventListener('keydown', esc);
  document.body.appendChild(box);
}

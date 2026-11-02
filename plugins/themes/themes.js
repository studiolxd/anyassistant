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

function community() {
  var section = document.getElementById('community');
  fetch('/admin/me', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (me) {
    if (!me.owner) return;
    texts = me.texts || {};
    section.querySelector('h2').textContent = T('From the community');
    section.querySelector('.lead').textContent = T('Themes and plugins other people share, from a public catalog. Every package is reviewed before it is listed.');
    load(false);
  }).catch(function () {});

  function call(method, path, body) {
    return fetch(path, { method: method, credentials: 'same-origin',
                         headers: body ? { 'Content-Type': 'application/json' } : {},
                         body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (data) { data._status = r.status; return data; }); });
  }

  function load(refresh) {
    call('GET', '/admin/community' + (refresh ? '?refresh=1' : '')).then(function (data) {
      if (data._status !== 200) return;  // the plugin is off, or not the owner
      section.hidden = false;
      section.querySelector('.error').textContent = data.error || '';
      var list = document.getElementById('packages');
      list.innerHTML = '';
      var themes = (data.packages || []).filter(function (p) { return p.kind === 'theme'; });
      if (!themes.length && !data.error) list.textContent = T('Nothing to install yet.');
      themes.forEach(function (p) { list.appendChild(row(p)); });
      var again = document.createElement('button');
      again.className = 'quiet';
      again.textContent = T('Reload the catalog');
      again.onclick = function () { load(true); };
      list.appendChild(again);
    });
  }

  function row(p) {
    var made = document.createElement('div');
    made.className = 'pkg';
    if (p.screenshot) {
      var img = document.createElement('img');
      img.src = '/admin/community/image?kind=theme&id=' + encodeURIComponent(p.id);
      img.alt = '';
      made.appendChild(img);
    }
    var about = document.createElement('div');
    about.className = 'about';
    var title = document.createElement('b');
    title.textContent = p.name;
    about.appendChild(title);
    if (p.installed) {
      var state = document.createElement('span');
      state.className = 'pill' + (p.update ? ' warn' : '');
      state.textContent = p.update ? T('update available') : T('installed') + ' ' + p.installed;
      about.appendChild(state);
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
    var note = document.createElement('span');
    note.className = 'muted';
    made.appendChild(note);
    function button(label, className, action) {
      var b = document.createElement('button');
      b.textContent = label;
      b.className = className;
      b.onclick = action;
      made.appendChild(b);
    }
    function install() {
      note.textContent = T('Installing…');
      call('POST', '/admin/community', { install: { kind: 'theme', id: p.id } }).then(function (r) {
        note.textContent = '';
        if (r.error) { alert(r.error); return; }
        config(p.id).then(function (data) { fill(data); show(data); });  // the new one, on screen
        load(false);
      });
    }
    function remove() {
      if (!confirm(T('Remove «%s»?').replace('%s', p.name))) return;
      call('POST', '/admin/community', { remove: { kind: 'theme', id: p.id } }).then(function (r) {
        if (r.error) { alert(r.error); return; }
        config('').then(function (data) { fill(data); show(data); });
        load(false);
      });
    }
    if (p.installed) {
      if (p.update && p.can) button(T('Update'), '', install);
      button(T('Remove'), 'danger', remove);
    } else if (p.can) {
      button(T('Install'), '', install);
    }
    return made;
  }
}

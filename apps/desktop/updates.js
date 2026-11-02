// Updates of what came from the community (the plugin «community»), as the Mac's Updates.swift:
// the server looks for them once a day (GET /admin/community/updates says what it found); the app
// shows a notification once per new version and an item in the tray's menu while they wait. A
// click opens where to install them. Nothing is installed by itself. Here, what is decided (main.js
// shows it); its tests: test/updates.test.js.

/// What the server answered, against the last notice shown: {pending, notice, announce}. pending:
/// the updates waiting (the menu's item); notice: the notice's number to remember (null: nothing
/// new); announce: the ones to show in a notification (none if they were installed meanwhile).
function read(answer, seen) {
  const pending = (answer && Array.isArray(answer.updates)) ? answer.updates : [];
  const notice = answer && answer.notice;
  if (!notice || !Number.isInteger(notice.id) || notice.id <= (seen || 0)) return { pending, notice: null, announce: [] };
  return { pending, notice: notice.id, announce: Array.isArray(notice.updates) ? notice.updates : [] };
}

/// «There's an update of Bedside (1.1.0)», or «There are updates of 2 themes and plugins».
function sentence(updates, T) {
  if (updates.length === 1) return T('There\'s an update of %s (%s)', updates[0].name, updates[0].to);
  return T('There are updates of %s themes and plugins', updates.length);
}

/// Where to install them: the themes page if they are all themes; else Settings → Plugins.
function place(updates) {
  return updates.every((u) => u.kind === 'theme') ? 'themes' : 'plugins';
}

module.exports = { read, sentence, place };

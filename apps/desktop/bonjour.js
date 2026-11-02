// The AnyAssistant servers announcing themselves on this network («_anyassistant._tcp», the
// plugin «bonjour»), for the installer's «Connect to another server»: as the Mac app lists them.
// Plain mDNS over UDP (no library): a PTR question every few seconds, asking for unicast replies
// (so it needs no port 5353 of its own), and the answers' SRV, TXT and A records. Its TXT record
// says the assistant's name, the computer, whether pairing is on and its address.

const dgram = require('dgram');
const { EventEmitter } = require('events');

const SERVICE = '_anyassistant._tcp.local';
const GROUP = '224.0.0.251';
const PORT = 5353;

function question() {
  const parts = SERVICE.split('.').map((label) => Buffer.concat([Buffer.from([label.length]), Buffer.from(label)]));
  const name = Buffer.concat([...parts, Buffer.from([0])]);
  const header = Buffer.from([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]);  // one question
  return Buffer.concat([header, name, Buffer.from([0, 12, 0x80, 1])]);  // PTR, IN, unicast reply wanted
}

// A name at «at», following compression pointers; [name, where it ends].
function readName(message, at) {
  const labels = [];
  let end = null;
  for (let hops = 0; hops < 32; hops += 1) {
    const length = message[at];
    if (length === undefined) break;
    if (length === 0) { at += 1; break; }
    if ((length & 0xc0) === 0xc0) {
      if (end === null) end = at + 2;
      at = ((length & 0x3f) << 8) | message[at + 1];
      continue;
    }
    labels.push(message.toString('utf8', at + 1, at + 1 + length));
    at += 1 + length;
  }
  return [labels.join('.'), end === null ? at : end];
}

function parse(message) {
  const records = [];
  try {
    const questions = message.readUInt16BE(4);
    const answers = message.readUInt16BE(6) + message.readUInt16BE(8) + message.readUInt16BE(10);
    let at = 12;
    for (let i = 0; i < questions; i += 1) { at = readName(message, at)[1] + 4; }
    for (let i = 0; i < answers; i += 1) {
      const [name, after] = readName(message, at);
      const type = message.readUInt16BE(after);
      const length = message.readUInt16BE(after + 8);
      const data = after + 10;
      if (type === 12) records.push({ name, type: 'PTR', value: readName(message, data)[0] });
      else if (type === 33) records.push({ name, type: 'SRV', port: message.readUInt16BE(data + 4), target: readName(message, data + 6)[0] });
      else if (type === 1 && length === 4) records.push({ name, type: 'A', address: Array.from(message.subarray(data, data + 4)).join('.') });
      else if (type === 16) {
        const txt = {};
        let p = data;
        while (p < data + length) {
          const n = message[p];
          const entry = message.toString('utf8', p + 1, p + 1 + n);
          const eq = entry.indexOf('=');
          if (eq > 0) txt[entry.slice(0, eq)] = entry.slice(eq + 1);
          p += 1 + n;
        }
        records.push({ name, type: 'TXT', txt });
      }
      at = data + length;
    }
  } catch (e) { /* not for us */ }
  return records;
}

/// browser.servers: [{id, assistant, computer, address, port, pairing}]; «change» when they change.
class Browser extends EventEmitter {
  constructor() {
    super();
    this.found = {};  // by instance name: {srv, txt, a, seen}
    this.addresses = {};  // host → address
    this.socket = null;
    this.timer = null;
  }

  get servers() {
    const now = Date.now();
    return Object.entries(this.found)
      .filter(([, s]) => s.srv && s.txt && now - s.seen < 20000)
      .map(([id, s]) => ({
        id, assistant: s.txt.name || 'AnyAssistant',
        computer: s.txt.computer || id.replace(/^AnyAssistant on /, ''),
        address: s.txt.address || this.addresses[s.srv.target] || s.srv.target.replace(/\.$/, ''),
        port: parseInt(s.txt.port, 10) || s.srv.port, pairing: s.txt.pairing !== '0',
      }))
      .sort((a, b) => a.computer.localeCompare(b.computer));
  }

  start() {
    if (this.socket) return;
    try {
      this.socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
      this.socket.on('error', () => this.stop());
      this.socket.on('message', (message) => this.heard(message));
      this.socket.bind(0, () => {
        try { this.socket.setMulticastTTL(255); } catch (e) { /* */ }
        this.ask();
        this.timer = setInterval(() => this.ask(), 3000);
      });
    } catch (e) { this.socket = null; }
  }

  ask() {
    if (!this.socket) return;
    try { this.socket.send(question(), PORT, GROUP); } catch (e) { /* no network */ }
  }

  heard(message) {
    let changed = false;
    for (const record of parse(message)) {
      if (record.type === 'A') { this.addresses[record.name] = record.address; changed = true; }
      if (!record.name.endsWith(SERVICE) || record.type === 'PTR') continue;
      const id = record.name.slice(0, -SERVICE.length - 1);
      const entry = this.found[id] || (this.found[id] = {});
      if (record.type === 'SRV') entry.srv = record;
      if (record.type === 'TXT') entry.txt = record.txt;
      entry.seen = Date.now();
      changed = true;
    }
    if (changed) this.emit('change');
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (this.socket) { try { this.socket.close(); } catch (e) { /* */ } }
    this.socket = null;
  }
}

module.exports = { Browser, parse, question };

// Settings and plugins, from the app: the server's /admin/… (plugins/admin, only from the
// Mac), in the active language. A change that needs it installs packages or restarts.

import SwiftUI

struct Pair: Identifiable, Equatable {
    let id = UUID()
    var key: String
    var value: String
}

final class OptionItem: ObservableObject, Identifiable {
    let name: String
    let group: String
    let kind: String  // text, longtext, bool, int, float, choice, json, dict
    let help: String
    let live: Bool
    let choices: [String]?
    let placeholder: String  // what an empty one uses: «Mónica · la del idioma»
    @Published var text: String  // what the field shows
    @Published var flag: Bool
    @Published var pairs: [Pair]  // dict (and voice set per language)

    var id: String { name }
    /// Edited as name → value pairs: a dict kind, or a json one that holds a dict (one voice per language).
    var isDict: Bool { kind == "dict" || (kind == "json" && !pairs.isEmpty) }

    init(_ raw: [String: Any]) {
        name = raw["name"] as? String ?? "?"
        group = raw["group"] as? String ?? ""
        kind = raw["kind"] as? String ?? "text"
        help = raw["help"] as? String ?? ""
        live = raw["live"] as? Bool ?? false
        choices = (raw["choices"] as? [Any])?.map { "\($0)" }
        let value = raw["value"]
        flag = value as? Bool ?? false
        if let dict = value as? [String: Any] {
            pairs = dict.keys.sorted().map { Pair(key: $0, value: "\(dict[$0]!)") }
            text = ""
        } else {
            pairs = []
            text = OptionItem.show(value, kind: kind)
        }
        let current = OptionItem.show(raw["current"], kind: kind)
        let empty = raw["empty"] as? String ?? ""
        placeholder = [current, empty].filter { !$0.isEmpty && $0 != "{}" }.joined(separator: " · ")
    }

    static func show(_ value: Any?, kind: String) -> String {
        guard let value, !(value is NSNull) else { return "" }
        if let lines = value as? [Any] { return lines.map { "\($0)" }.joined(separator: "\n") }
        if let dict = value as? [String: Any] {
            return dict.keys.sorted().map { "\($0): \(dict[$0]!)" }.joined(separator: ", ")
        }
        if let number = value as? NSNumber, kind == "float" { return "\(number.doubleValue)" }
        return "\(value)"
    }

    /// The value to send, of its kind (NSNull: back to empty, as it comes).
    var sent: Any {
        if isDict {
            let filled = pairs.filter { !$0.key.trimmingCharacters(in: .whitespaces).isEmpty }
            if filled.isEmpty { return NSNull() }
            return Dictionary(filled.map { ($0.key.trimmingCharacters(in: .whitespaces), $0.value) },
                              uniquingKeysWith: { _, last in last })
        }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        switch kind {
        case "bool": return flag
        case "int": return Int(trimmed).map { $0 as Any } ?? NSNull()
        case "float": return Double(trimmed.replacingOccurrences(of: ",", with: ".")).map { $0 as Any } ?? NSNull()
        default: return trimmed.isEmpty ? NSNull() : (kind == "longtext" ? text : trimmed)
        }
    }
}

struct PluginItem: Identifiable {
    let id: String
    let name: String
    let description: String
    let kind: String
    var on: Bool
    let locked: Bool
    let security: Bool
    let yours: Bool
    let unfit: [String]
    let missing: [String]
}

@MainActor
final class Admin: ObservableObject {
    @Published var groups: [(id: String, title: String)] = []
    @Published var options: [OptionItem] = []
    @Published var plugins: [PluginItem] = []
    @Published var note: String?
    @Published var error: String?
    @Published var restartNeeded = false

    let server = Server.shared

    private func call(_ path: String, _ body: [String: Any]? = nil) async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/\(path)")!)
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request),
              let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            error = T("The server isn't answering: is it running?")
            return nil
        }
        if (response as? HTTPURLResponse)?.statusCode != 200 {
            error = answer["error"] as? String ?? T("It couldn't be saved.")
            return nil
        }
        error = nil
        return answer
    }

    func load() async {
        await loadSettings()
        await loadPlugins()
    }

    func loadSettings() async {
        if let answer = await call("settings") {
            groups = (answer["groups"] as? [[String: Any]] ?? []).map {
                (id: $0["id"] as? String ?? "", title: $0["title"] as? String ?? "")
            }
            options = (answer["options"] as? [[String: Any]] ?? []).map(OptionItem.init)
        }
    }

    /// The plugins as they are now: they change by voice too («desactiva…»).
    func loadPlugins() async {
        if let answer = await call("plugins") {
            plugins = (answer["plugins"] as? [[String: Any]] ?? []).map {
                PluginItem(id: $0["id"] as? String ?? "", name: $0["name"] as? String ?? "",
                           description: $0["description"] as? String ?? "", kind: $0["kind"] as? String ?? "",
                           on: $0["on"] as? Bool ?? false, locked: $0["locked"] as? Bool ?? false,
                           security: $0["security"] as? Bool ?? false, yours: $0["yours"] as? Bool ?? false,
                           unfit: $0["unfit"] as? [String] ?? [], missing: $0["commands_missing"] as? [String] ?? [])
            }
        }
    }

    func save(_ option: OptionItem) async {
        guard let answer = await call("settings", [option.name: option.sent]) else { return }
        if answer["restart"] as? Bool == true { restartNeeded = true }
        note = T("Saved.")
    }

    func turn(_ plugin: PluginItem, on: Bool) async {
        guard let answer = await call("plugins", [plugin.id: on]) else { return }
        if answer["packages"] as? Bool == true {
            note = T("Installing what it needs…")
            await server.run(server.program.appending(path: "bin/anyassistant"), ["setup", "packages"])
            server.restart()
            note = T("Installed; restarting.")
        } else if answer["restart"] as? Bool == true {
            restartNeeded = true
        }
        await load()
    }

    func restart() {
        server.restart()
        restartNeeded = false
        note = T("Restarting…")
    }
}

struct SettingsView: View {
    @StateObject private var admin = Admin()
    @State private var section: String? = "plugins"

    var body: some View {
        // The sections always visible: no button to fold the sidebar (there are only a few).
        NavigationSplitView(columnVisibility: .constant(.all)) {
            List(selection: $section) {
                Label(T("Plugins"), systemImage: "puzzlepiece.extension").tag("plugins")
                Section(T("Settings")) {
                    ForEach(admin.groups, id: \.id) { group in
                        Text(group.title).tag(group.id)
                    }
                }
            }
            .navigationSplitViewColumnWidth(200)
            .toolbar(removing: .sidebarToggle)
        } detail: {
            VStack(spacing: 0) {
                if admin.restartNeeded {
                    HStack {
                        Text(T("Some changes apply after restarting."))
                        Spacer()
                        Button(T("Restart")) { admin.restart() }
                    }
                    .padding(10).background(.yellow.opacity(0.2))
                }
                if let error = admin.error {
                    Text(error).foregroundStyle(.red).padding(8)
                }
                if section == "plugins" {
                    PluginsView(admin: admin)
                } else if let section {
                    OptionsView(admin: admin, group: section)
                }
                if let note = admin.note {
                    Text(note).font(.caption).foregroundStyle(.secondary).padding(6)
                }
            }
        }
        .task { await admin.load() }
        // Kept up to date: the plugins every few seconds (they change by voice too); the
        // options when you come back to the window (not while you type in one).
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            Task { await admin.loadPlugins() }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            Task { await admin.load() }
        }
    }
}

struct OptionsView: View {
    @ObservedObject var admin: Admin
    let group: String

    var body: some View {
        Form {
            ForEach(admin.options.filter { $0.group == group }) { option in
                OptionRow(option: option, admin: admin)
            }
        }
        .formStyle(.grouped)
    }
}

struct OptionRow: View {
    @ObservedObject var option: OptionItem
    let admin: Admin
    @FocusState private var editing: Bool
    @State private var saved = ""  // what was last saved: not saved again for nothing
    @State private var pending: Task<Void, Never>?  // a save a moment after you stop typing

    /// Its help, as a title («La hora mientras duerme»); its name goes below.
    var label: String { option.help.prefix(1).uppercased() + option.help.dropFirst() }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            switch option.kind {
            case "bool":
                Toggle(label, isOn: $option.flag)
                    .onChange(of: option.flag) { _, _ in Task { await admin.save(option) } }
            case "choice" where option.choices != nil:
                Picker(label, selection: $option.text) {
                    if option.text.isEmpty { Text(option.placeholder).tag("") }
                    ForEach(option.choices!, id: \.self) { Text($0).tag($0) }
                }
                .onChange(of: option.text) { _, _ in Task { await admin.save(option) } }
            case "longtext":
                Text(label)
                TextEditor(text: $option.text)
                    .font(.body).frame(minHeight: 110)
                    .focused($editing)
                    .onChange(of: editing) { _, now in if !now { save() } }
                    .onChange(of: option.text) { _, _ in saveSoon() }  // no button: it saves itself
                    .overlay(alignment: .topLeading) {
                        if option.text.isEmpty {
                            Text(option.placeholder).foregroundStyle(.tertiary).padding(.top, 1).padding(.leading, 5)
                                .allowsHitTesting(false)
                        }
                    }
            default:
                if option.isDict {
                    DictEditor(option: option, label: label, admin: admin)
                } else {
                    TextField(label, text: $option.text, prompt: Text(option.placeholder))
                        .focused($editing)
                        .onSubmit { save() }
                        .onChange(of: editing) { _, now in if !now { save() } }  // leaving the field saves it
                }
            }
            Text(option.name + (option.live ? "" : " · " + T("needs a restart")))
                .font(.caption.monospaced()).foregroundStyle(.secondary)
        }
        .onAppear { saved = option.text }
    }
}

extension OptionRow {
    /// Saves the field if it changed since it was loaded or last saved.
    func save() {
        pending?.cancel()
        guard option.text != saved else { return }
        saved = option.text
        Task { await admin.save(option) }
    }

    /// Saves it a second after the last keystroke.
    func saveSoon() {
        pending?.cancel()
        pending = Task {
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            if !Task.isCancelled { save() }
        }
    }
}

/// Name → value pairs (detail levels, the skin's options, a voice per language): rows to edit.
struct DictEditor: View {
    @ObservedObject var option: OptionItem
    let label: String
    let admin: Admin
    @State private var pending: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label)
            if option.pairs.isEmpty {
                Text(option.placeholder).foregroundStyle(.tertiary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 6) {
                    GridRow {
                        Text(T("Name")).font(.caption).foregroundStyle(.secondary)
                        Text(T("Value")).font(.caption).foregroundStyle(.secondary)
                        Color.clear.frame(width: 16, height: 1)
                    }
                    ForEach($option.pairs) { $pair in
                        GridRow(alignment: .top) {
                            TextField("", text: $pair.key, prompt: Text(T("name")))
                                .textFieldStyle(.roundedBorder).labelsHidden().frame(width: 150)
                            TextField("", text: $pair.value, prompt: Text(T("value")), axis: .vertical)
                                .textFieldStyle(.roundedBorder).labelsHidden().lineLimit(1...4)
                            Button {
                                option.pairs.removeAll { $0.id == pair.id }
                            } label: {
                                Image(systemName: "minus.circle.fill").foregroundStyle(.secondary)
                            }
                            .buttonStyle(.borderless).help(T("Remove"))
                        }
                    }
                }
            }
            Button {
                option.pairs.append(Pair(key: "", value: ""))
            } label: {
                Label(T("Add"), systemImage: "plus.circle")
            }
            .buttonStyle(.borderless)
        }
        .onChange(of: option.pairs) { _, _ in saveSoon() }  // no button: it saves itself
    }

    func saveSoon() {
        pending?.cancel()
        pending = Task {
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            if !Task.isCancelled { await admin.save(option) }
        }
    }
}

struct PluginsView: View {
    @ObservedObject var admin: Admin
    @State private var asking: PluginItem?

    let kinds = ["feature", "skill", "library", "brain", "llm", "stt", "tts", "wake", "vad"]

    var body: some View {
        Form {
            ForEach(kinds, id: \.self) { kind in
                let found = admin.plugins.filter { $0.kind == kind }
                if !found.isEmpty {
                    Section(title(kind)) {
                        ForEach(found) { plugin in row(plugin) }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .alert(T("Turn it off?"), isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }),
               presenting: asking) { plugin in
            Button(T("Turn it off"), role: .destructive) { Task { await admin.turn(plugin, on: false) } }
            Button(T("Cancel"), role: .cancel) {}
        } message: { plugin in
            Text(plugin.security
                 ? T("It is a security plugin: without it, that protection is gone.")
                 : T("AnyAssistant needs it to work as usual."))
        }
    }

    func row(_ plugin: PluginItem) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Toggle(isOn: Binding(get: { plugin.on }, set: { on in
                if !on && plugin.locked { asking = plugin } else { Task { await admin.turn(plugin, on: on) } }
            })) {
                HStack(spacing: 6) {
                    Text(plugin.name)
                    if plugin.security { Image(systemName: "lock.shield").foregroundStyle(.secondary) }
                    if plugin.yours { Text(T("yours")).font(.caption).foregroundStyle(.secondary) }
                }
            }
            Text(plugin.description).font(.caption).foregroundStyle(.secondary)
            ForEach(plugin.unfit + plugin.missing.map { T("command not found:") + " " + $0 }, id: \.self) {
                Text($0).font(.caption).foregroundStyle(.orange)
            }
        }
    }

    func title(_ kind: String) -> String {
        switch kind {
        case "feature": T("Features")
        case "skill": T("Skills")
        case "brain": T("Brain")
        case "llm": T("LLMs")
        case "stt": T("Speech recognition")
        case "tts": T("Voices")
        case "wake": T("Wake word")
        case "vad": T("Voice detection")
        case "library": T("Libraries")
        default: kind
        }
    }
}

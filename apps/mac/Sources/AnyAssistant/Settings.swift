// Settings and plugins, from the app: the server's /admin/… (plugins/admin, only from the
// Mac), in the active language. A change that needs it installs packages or restarts.

import SwiftUI

final class OptionItem: ObservableObject, Identifiable {
    let name: String
    let group: String
    let kind: String  // text, bool, int, float, choice, json
    let help: String
    let live: Bool
    let choices: [String]?
    @Published var text: String  // what the field shows
    @Published var flag: Bool

    var id: String { name }

    init(_ raw: [String: Any]) {
        name = raw["name"] as? String ?? "?"
        group = raw["group"] as? String ?? ""
        kind = raw["kind"] as? String ?? "text"
        help = raw["help"] as? String ?? ""
        live = raw["live"] as? Bool ?? false
        choices = (raw["choices"] as? [Any])?.map { "\($0)" }
        let value = raw["value"]
        flag = value as? Bool ?? false
        text = OptionItem.show(value, kind: kind)
    }

    static func show(_ value: Any?, kind: String) -> String {
        guard let value, !(value is NSNull) else { return "" }
        if kind == "json", JSONSerialization.isValidJSONObject(value),
           let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
            return String(decoding: data, as: UTF8.self)
        }
        if let number = value as? NSNumber, kind == "float" { return "\(number.doubleValue)" }
        return "\(value)"
    }

    /// The value to send, of its kind (nil: leave it empty, as it comes).
    var sent: Any? {
        switch kind {
        case "bool": return flag
        case "int": return Int(text.trimmingCharacters(in: .whitespaces))
        case "float": return Double(text.replacingOccurrences(of: ",", with: "."))
        case "json":
            guard !text.isEmpty else { return NSNull() }
            return (try? JSONSerialization.jsonObject(with: Data(text.utf8), options: [.fragmentsAllowed])) ?? text
        default: return text.isEmpty ? NSNull() : text
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
        if let answer = await call("settings") {
            groups = (answer["groups"] as? [[String: Any]] ?? []).map {
                (id: $0["id"] as? String ?? "", title: $0["title"] as? String ?? "")
            }
            options = (answer["options"] as? [[String: Any]] ?? []).map(OptionItem.init)
        }
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
        guard let answer = await call("settings", [option.name: option.sent ?? NSNull()]) else { return }
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
        NavigationSplitView {
            List(selection: $section) {
                Label(T("Plugins"), systemImage: "puzzlepiece.extension").tag("plugins")
                Section(T("Settings")) {
                    ForEach(admin.groups, id: \.id) { group in
                        Text(group.title).tag(group.id)
                    }
                }
            }
            .navigationSplitViewColumnWidth(200)
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

    /// Its help, as a title («La hora mientras duerme»); its name goes below.
    var label: String { option.help.prefix(1).uppercased() + option.help.dropFirst() }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            switch option.kind {
            case "bool":
                Toggle(label, isOn: $option.flag)
                    .onChange(of: option.flag) { _, _ in Task { await admin.save(option) } }
            case "choice" where option.choices != nil:
                Picker(label, selection: $option.text) {
                    ForEach(option.choices!, id: \.self) { Text($0).tag($0) }
                }
                .onChange(of: option.text) { _, _ in Task { await admin.save(option) } }
            default:
                TextField(label, text: $option.text, axis: option.kind == "json" ? .vertical : .horizontal)
                    .onSubmit { Task { await admin.save(option) } }
            }
            Text(option.name + (option.live ? "" : " · " + T("needs a restart")))
                .font(.caption.monospaced()).foregroundStyle(.secondary)
        }
    }
}

struct PluginsView: View {
    @ObservedObject var admin: Admin
    @State private var asking: PluginItem?

    let kinds = ["feature", "skill", "brain", "llm", "stt", "tts", "wake", "vad"]

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
        default: kind
        }
    }
}

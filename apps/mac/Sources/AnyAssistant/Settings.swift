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
    let plugin: String?  // the plugin that brings it (nil: the core's)
    let kind: String  // text, longtext, bool, int, float, choice, json, dict
    let title: String  // short, as a setting's name («Hora en reposo»); empty: its help is the title
    let help: String
    let live: Bool
    let choices: [String]?
    let labels: [String: String]  // how each choice is shown, in the active language
    let placeholder: String  // what an empty one uses: «Mónica · la del idioma»
    @Published var isSet: Bool  // a secret: whether the keychain has it (its value never comes)
    @Published var text: String  // what the field shows
    @Published var flag: Bool
    @Published var pairs: [Pair]  // dict (and voice set per language)

    var id: String { name }
    /// Where it lives: its plugin's page, or a General section.
    var place: String { plugin.map { "plugin:" + $0 } ?? group }
    /// Edited as name → value pairs: a dict kind, or a json one that holds a dict (one voice per language).
    var isDict: Bool { kind == "dict" || (kind == "json" && !pairs.isEmpty) }

    init(_ raw: [String: Any]) {
        name = raw["name"] as? String ?? "?"
        group = raw["group"] as? String ?? ""
        plugin = raw["plugin"] as? String
        kind = raw["kind"] as? String ?? "text"
        title = raw["title"] as? String ?? ""
        help = raw["help"] as? String ?? ""
        live = raw["live"] as? Bool ?? false
        choices = (raw["choices"] as? [Any])?.map { "\($0)" }
        labels = raw["labels"] as? [String: String] ?? [:]
        isSet = raw["set"] as? Bool ?? false
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

/// A package of the community catalog (the plugin «community»): a theme or a plugin other people share.
struct CommunityItem: Identifiable {
    let kind: String  // theme or plugin
    let packageId: String
    let name: String
    let author: String
    let version: String
    let description: String
    let installed: String?  // the version installed from the catalog, if any
    let update: Bool  // the catalog has a newer one
    let can: Bool  // it can be installed here; else «why» says what stops it
    let why: String

    var id: String { kind + ":" + packageId }
}

@MainActor
final class Admin: ObservableObject {
    @Published var groups: [(id: String, title: String)] = []
    @Published var options: [OptionItem] = []
    @Published var plugins: [PluginItem] = []
    @Published var community: [CommunityItem] = []
    @Published var communityOn = true  // the plugin «community» answers
    @Published var communityError: String?  // the catalog couldn't be read
    @Published var note: String?
    @Published var error: String?  // a change that couldn't be saved: at the bottom, by «Saved.»
    @Published var unreachable = false  // the server doesn't answer: the window says so in the middle
    @Published var restartNeeded = false

    let server = Server.shared

    /// A place's name, for the search: a General section's, or a plugin's.
    func title(of place: String) -> String {
        if place.hasPrefix("plugin:") {
            let id = String(place.dropFirst(7))
            return plugins.first { $0.id == id }?.name ?? id
        }
        return groups.first { $0.id == place }?.title ?? place
    }

    /// A route of the admin's; nil if it failed (and «error» says so, unless quiet: a plugin that is off).
    private func call(_ path: String, _ body: [String: Any]? = nil, quiet: Bool = false) async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/\(path)")!)
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request),
              let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            if !quiet { unreachable = true }
            return nil
        }
        unreachable = false
        if (response as? HTTPURLResponse)?.statusCode != 200 {
            if !quiet { error = answer["error"] as? String ?? T("It couldn't be saved.") }
            return nil
        }
        error = nil
        return answer
    }

    func load() async {
        await loadSettings()
        await loadPlugins()
        await loadCommunity()
    }

    /// The community catalog: each package, what is installed and whether an update exists.
    func loadCommunity(refresh: Bool = false) async {
        guard let answer = await call("community" + (refresh ? "?refresh=1" : ""), quiet: true) else {
            communityOn = false
            return
        }
        communityOn = true
        communityError = answer["error"] as? String
        community = (answer["packages"] as? [[String: Any]] ?? []).map {
            CommunityItem(kind: $0["kind"] as? String ?? "", packageId: $0["id"] as? String ?? "",
                          name: $0["name"] as? String ?? "", author: $0["author"] as? String ?? "",
                          version: $0["version"] as? String ?? "", description: $0["description"] as? String ?? "",
                          installed: $0["installed"] as? String, update: $0["update"] as? Bool ?? false,
                          can: $0["can"] as? Bool ?? false, why: $0["why"] as? String ?? "")
        }
    }

    /// Installs or updates a package (a plugin: after the user confirmed, and it starts off).
    func install(_ item: CommunityItem) async {
        note = T("Installing…")
        guard let answer = await call("community", ["install": ["kind": item.kind, "id": item.packageId],
                                                    "confirm": item.kind == "plugin"]) else {
            note = nil
            return
        }
        if answer["restart"] as? Bool == true { restartNeeded = true }
        note = answer["updated"] as? Bool == true ? T("Updated. It applies after restarting.")
             : item.kind == "plugin" ? T("Installed. It is off: turn it on in Plugins after restarting.") : T("Installed.")
        await loadCommunity()
        await loadPlugins()
    }

    func remove(_ item: CommunityItem) async {
        guard let answer = await call("community", ["remove": ["kind": item.kind, "id": item.packageId]]) else { return }
        if answer["restart"] as? Bool == true { restartNeeded = true }
        note = item.kind == "plugin" ? T("Removed. It applies after restarting.") : T("Removed.")
        await loadCommunity()
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

/// Settings: «General», the core's by topic; «Plugins», each one's page (on or off, what it does and
/// its options, its accounts or voices). Every option lives in one place; the search finds it.
/// Where the settings window is inside a section: a plugin's page, its mail accounts, its voices.
/// Kept here (not a NavigationStack: in a window it draws the title bar broken), with a back
/// button over the page.
enum SettingsPage: Hashable {
    case plugin(String), mail, voices
}

@MainActor
final class SettingsNavigation: ObservableObject {
    @Published var pages: [SettingsPage] = []

    func open(_ page: SettingsPage) { pages.append(page) }
    func back() { _ = pages.popLast() }
}

/// A row that opens a page (as a NavigationLink would): its content and a chevron.
struct PageLink<Content: View>: View {
    let page: SettingsPage
    @ViewBuilder let content: Content
    @EnvironmentObject private var navigation: SettingsNavigation

    var body: some View {
        Button { navigation.open(page) } label: {
            HStack {
                content
                Spacer()
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct SettingsView: View {
    @StateObject private var admin = Admin()
    @StateObject private var navigation = SettingsNavigation()
    @State private var section: String? = "assistant"
    @State private var search = ""

    var body: some View {
        // A sidebar of a fixed width (a split view can always be dragged), with the search on top.
        HStack(spacing: 0) {
            VStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField(T("Search"), text: $search).textFieldStyle(.plain)
                    if !search.isEmpty {
                        Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 8).padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 7).fill(Color.primary.opacity(0.06)))
                .padding(.horizontal, 10).padding(.top, 10)
                List(selection: $section) {
                    Section(T("General")) {
                        ForEach(admin.groups, id: \.id) { group in
                            Label(group.title, systemImage: symbol(group.id)).tag(group.id)
                        }
                    }
                    Section {
                        Label(T("Plugins"), systemImage: "puzzlepiece.extension").tag("plugins")
                    }
                }
                .listStyle(.sidebar)
            }
            .frame(width: 240)
            .background(.regularMaterial)
            Divider()
            VStack(spacing: 0) {
                if admin.restartNeeded {
                    HStack {
                        Text(T("Some changes apply after restarting."))
                        Spacer()
                        Button(T("Restart")) { admin.restart() }
                    }
                    .padding(10).background(.yellow.opacity(0.2))
                }
                if let page = navigation.pages.last {  // opened from the search too: Back returns to the results
                    HStack(spacing: 8) {
                        Button { navigation.back() } label: { Image(systemName: "chevron.left") }
                            .buttonStyle(.borderless).help(T("Back"))
                        Text(title(page)).font(.headline)
                        Spacer()
                    }
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    Divider()
                    pageView(page)
                } else if admin.unreachable {
                    ServerUnavailable { Task { await admin.load() } }
                } else if !search.trimmingCharacters(in: .whitespaces).isEmpty {
                    SearchResults(admin: admin, search: search)
                } else if section == "plugins" {
                    PluginsView(admin: admin)
                } else if let section {
                    OptionsView(admin: admin, group: section)
                }
                if let error = admin.error {  // what couldn't be saved, where «Saved.» goes
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption).foregroundStyle(.red).padding(6)
                } else if let note = admin.note {
                    Text(note).font(.caption).foregroundStyle(.secondary).padding(6)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .environmentObject(navigation)
        .onChange(of: section) { _, _ in navigation.pages = []; search = "" }
        .onChange(of: search) { _, now in if !now.isEmpty { navigation.pages = [] } }
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

    @ViewBuilder func pageView(_ page: SettingsPage) -> some View {
        switch page {
        case .plugin(let id):
            if let plugin = admin.plugins.first(where: { $0.id == id }) { PluginPage(admin: admin, plugin: plugin) }
        case .mail: MailView()
        case .voices: VoicesView()
        }
    }

    func title(_ page: SettingsPage) -> String {
        switch page {
        case .plugin(let id): admin.plugins.first { $0.id == id }?.name ?? id
        case .mail: T("Mail accounts")
        case .voices: T("Known voices")
        }
    }

    func symbol(_ group: String) -> String {
        switch group {
        case "assistant": "person.wave.2"
        case "voice": "waveform"
        case "security": "hand.raised"
        case "server": "server.rack"
        default: "gearshape"
        }
    }
}

/// A search: the options whose text or name has it (wherever they live) and the plugins.
struct SearchResults: View {
    @ObservedObject var admin: Admin
    let search: String

    var body: some View {
        let words = search.lowercased()
        let options = admin.options.filter {
            $0.group != "plugins" && [$0.title, $0.help, $0.name].contains { $0.lowercased().contains(words) }
        }
        let plugins = admin.plugins.filter {
            $0.name.lowercased().contains(words) || $0.description.lowercased().contains(words)
        }
        Form {
            if options.isEmpty && plugins.isEmpty {
                Text(T("No results")).foregroundStyle(.secondary)
            }
            if !plugins.isEmpty {
                Section(T("Plugins")) {
                    ForEach(plugins) { plugin in
                        PageLink(page: .plugin(plugin.id)) { Text(plugin.name) }
                    }
                }
            }
            ForEach(Array(Set(options.map(\.place))).sorted(), id: \.self) { place in
                Section(admin.title(of: place)) {
                    ForEach(options.filter { $0.place == place }) { option in
                        OptionRow(option: option, admin: admin)
                    }
                }
            }
        }
        .formStyle(.grouped)
    }
}

struct OptionsView: View {
    @ObservedObject var admin: Admin
    let group: String

    var body: some View {
        Form {
            ForEach(admin.options.filter { $0.group == group && $0.plugin == nil }) { option in
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

    /// Its title («Hora en reposo»); without one, its help as the title.
    var label: String {
        let shown = option.title.isEmpty ? option.help : option.title
        return shown.prefix(1).uppercased() + shown.dropFirst()
    }
    /// What goes under it, in grey: its help (if the title isn't it) and whether it restarts.
    var note: String {
        [option.title.isEmpty ? "" : option.help, option.live ? "" : T("Applies after restarting.")]
            .filter { !$0.isEmpty }.joined(separator: " ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            switch option.kind {
            case "bool":
                Toggle(label, isOn: $option.flag)
                    .onChange(of: option.flag) { _, _ in Task { await admin.save(option) } }
            case "choice" where option.choices != nil:
                Picker(label, selection: $option.text) {
                    if option.text.isEmpty { Text(option.placeholder).tag("") }
                    ForEach(option.choices!, id: \.self) { Text(option.labels[$0] ?? $0).tag($0) }
                }
                .onChange(of: option.text) { _, _ in Task { await admin.save(option) } }
            case "secret":
                // Saved in the keychain when you leave the field (or press Return); what it has is never shown.
                SecureField(label, text: $option.text,
                            prompt: Text(option.isSet ? T("Saved in the keychain") : T("Not set")))
                    .focused($editing)
                    .onSubmit { saveSecret() }
                    .onChange(of: editing) { _, now in if !now { saveSecret() } }
                if option.isSet {
                    Button(T("Remove"), role: .destructive) {
                        option.text = ""
                        Task { await admin.save(option); option.isSet = false }
                    }
                    .buttonStyle(.link)
                }
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
            if !note.isEmpty {
                Text(note).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
        .help(option.name)  // its name in settings.json, on hover
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

    /// A secret: to the keychain, then the field empties (only «saved» shows).
    func saveSecret() {
        guard !option.text.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        Task {
            await admin.save(option)
            option.text = ""
            option.isSet = true
        }
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

/// Name → value pairs (detail levels, the theme's options, a voice per language): rows to edit.
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
    @State private var asking: CommunityItem?  // a community plugin to install or update: it asks first

    let kinds = ["feature", "skill", "library", "brain", "llm", "stt", "tts", "wake", "vad"]

    var body: some View {
        let shared = admin.community.filter { $0.kind == "plugin" }
        Form {
            ForEach(kinds, id: \.self) { kind in
                // The ones that are on first, then the rest; each opens its page.
                let found = admin.plugins.filter { $0.kind == kind }.sorted { $0.on && !$1.on }
                if !found.isEmpty {
                    Section(title(kind)) {
                        ForEach(found) { plugin in
                            PageLink(page: .plugin(plugin.id)) { row(plugin) }
                        }
                    }
                }
            }
            // From the community (the plugin «community»): the catalog's plugins, to install (after
            // a warning: it is code that runs here), update or remove. Themes are in the Themes window.
            Section {
                if !admin.communityOn {
                    Text(T("Turn on the plugin «Community».")).foregroundStyle(.secondary)
                } else if let why = admin.communityError {
                    Text(why).foregroundStyle(.orange)
                } else if shared.isEmpty {
                    Text(T("Nothing to install yet.")).foregroundStyle(.secondary)
                }
                ForEach(shared) { item in
                    CommunityRow(item: item, admin: admin) { asking = item }
                }
                if admin.communityOn {
                    Button(T("Reload the catalog")) { Task { await admin.loadCommunity(refresh: true) } }
                        .buttonStyle(.link)
                }
            } header: {
                Text(T("From the community"))
            } footer: {
                Text(T("Plugins other people share, from a public catalog. Every package is reviewed before it is listed. A plugin runs on this server with your permissions."))
            }
        }
        .formStyle(.grouped)
        .alert((asking?.installed == nil ? T("Install «%s»?") : T("Update «%s»?")).replacingOccurrences(of: "%s", with: asking?.name ?? ""),
               isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }), presenting: asking) { item in
            Button(item.installed == nil ? T("Install") : T("Update")) { Task { await admin.install(item) } }
            Button(T("Cancel"), role: .cancel) {}
        } message: { _ in
            Text(T("A plugin is code that runs on this server with your permissions. Install it only if you trust its author. It starts off: turn it on in Plugins when you want to use it."))
        }
    }

    func row(_ plugin: PluginItem) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(plugin.name)
                    if plugin.security { Image(systemName: "lock.shield").foregroundStyle(.secondary) }
                    if plugin.yours { Text(T("yours")).font(.caption).foregroundStyle(.secondary) }
                }
                Text(plugin.description).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            Text(plugin.on ? T("On") : T("Off")).foregroundStyle(.secondary)
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

/// A package of the community catalog: what it is, what is installed, and what can be done with it.
struct CommunityRow: View {
    let item: CommunityItem
    @ObservedObject var admin: Admin
    let install: () -> Void  // asks first (a plugin)
    @State private var removing = false

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(item.name)
                    if let installed = item.installed {
                        Text(item.update ? T("update available") : T("installed") + " " + installed)
                            .font(.caption).foregroundStyle(item.update ? .orange : .secondary)
                    }
                }
                Text([item.author.isEmpty ? "" : T("by") + " " + item.author, T("version") + " " + item.version]
                        .filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary)
                Text(item.description).font(.caption).foregroundStyle(.secondary)
                if !item.can { Text(item.why).font(.caption).foregroundStyle(.orange) }
            }
            Spacer()
            if item.installed != nil {
                if item.update && item.can { Button(T("Update")) { install() } }
                Button(T("Remove"), role: .destructive) { removing = true }
            } else if item.can {
                Button(T("Install")) { install() }
            }
        }
        .confirmationDialog(T("Remove «%s»?").replacingOccurrences(of: "%s", with: item.name), isPresented: $removing) {
            Button(T("Remove"), role: .destructive) { Task { await admin.remove(item) } }
        }
    }
}

/// A plugin's page: on or off, what it does, what it lacks, its options and, for the mail and the
/// voices, their accounts and the known voices.
struct PluginPage: View {
    @ObservedObject var admin: Admin
    let plugin: PluginItem
    @State private var asking = false

    var current: PluginItem { admin.plugins.first { $0.id == plugin.id } ?? plugin }

    var body: some View {
        let options = admin.options.filter { $0.plugin == plugin.id }
        Form {
            Section {
                Toggle(isOn: Binding(get: { current.on }, set: { on in
                    if !on && current.locked { asking = true } else { Task { await admin.turn(current, on: on) } }
                })) {
                    HStack(spacing: 6) {
                        Text(current.name).font(.headline)
                        if current.security { Image(systemName: "lock.shield").foregroundStyle(.secondary) }
                    }
                }
            } footer: {
                VStack(alignment: .leading, spacing: 4) {
                    Text(current.description)
                    ForEach(current.unfit + current.missing.map { T("command not found:") + " " + $0 }, id: \.self) {
                        Text($0).foregroundStyle(.orange)
                    }
                }
                .font(.footnote).foregroundStyle(.secondary)
            }
            if plugin.id == "mail" {
                Section { PageLink(page: .mail) { Text(T("Mail accounts")) } }
            }
            if plugin.id == "voices" {
                Section { PageLink(page: .voices) { Text(T("Known voices")) } }
            }
            if !options.isEmpty {
                Section(T("Options")) {
                    ForEach(options) { option in OptionRow(option: option, admin: admin) }
                }
                .disabled(!current.on)
            }
        }
        .formStyle(.grouped)
        .alert(T("Turn it off?"), isPresented: $asking) {
            Button(T("Turn it off"), role: .destructive) { Task { await admin.turn(current, on: false) } }
            Button(T("Cancel"), role: .cancel) {}
        } message: {
            Text(current.security
                 ? T("It is a security plugin: without it, that protection is gone.")
                 : T("AnyAssistant needs it to work as usual."))
        }
    }
}

// The devices (the plugin «devices», only from the Mac), as System Settings lists Bluetooth's: a
// row each (its icon, name, room and state; the connected ones first) and «Conectar otro
// dispositivo…»; a click opens its page: its state, name and room, its language model, and
// «Olvidar este dispositivo».

import SwiftUI

struct DeviceItem: Identifiable, Equatable {
    let id: String
    var name: String
    var room: String
    let connected: Bool
    let current: Bool
    let seen: Date?
    let press: Bool  // talks a sentence at a time (the watch): never «connected»
    var llm: String = ""  // its own LLM; "": the general one
    var kind: String = ""  // «iPhone», «Mac»…: its icon
}

@MainActor
final class Devices: ObservableObject {
    @Published var items: [DeviceItem] = []
    @Published var error: String?
    @Published var off = false  // the plugin «devices» is off (or the server is older)
    @Published var llms: [String] = []  // the LLMs a device may use
    @Published var general = "claude"  // the general one

    let server = Server.shared

    private func call(_ body: [String: Any]? = nil) async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/devices")!)
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request) else {
            error = T("The server isn't answering: is it running?")
            return nil
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        off = status == 404 && body == nil
        guard status == 200, let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            if status == 400 { error = T("Another device already has that name.") }
            else if !off { error = T("It couldn't be saved.") }
            return nil
        }
        error = nil
        return answer
    }

    func load() async {
        guard let answer = await call() else { return }
        show(answer)
    }

    private func show(_ answer: [String: Any]) {
        items = (answer["devices"] as? [[String: Any]] ?? []).map {
            DeviceItem(id: $0["id"] as? String ?? "", name: $0["name"] as? String ?? "",
                       room: $0["room"] as? String ?? "", connected: $0["connected"] as? Bool ?? false,
                       current: $0["current"] as? Bool ?? false,
                       seen: ($0["seen"] as? Double).map { Date(timeIntervalSince1970: $0) },
                       press: $0["press"] as? Bool ?? false, llm: $0["llm"] as? String ?? "",
                       kind: $0["kind"] as? String ?? "")
        }
        .sorted { ($0.connected ? 0 : 1, $0.name) < ($1.connected ? 0 : 1, $1.name) }
        llms = answer["llms"] as? [String] ?? llms
        general = answer["general"] as? String ?? general
    }

    /// Its own LLM ("": back to the general one), from its next question.
    func setLLM(_ item: DeviceItem, _ llm: String) async {
        if let answer = await call(["id": item.id, "llm": llm]) { show(answer) }
    }

    func save(_ item: DeviceItem) async {
        if let answer = await call(["id": item.id, "name": item.name, "room": item.room]) { show(answer) }
        else { await load() }  // back to what it was (a name already taken…)
    }

    func forget(_ item: DeviceItem) async {
        if let answer = await call(["id": item.id, "forget": true]) { show(answer) }
    }
}

struct DevicesView: View {
    @StateObject private var devices = Devices()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let error = devices.error {
                    Text(error).foregroundStyle(.red).padding(8)
                }
                if devices.off {
                    Text(T("Turn on the plugin «Devices» in the settings to see them here."))
                        .foregroundStyle(.secondary).padding(24)
                    Spacer()
                } else {
                    Form {
                        Section {
                            if devices.items.isEmpty {
                                Text(T("No device has connected yet.")).foregroundStyle(.secondary)
                            }
                            ForEach(devices.items) { item in
                                NavigationLink(value: item.id) { DeviceRow(item: item) }
                            }
                        }
                        Section {
                            Button(T("Connect another device…")) { Delegate.show("pair") }
                        }
                    }
                    .formStyle(.grouped)
                }
            }
            .navigationDestination(for: String.self) { id in
                if let item = devices.items.first(where: { $0.id == id }) {
                    DeviceDetail(item: item, devices: devices)
                }
            }
        }
        .task { await devices.load() }
        // Kept up to date: they connect and change by voice too (not while you type in one).
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            if NSApp.keyWindow?.firstResponder is NSText { return }
            Task { await devices.load() }
        }
    }
}

/// A device in the list: its icon, its name, and its room and state under it.
struct DeviceRow: View {
    let item: DeviceItem

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: deviceSymbol(item.kind)).font(.title2).frame(width: 30)
                .foregroundStyle(item.connected ? Color.accentColor : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.name.isEmpty ? T("Unnamed device") : item.name)
                Text([item.room, deviceState(item)].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            if item.connected { Circle().fill(.green).frame(width: 8, height: 8) }
        }
        .padding(.vertical, 2)
    }
}

/// A device's page: its state, name and room, its language model; «Olvidar este dispositivo».
struct DeviceDetail: View {
    let item: DeviceItem
    @ObservedObject var devices: Devices
    @State private var name = ""
    @State private var room = ""
    @State private var forgetting = false
    @State private var pending: Task<Void, Never>?
    @FocusState private var editing: Bool
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section {
                LabeledContent(T("State"), value: deviceState(item))
            }
            Section {
                TextField(T("Name"), text: $name)
                TextField(T("Room"), text: $room, prompt: Text(T("Not set yet")))
            } footer: {
                Text(T("The room is how you say it by voice: «pon una alarma en la cocina». It can also be changed by voice from the device itself: «esta es la de la cocina»."))
                    .font(.caption).foregroundStyle(.secondary)
            }
            .focused($editing)
            .onSubmit { save() }
            Section {
                Picker(T("Language model"), selection: Binding(get: { item.llm }, set: { new in
                    Task { await devices.setLLM(item, new) }
                })) {
                    Text(String(format: T("The general one (%@)"), llmName(devices.general))).tag("")
                    ForEach(devices.llms, id: \.self) { Text(llmName($0)).tag($0) }  // fixed, whatever the default becomes
                }
            } footer: {
                Text(T("The one that answers on this device.")).font(.caption).foregroundStyle(.secondary)
            }
            Section {
                Button(T("Forget This Device"), role: .destructive) { forgetting = true }
            } footer: {
                Text(T("It is forgotten here; if it connects again it is a new device.")).font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle(item.name.isEmpty ? T("Unnamed device") : item.name)
        .alert(T("Forget this device?"), isPresented: $forgetting) {
            Button(T("Forget"), role: .destructive) { Task { await devices.forget(item); dismiss() } }
            Button(T("Cancel"), role: .cancel) {}
        } message: {
            Text(T("It is forgotten here; if it connects again it is a new device."))
        }
        .onAppear { name = item.name; room = item.room }
        .onDisappear { save() }
        .onChange(of: editing) { _, now in if !now { save() } }  // leaving a field saves it
        .onChange(of: name) { _, _ in later() }  // and a moment after typing
        .onChange(of: room) { _, _ in later() }
        .onChange(of: item) { _, new in if !editing { name = new.name; room = new.room } }
    }

    /// Saved once you stop typing for a moment.
    func later() {
        pending?.cancel()
        pending = Task {
            try? await Task.sleep(nanoseconds: 900_000_000)
            if !Task.isCancelled { save() }
        }
    }

    func save() {
        guard name != item.name || room != item.room, !name.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        var changed = item
        changed.name = name
        changed.room = room
        Task { await devices.save(changed) }
    }
}

/// How a device is now: connected (and talking to you), press to talk (the watch), or when it was last seen.
func deviceState(_ item: DeviceItem) -> String {
    if item.current && item.connected { return T("Connected · talking to you") }
    if item.connected { return T("Connected") }
    let state = item.press ? T("Press to talk") : T("Not connected")
    guard let seen = item.seen else { return state }
    return state + " · " + seen.formatted(.relative(presentation: .named))
}

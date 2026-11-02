// The devices (the plugin «devices», only from the Mac): which ones there are, which are
// connected and which one you're talking to; their name and room, to edit, or forget one; and
// its room's noise (the plugin «calibration»): «Calibrate» measures a few seconds of silence there.

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
    var noise: String = ""  // its room, measured: quiet, some, noisy; "": not measured
    var noiseDb: Double?
    var calibratedAt: Date?
    var calibrating: String = ""  // a calibration going on there: asking, measuring; or just ended: done, talking
}

@MainActor
final class Devices: ObservableObject {
    @Published var items: [DeviceItem] = []
    @Published var error: String?
    @Published var off = false  // the plugin «devices» is off (or the server is older)
    @Published var llms: [String] = []  // the LLMs a device may use
    @Published var general = "claude"  // the general one

    let server = Server.shared

    private func call(_ body: [String: Any]? = nil, path: String = "/devices") async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)\(path)")!)
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
                       noise: ($0["noise"] as? [String: Any])?["noise"] as? String ?? "",
                       noiseDb: ($0["noise"] as? [String: Any])?["db"] as? Double,
                       calibratedAt: (($0["noise"] as? [String: Any])?["at"] as? Double).map { Date(timeIntervalSince1970: $0) },
                       calibrating: ($0["noise"] as? [String: Any])?["step"] as? String ?? "")
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

    /// Measures its room's noise there (the plugin «calibration»): it asks for silence on the
    /// device, measures a few seconds and says what it found; the row follows it.
    func calibrate(_ item: DeviceItem) async {
        if let i = items.firstIndex(of: item) { items[i].calibrating = "asking" }
        if await call(["calibrate": item.id], path: "/admin/calibration") == nil, error == nil {
            error = T("It couldn't start the calibration: is the plugin «Calibration» on?")
        }
    }
}

struct DevicesView: View {
    @StateObject private var devices = Devices()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let error = devices.error {
                Text(error).foregroundStyle(.red).padding(8)
            }
            if devices.off {
                Text(T("Turn on the plugin «Devices» in the settings to see them here."))
                    .foregroundStyle(.secondary).padding(24)
            } else if devices.items.isEmpty {
                Text(T("No device has connected yet: pair one from the menu."))
                    .foregroundStyle(.secondary).padding(24)
            } else {
                Form {
                    Section {
                        ForEach(devices.items) { item in
                            DeviceRow(item: item, devices: devices)
                        }
                    } footer: {
                        Text(T("The room is how you say it by voice: «pon una alarma en la cocina». It can also be changed by voice from the device itself: «esta es la de la cocina»."))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .formStyle(.grouped)
            }
            Spacer(minLength: 0)
        }
        .task { await devices.load() }
        // Kept up to date: they connect and change by voice too (not while you type in one).
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            if NSApp.keyWindow?.firstResponder is NSText { return }
            Task { await devices.load() }
        }
    }
}

struct DeviceRow: View {
    let item: DeviceItem
    @ObservedObject var devices: Devices
    @State private var name = ""
    @State private var room = ""
    @FocusState private var editing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Circle().fill(item.connected ? .green : item.press ? .blue : .secondary.opacity(0.4)).frame(width: 8, height: 8)
                Text(state).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(T("Forget")) { Task { await devices.forget(item) } }
                    .buttonStyle(.borderless).foregroundStyle(.red)
                    .help(T("It is forgotten here; if it connects again it is a new device."))
            }
            HStack(alignment: .top, spacing: 16) {
                field(T("Name"), text: $name, empty: "")
                field(T("Room"), text: $room, empty: T("Not set yet"))
                VStack(alignment: .leading, spacing: 4) {
                    Text(T("Its LLM")).font(.caption).foregroundStyle(.secondary)
                    Picker(T("Its LLM"), selection: Binding(get: { item.llm }, set: { new in
                        Task { await devices.setLLM(item, new) }
                    })) {
                        Text(String(format: T("The general one (%@)"), llmName(devices.general))).tag("")
                        ForEach(devices.llms, id: \.self) { Text(llmName($0)).tag($0) }  // fixed, whatever the default becomes
                    }
                    .labelsHidden()
                }
                .frame(maxWidth: .infinity)
            }
            .onSubmit { save() }
            .onChange(of: editing) { _, now in if !now { save() } }  // leaving a field saves it
            .onChange(of: name) { _, _ in later() }  // and a moment after typing (closing the window too)
            .onChange(of: room) { _, _ in later() }
            HStack(spacing: 8) {
                Image(systemName: "waveform.badge.minus").foregroundStyle(.secondary)
                Text(noise).font(.caption).foregroundStyle(item.calibrating == "talking" ? .orange : .secondary)
                Spacer()
                if item.connected && !item.press {
                    Button(T("Calibrate")) { Task { await devices.calibrate(item) } }
                        .buttonStyle(.borderless)
                        .disabled(item.calibrating == "asking" || item.calibrating == "measuring")
                        .help(T("A few seconds of silence measured on the device: how it tells your voice from the room's noise."))
                }
            }
        }
        .onAppear { name = item.name; room = item.room }
        .onDisappear { save() }
        .onChange(of: item) { _, new in if !editing { name = new.name; room = new.room } }
    }

    /// A field with its title above it (in a form, macOS puts the title on the left and the
    /// field without a border: the title read as if it were the value).
    func field(_ title: String, text: Binding<String>, empty: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            TextField(title, text: text, prompt: Text(empty))
                .labelsHidden().textFieldStyle(.roundedBorder).focused($editing)
        }
        .frame(maxWidth: .infinity)
    }

    /// Its room's noise, or the calibration going on there.
    var noise: String {
        switch item.calibrating {
        case "asking", "measuring": return T("Measuring: keep silent near the device…")
        case "talking": return T("It heard talking: try again in silence.")
        default: break
        }
        guard !item.noise.isEmpty else { return T("Room noise: not measured") }
        let level = ["quiet": T("quiet"), "some": T("some noise"), "noisy": T("noisy")][item.noise] ?? item.noise
        var text = T("Room noise") + ": " + level
        if let db = item.noiseDb { text += " (\(Int(db.rounded())) dB)" }
        if let at = item.calibratedAt { text += " · " + T("measured") + " " + at.formatted(.relative(presentation: .named)) }
        return text
    }

    var state: String {
        if item.current && item.connected { return T("Connected · talking to you") }
        if item.connected { return T("Connected") }
        let state = item.press ? T("Press to talk") : T("Not connected")
        guard let seen = item.seen else { return state }
        return state + " · " + (item.press ? T("last used") + " " : "") + seen.formatted(.relative(presentation: .named))
    }

    @State private var pending: Task<Void, Never>?

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

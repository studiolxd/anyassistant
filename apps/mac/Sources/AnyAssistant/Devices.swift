// The devices (the plugin «devices», only from the Mac): which ones there are, which are
// connected and which one you're talking to; their name and room, to edit, or forget one.

import SwiftUI

struct DeviceItem: Identifiable, Equatable {
    let id: String
    var name: String
    var room: String
    let connected: Bool
    let current: Bool
    let seen: Date?
}

@MainActor
final class Devices: ObservableObject {
    @Published var items: [DeviceItem] = []
    @Published var error: String?
    @Published var off = false  // the plugin «devices» is off (or the server is older)

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
                       seen: ($0["seen"] as? Double).map { Date(timeIntervalSince1970: $0) })
        }
        .sorted { ($0.connected ? 0 : 1, $0.name) < ($1.connected ? 0 : 1, $1.name) }
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
    let devices: Devices
    @State private var name = ""
    @State private var room = ""
    @FocusState private var editing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Circle().fill(item.connected ? .green : .secondary.opacity(0.4)).frame(width: 8, height: 8)
                Text(state).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(T("Forget")) { Task { await devices.forget(item) } }
                    .buttonStyle(.borderless).foregroundStyle(.red)
                    .help(T("It is forgotten here; if it connects again it is a new device."))
            }
            HStack(spacing: 12) {
                TextField(T("Name"), text: $name).focused($editing)
                TextField(T("Room"), text: $room, prompt: Text(T("unknown"))).focused($editing)
            }
            .onSubmit { save() }
            .onChange(of: editing) { _, now in if !now { save() } }  // leaving a field saves it
        }
        .onAppear { name = item.name; room = item.room }
        .onChange(of: item) { _, new in if !editing { name = new.name; room = new.room } }
    }

    var state: String {
        if item.current && item.connected { return T("Connected · talking to you") }
        if item.connected { return T("Connected") }
        guard let seen = item.seen else { return T("Not connected") }
        return T("Not connected") + " · " + seen.formatted(.relative(presentation: .named))
    }

    func save() {
        guard name != item.name || room != item.room else { return }
        var changed = item
        changed.name = name
        changed.room = room
        Task { await devices.save(changed) }
    }
}

// Voices (the plugin «voices», through /admin/voices, only from the Mac): who it knows by
// their voice, forgetting one, and learning one on a connected device (the person reads a
// few phrases there, with the microphone it will hear them with).

import SwiftUI

@MainActor
final class VoicesModel: ObservableObject {
    @Published var people: [(name: String, samples: Int)] = []
    @Published var check = "off"
    @Published var off = false
    @Published var note: String?

    let server = Server.shared

    private func call(_ body: [String: Any]? = nil) async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/voices")!)
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request) else { return nil }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        off = status == 404 && body == nil
        let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any]
        if status != 200 { note = answer?["error"] as? String; return nil }
        return answer
    }

    private func show(_ answer: [String: Any]?) {
        guard let answer else { return }
        people = (answer["people"] as? [[String: Any]] ?? []).map {
            (name: $0["name"] as? String ?? "", samples: $0["samples"] as? Int ?? 0)
        }
        check = answer["check"] as? String ?? "off"
    }

    func load() async { show(await call()) }

    func learn(on device: String, name: String) async {
        show(await call(["learn": device, "name": name]))
        if !off { note = T("Go to that device: it will ask for the phrases.") }
    }

    func forget(_ name: String) async { show(await call(["forget": name])) }
}

struct VoicesView: View {
    @StateObject private var model = VoicesModel()
    @StateObject private var devices = Devices()
    @State private var device = ""
    @State private var name = ""

    var body: some View {
        Form {
            if model.off {
                Text(T("Turn on the plugin «Voices» to teach it who you are.")).foregroundStyle(.secondary)
            } else {
                Section {
                    if model.people.isEmpty {
                        Text(T("Nobody yet: while nobody is known, it listens to everyone.")).foregroundStyle(.secondary)
                    }
                    ForEach(model.people, id: \.name) { person in
                        HStack {
                            Image(systemName: "person.wave.2")
                            Text(person.name)
                            Spacer()
                            Button(T("Forget")) { Task { await model.forget(person.name) } }
                                .foregroundStyle(.red)
                        }
                    }
                } header: {
                    Text(T("Known voices"))
                } footer: {
                    Text(T("What needs a known voice is in Settings → Security («voice_check»). On a device you can also say «aprende mi voz»."))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section(T("Learn a voice")) {
                    Picker(T("On the device"), selection: $device) {
                        Text(T("Choose one")).tag("")
                        ForEach(devices.items.filter(\.connected)) { item in
                            Text(item.room.isEmpty ? item.name : "\(item.name) (\(item.room))").tag(item.id)
                        }
                    }
                    TextField(T("Name"), text: $name, prompt: Text(T("the person's: «Suvi»")))
                    HStack {
                        if let note = model.note { Text(note).font(.caption).foregroundStyle(.secondary) }
                        Spacer()
                        Button(T("Start learning")) { Task { await model.learn(on: device, name: name) } }
                            .disabled(device.isEmpty)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .task {
            await model.load()
            await devices.load()
        }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            Task { await model.load() }  // a voice learnt on a device shows up here
        }
    }
}

// Voices (the plugin «voices», through /admin/voices, only from the Mac): who it knows by
// their voice, forgetting one, and learning one on a connected device (the person reads a
// few phrases there, with the microphone it will hear them with): the guide, LearnVoiceView,
// shows each phrase to read, one at a time.

import SwiftUI

@MainActor
final class VoicesModel: ObservableObject {
    @Published var people: [(name: String, samples: Int, relearn: [String], facts: Int)] = []  // relearn: the devices where their voice should be learnt again; facts: how many the plugin «memory» remembers about them
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
            (name: $0["name"] as? String ?? "", samples: $0["samples"] as? Int ?? 0,
             relearn: $0["relearn"] as? [String] ?? [], facts: $0["facts"] as? Int ?? 0)
        }
        check = answer["check"] as? String ?? "off"
    }

    func load() async { show(await call()) }

    /// Another name for a known voice («Subi» → «Suvi»), and for what it remembers about them.
    func rename(_ name: String, to: String) async {
        note = nil
        show(await call(["rename": name, "to": to]))
    }

    /// memory: "keep" or "delete" what the plugin «memory» remembers about them (nil: it remembers nothing).
    func forget(_ name: String, memory: String? = nil) async {
        var body: [String: Any] = ["forget": name]
        if let memory { body["memory"] = memory }
        show(await call(body))
    }
}

struct VoicesView: View {
    @StateObject private var model = VoicesModel()
    @Environment(\.openWindow) private var openWindow
    @State private var asking: String?  // whose voice is being forgotten, while it asks about what it remembers of them
    @State private var renaming: String?  // whose name is being changed
    @State private var newName = ""

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
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Image(systemName: "person.wave.2")
                                Text(person.name)
                                Spacer()
                                Button(T("Rename…")) { newName = person.name; renaming = person.name }
                                Button(T("Forget")) {
                                    if person.facts > 0 { asking = person.name } else { Task { await model.forget(person.name) } }
                                }
                                .foregroundStyle(.red)
                            }
                            // Their score there has dropped lately: the microphone moved, a cold… (the server
                            // said so once, as a notice).
                            ForEach(person.relearn, id: \.self) { device in
                                Label(String(format: T("It would be good to learn their voice again on %@."), device),
                                      systemImage: "exclamationmark.triangle")
                                    .font(.caption).foregroundStyle(.orange)
                            }
                        }
                    }
                } header: {
                    Text(T("Known voices"))
                } footer: {
                    Text(T("What needs a known voice is in Settings → Security («voice_check»). On a device you can also say «aprende mi voz»."))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section(T("Learn a voice")) {
                    HStack {
                        Text(T("A guide shows each phrase to read, one at a time."))
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button(T("Learn a voice…")) {
                            LearnGuide.shared.reset()
                            NSApp.activate(ignoringOtherApps: true)
                            openWindow(id: "learn-voice")
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .alert(String(format: T("Also erase what it remembers about %@?"), asking ?? ""),
               isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }), presenting: asking) { name in
            Button(T("Keep")) { Task { await model.forget(name, memory: "keep") } }
            Button(T("Erase"), role: .destructive) { Task { await model.forget(name, memory: "delete") } }
            Button(T("Cancel"), role: .cancel) {}
        } message: { _ in
            Text(T("If you keep it and its voice is learnt again under the same name, it remembers it again."))
        }
        .alert(T("Rename"), isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } }),
               presenting: renaming) { name in
            TextField(T("Name"), text: $newName)
            Button(T("Rename")) {
                let to = newName.trimmingCharacters(in: .whitespaces)
                if !to.isEmpty, to != name { Task { await model.rename(name, to: to) } }
            }
            .keyboardShortcut(.defaultAction)
            Button(T("Cancel"), role: .cancel) {}
        } message: { _ in
            Text(T("What it remembers about them keeps the new name too."))
        }
        .task { await model.load() }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            Task { await model.load() }  // a voice learnt on a device shows up here
        }
    }
}

// MARK: - The guide: learning a voice, one phrase at a time

/// Where a learning is on its device (the server's /admin/voices «learning»), for the guide.
@MainActor
final class LearnGuide: ObservableObject {
    static let shared = LearnGuide()

    enum Step: String { case choose, name, phrase, done, cancelled }

    @Published var device = ""
    @Published var name = ""
    @Published var step = Step.choose
    @Published var phrase = ""
    @Published var number = 1
    @Published var total = 5
    @Published var again = false
    @Published var problem: String?
    private var polling: Task<Void, Never>?

    let server = Server.shared

    private func call(_ body: [String: Any]? = nil) async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/voices")!)
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request) else { return nil }
        let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any]
        if (response as? HTTPURLResponse)?.statusCode != 200 {
            problem = answer?["error"] as? String ?? T("Turn on the plugin «Voices» to teach it who you are.")
            return nil
        }
        return answer
    }

    func reset() {
        polling?.cancel()
        step = .choose
        problem = nil
        again = false
    }

    func start() async {
        problem = nil
        let given = name.trimmingCharacters(in: .whitespaces)
        guard await call(["learn": device, "name": given]) != nil else { return }
        step = given.isEmpty ? .name : .phrase
        follow()
    }

    func cancel() async {
        _ = await call(["cancel": device])
        await refresh()
    }

    /// Twice a second, while it goes on: the phrase it asks for now.
    private func follow() {
        polling?.cancel()
        polling = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                guard let self, self.step == .name || self.step == .phrase else { return }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }

    private func refresh() async {
        guard let answer = await call(),
              let mine = (answer["learning"] as? [String: Any])?[device] as? [String: Any] else { return }
        step = Step(rawValue: mine["step"] as? String ?? "") ?? step
        phrase = mine["phrase"] as? String ?? ""
        number = mine["number"] as? Int ?? number
        total = mine["total"] as? Int ?? total
        again = mine["again"] as? Bool ?? false
        if let said = mine["name"] as? String, !said.isEmpty { name = said }
    }
}

struct LearnVoiceView: View {
    @ObservedObject var guide = LearnGuide.shared
    @StateObject private var devices = Devices()
    @Environment(\.dismissWindow) private var dismissWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            switch guide.step {
            case .choose: choose
            case .name: listening(T("Tell it your name"), T("Say it to the device: «Me llamo Suvi»."))
            case .phrase: reading
            case .done: ended("checkmark.circle.fill", .green, String(format: T("Done, %@: it knows your voice."), guide.name))
            case .cancelled: ended("xmark.circle", .secondary, T("Cancelled: nothing was learnt."))
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task { await devices.load() }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            if guide.step == .choose { Task { await devices.load() } }  // renamed, connected: as it is now
        }
    }

    var choose: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(T("Learn a voice")).font(.title2.bold())
            Text(T("Stand in front of the device you talk to most: its microphone is the one that will hear you. Then read the phrases this window shows, one at a time."))
                .foregroundStyle(.secondary)
            Form {
                Picker(T("On the device"), selection: $guide.device) {
                    Text(T("Choose one")).tag("")
                    ForEach(devices.items.filter(\.connected)) { item in
                        Text(item.room.isEmpty ? item.name : "\(item.name) (\(item.room))").tag(item.id)
                    }
                }
                TextField(T("Name"), text: $guide.name, prompt: Text(T("the person's: «Suvi»")))
            }
            .formStyle(.grouped)
            if let problem = guide.problem { Text(problem).foregroundStyle(.red) }
            Spacer()
            HStack {
                Spacer()
                Button(T("Start learning")) { Task { await guide.start() } }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(guide.device.isEmpty)
            }
        }
    }

    var reading: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(String(format: T("Phrase %d of %d"), guide.number, guide.total)).font(.headline)
                Spacer()
                Button(T("Cancel"), role: .cancel) { Task { await guide.cancel() } }
            }
            ProgressView(value: Double(guide.number - 1), total: Double(guide.total))
            Text(T("Read it out loud:")).foregroundStyle(.secondary).padding(.top, 8)
            Text(guide.phrase)
                .font(.system(size: 30, weight: .semibold))
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if guide.again {
                Label(T("A little longer: say the whole phrase again."), systemImage: "arrow.counterclockwise")
                    .foregroundStyle(.orange)
            }
            Spacer()
            Label(T("When it hears you, it goes on to the next one."), systemImage: "waveform")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    func listening(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(title).font(.title2.bold())
                Spacer()
                Button(T("Cancel"), role: .cancel) { Task { await guide.cancel() } }
            }
            Text(detail).font(.title3)
            Spacer()
            Label(T("Listening on the device…"), systemImage: "waveform").foregroundStyle(.secondary)
        }
    }

    func ended(_ symbol: String, _ color: Color, _ text: String) -> some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: symbol).font(.system(size: 54)).foregroundStyle(color)
            Text(text).font(.title3).multilineTextAlignment(.center)
            Spacer()
            HStack {
                Button(T("Learn another")) { guide.reset() }
                Spacer()
                Button(T("Close")) { dismissWindow(id: "learn-voice") }.buttonStyle(.borderedProminent)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

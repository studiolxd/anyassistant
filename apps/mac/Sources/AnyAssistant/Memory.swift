// Memory (the plugin «memory», through /admin/memory, only from the Mac): what it remembers,
// shared by everyone and about each person; each fact edited in place, moved to someone else
// or deleted.

import SwiftUI

@MainActor
final class MemoryModel: ObservableObject {
    @Published var shared: [String] = []
    @Published var people: [(name: String, facts: [String])] = []  // with known voices that have none yet
    @Published var off = false
    @Published var loaded = false
    @Published var problem: String?

    let server = Server.shared

    /// Whose a fact can be moved to: the people (the shared ones are «nil»).
    var names: [String] { people.map(\.name) }

    private func call(_ body: [String: Any]? = nil) async -> [String: Any]? {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/memory")!)
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request) else { return nil }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any]
        off = status == 404 && answer?["people"] == nil  // the plugin is off: its route isn't there
        problem = status == 200 ? nil : answer?["error"] as? String
        return answer?["people"] != nil ? answer : nil  // a fact gone meanwhile: what there is now, too
    }

    private func show(_ answer: [String: Any]?) {
        guard let answer else { return }
        shared = answer["shared"] as? [String] ?? []
        people = (answer["people"] as? [[String: Any]] ?? []).map {
            (name: $0["name"] as? String ?? "", facts: $0["facts"] as? [String] ?? [])
        }
        loaded = true
    }

    func load() async { show(await call()) }

    /// A fact of whose (nil: shared): {"edit": text}, {"delete": true} or {"move": name or NSNull()}.
    func change(_ who: String?, _ fact: String, _ what: [String: Any]) async {
        var body: [String: Any] = ["who": who ?? NSNull(), "fact": fact]
        body.merge(what) { $1 }
        show(await call(body))
    }
}

struct MemoryView: View {
    @StateObject private var model = MemoryModel()

    var body: some View {
        Form {
            if model.off {
                Text(T("Turn on the plugin «Memory» so it remembers you from one conversation to the next."))
                    .foregroundStyle(.secondary)
            } else if model.loaded {
                let people = model.people.filter { !$0.facts.isEmpty }
                if model.shared.isEmpty && people.isEmpty {
                    Text(T("It doesn't remember anything yet.")).foregroundStyle(.secondary)
                }
                if !model.shared.isEmpty {
                    Section(T("Shared")) { facts(nil, model.shared) }
                }
                ForEach(people, id: \.name) { person in
                    Section(person.name) { facts(person.name, person.facts) }
                }
                Section {
                } footer: {
                    VStack(alignment: .leading, spacing: 4) {
                        if let problem = model.problem { Text(problem).foregroundStyle(.red) }
                        Text(T("What is shared goes into every conversation; what is about someone, only when it recognises their voice."))
                    }
                    .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .task { await model.load() }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            Task { await model.load() }  // it may have learnt something meanwhile
        }
    }

    func facts(_ who: String?, _ facts: [String]) -> some View {
        ForEach(Array(facts.enumerated()), id: \.offset) { _, fact in
            FactRow(model: model, who: who, fact: fact).id("\(who ?? "")|\(fact)")
        }
    }
}

/// A fact: its text, edited in place (Return or leaving the field saves it; Escape undoes it), and a
/// menu to move it to someone else or delete it.
struct FactRow: View {
    @ObservedObject var model: MemoryModel
    let who: String?
    let fact: String
    @State private var draft = ""
    @FocusState private var editing: Bool

    var body: some View {
        HStack {
            TextField("", text: $draft, axis: .vertical)
                .textFieldStyle(.plain)
                .labelsHidden()
                .focused($editing)
                .onSubmit(save)
                .onExitCommand { draft = fact; editing = false }
            Menu {
                Menu(T("Move to…")) {
                    if who != nil {
                        Button(T("Shared")) { Task { await model.change(who, fact, ["move": NSNull()]) } }
                    }
                    ForEach(model.names.filter { $0 != who }, id: \.self) { name in
                        Button(name) { Task { await model.change(who, fact, ["move": name]) } }
                    }
                }
                Divider()
                Button(T("Delete"), role: .destructive) { Task { await model.change(who, fact, ["delete": true]) } }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
        }
        .onAppear { draft = fact }
        .onChange(of: editing) { _, now in if !now { save() } }
    }

    func save() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text != fact else { return }
        guard !text.isEmpty else { draft = fact; return }
        Task { await model.change(who, fact, ["edit": text]) }
    }
}

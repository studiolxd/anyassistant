// The installer in a window: the same steps as `bin/anyassistant setup`, through its
// JSON (`--list --json` for the questions, `--json` for the progress).

import Foundation
import ServiceManagement

struct Choice: Hashable {
    let value: AnyHashable
    let label: String
}

struct Question: Identifiable {
    let id: String
    let title: String
    let help: String
    let choices: [Choice]?  // nil: free text
    var answer: AnyHashable
}

struct StepRow: Identifiable {
    let id: String
    let title: String
    var status: Status = .running
    var text = ""

    enum Status { case running, done, skipped, failed }
}

@MainActor
final class Setup: ObservableObject {
    static let shared = Setup()
    enum Phase { case welcome, another, preparing, questions, installing, finished }

    @Published var phase: Phase = .welcome
    @Published var questions: [Question] = []
    @Published var steps: [StepRow] = []
    @Published var note = ""
    @Published var failed = false
    @Published var startAtLogin = true
    @Published var total = 0  // how many steps it runs (for the progress bar)

    let server = Server.shared
    /// What the app does itself: it starts the server (not launchd), and shows how to connect.
    let skipped = ["--skip", "service", "--skip", "connect"]

    /// The program and its Python, before any question.
    func prepare() async -> Bool {
        phase = .preparing
        note = T("Copying the program and preparing Python…")
        let code = await server.run(server.bundled.appending(path: "install.sh"),
                                    ["--to", server.program.path, "--data", server.data.path,
                                     "--cache", server.cache.path, "--no-setup", "--json"]) { [weak self] line in
            _ = line  // install.sh's own words are English: the window says it in its language
        }
        if code != 0 { failed = true; note = T("It couldn't prepare the program.") }
        return code == 0
    }

    /// «Install with what comes»: every default, no questions.
    func installWithDefaults() async {
        guard await prepare() else { return }
        await install(["--defaults"])
    }

    /// «Step by step»: the questions first.
    func askQuestions() async {
        guard await prepare() else { return }
        var found: [Question] = []
        _ = await server.run(server.program.appending(path: "bin/anyassistant"),
                             ["setup", "--list", "--json"] + skipped) { line in
            guard let steps = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [[String: Any]] else { return }
            for step in steps where step["kind"] as? String == "question" {
                let choices = (step["choices"] as? [[String: Any]])?.map {
                    Choice(value: Setup.hashable($0["value"]), label: Setup.label($0["label"]))
                }
                found.append(Question(id: step["id"] as? String ?? "?", title: step["title"] as? String ?? "",
                                      help: step["help"] as? String ?? "", choices: choices,
                                      answer: Setup.hashable(step["default"])))
            }
        }
        questions = found
        phase = .questions
    }

    func installWithAnswers() async {
        var arguments: [String] = []
        for question in questions {
            let value: String
            switch question.answer {
            case let flag as Bool: value = flag ? "true" : "false"
            default: value = "\(question.answer)"
            }
            arguments += ["--set", "\(question.id)=\(value)"]
        }
        await install(arguments)
    }

    private func install(_ arguments: [String]) async {
        phase = .installing
        steps = []
        let code = await server.run(server.program.appending(path: "bin/anyassistant"),
                                    ["setup", "--json"] + skipped + arguments) { [weak self] line in
            self?.handle(line)
        }
        failed = code != 0
        if startAtLogin { try? SMAppService.mainApp.register() }
        phase = .finished
        server.launch()
        Client.shared.begin()  // the assistant on this Mac too
    }

    private func handle(_ line: String) {
        guard let event = Setup.decode(line), let kind = event["event"] as? String else { return }
        let id = event["id"] as? String ?? ""
        let text = event["text"] as? String ?? ""
        switch kind {
        case "step":
            total = event["total"] as? Int ?? total
            steps.append(StepRow(id: id, title: event["title"] as? String ?? id))
        case "progress":
            if let i = steps.firstIndex(where: { $0.id == id }) { steps[i].text = text }
        case "done", "skipped", "error":
            if let i = steps.firstIndex(where: { $0.id == id }) {
                steps[i].status = kind == "done" ? .done : kind == "skipped" ? .skipped : .failed
                steps[i].text = text
            }
        default: break
        }
    }

    // MARK: JSON helpers

    static func decode(_ line: String) -> [String: Any]? {
        try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
    }

    static func hashable(_ value: Any?) -> AnyHashable {
        switch value {
        case let number as NSNumber where CFGetTypeID(number) == CFBooleanGetTypeID(): return number.boolValue
        case let text as String: return text
        case let number as NSNumber: return number.intValue
        default: return ""
        }
    }

    static func label(_ value: Any?) -> String {
        switch value {
        case let text as String where text == "True": return T("Yes")
        case let text as String where text == "False": return "No"
        case let text as String: return text
        default: return "\(value ?? "")"
        }
    }
}

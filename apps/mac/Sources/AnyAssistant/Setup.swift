// The installer in a window: the same steps as `bin/anyassistant setup`, through its
// JSON (`--list --json` for the questions, `--json` for the progress). Its «device» steps (your
// voice: they need this Mac's microphone) right after installing, once the server runs, through
// its /setup/device/<id>.

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

    enum Status { case running, done, skipped, failed, later }
}

/// A «device» step: offered once installed, done on this Mac (its button, or «Not now»).
struct DeviceStep {
    let id: String
    let title: String
    let help: String
    let action: String
    let later: String
}

/// Where a «device» step is, as the server says it.
struct DeviceProgress {
    enum Stage { case offer, waiting, running }
    var stage = Stage.offer
    var title = ""
    var text = ""
    var detail = ""
    var fraction: Double?
}

@MainActor
final class Setup: ObservableObject {
    static let shared = Setup()
    enum Phase { case welcome, another, preparing, questions, installing, device, finished }

    @Published var phase: Phase = .welcome
    @Published var questions: [Question] = []
    @Published var steps: [StepRow] = []
    @Published var note = ""
    @Published var failed = false
    @Published var startAtLogin = true
    @Published var total = 0  // how many steps it runs (for the progress bar)
    @Published var devices: [DeviceStep] = []  // the «device» steps still to offer, the first one now
    @Published var device = DeviceProgress()
    private var following: Task<Void, Never>?

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
        devices = []
        let code = await server.run(server.program.appending(path: "bin/anyassistant"),
                                    ["setup", "--json"] + skipped + arguments) { [weak self] line in
            self?.handle(line)
        }
        failed = code != 0
        if startAtLogin { try? SMAppService.mainApp.register() }
        server.launch()
        Client.shared.begin()  // the assistant on this Mac too
        device = DeviceProgress()
        phase = devices.isEmpty ? .finished : .device
    }

    // MARK: «Device» steps: on this Mac, once the server runs

    private func call(_ id: String, _ body: [String: Any]? = nil) async -> (Int, [String: Any]) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/setup/device/\(id)")!)
        request.timeoutInterval = 5
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request) else { return (0, [:]) }
        let answer = (try? JSONSerialization.jsonObject(with: raw) as? [String: Any]) ?? [:]
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, answer)
    }

    /// Its button: once the server and this Mac's device are up, it starts there; then, how it goes.
    func startDevice() {
        guard let step = devices.first else { return }
        device = DeviceProgress(stage: .waiting)
        following?.cancel()
        following = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {  // the server starting, this Mac's device connecting
                let (status, answer) = await self.call(step.id)
                if status == 404 { return self.ended(.skipped, step.later) }  // its plugin isn't on
                if status == 200, answer["device"] as? String != nil { break }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
            var (status, answer) = await self.call(step.id, ["do": "start"])
            while !Task.isCancelled {
                if status != 200 { return self.ended(.failed, answer["error"] as? String ?? "") }
                if let state = answer["state"] as? [String: Any] {
                    let text = state["text"] as? String ?? ""
                    switch state["state"] as? String {
                    case "done": return self.ended(.done, text)
                    case "cancelled": return self.ended(.skipped, text)
                    default:
                        self.device = DeviceProgress(stage: .running, title: state["title"] as? String ?? "", text: text,
                                                     detail: state["detail"] as? String ?? "",
                                                     fraction: state["fraction"] as? Double)
                    }
                }
                try? await Task.sleep(nanoseconds: 500_000_000)
                (status, answer) = await self.call(step.id)
            }
        }
    }

    /// «Not now» (or cancelling it while it waits for the server): how to do it later.
    func skipDevice() {
        guard let step = devices.first else { return }
        if device.stage == .running {
            Task { _ = await call(step.id, ["do": "cancel"]) }  // its end comes as the server says it
            return
        }
        ended(.skipped, step.later)
    }

    private func ended(_ status: StepRow.Status, _ text: String) {
        following?.cancel()
        guard let step = devices.first else { return }
        if let i = steps.firstIndex(where: { $0.id == step.id }) {
            steps[i].status = status
            steps[i].text = text
        }
        devices.removeFirst()
        device = DeviceProgress()
        if devices.isEmpty { phase = .finished }
    }

    private func handle(_ line: String) {
        guard let event = Setup.decode(line), let kind = event["event"] as? String else { return }
        let id = event["id"] as? String ?? ""
        let text = event["text"] as? String ?? ""
        switch kind {
        case "step":
            total = event["total"] as? Int ?? total
            steps.append(StepRow(id: id, title: event["title"] as? String ?? id))
        case "device":  // done on this Mac once installed
            total = event["total"] as? Int ?? total
            steps.append(StepRow(id: id, title: event["title"] as? String ?? id, status: .later))
            devices.append(DeviceStep(id: id, title: event["title"] as? String ?? id, help: event["help"] as? String ?? "",
                                      action: event["action"] as? String ?? "", later: event["later"] as? String ?? ""))
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

// What the face shows, as the page has it: the state (asleep, hearing, thinking, speaking…),
// the texts in the Mac's language, the theme and its colours, the screen settings, what was
// said, the timers, the photo it looks at. The Mac's messages change it (receive), and its
// /config (configure): the same as the page's, so the app follows the Mac's settings.

import SwiftUI

@MainActor
final class FaceModel: ObservableObject {
    struct Caption: Identifiable, Equatable {
        let id: String
        var text: String
        let assistant: Bool
    }

    struct Item: Identifiable, Equatable {
        let kind: String  // timer, alarm, reminder
        let at: Double
        let label: String
        var id: String { "\(kind)-\(at)" }
    }

    @Published var state = "connecting"
    @Published var problem: String?  // not connected: what to say instead of the state
    @Published var name = "AnyAssistant"
    @Published var lang = Locale.current.languageCode ?? "en"
    @Published var wake = ""
    @Published var texts: [String: String] = [:]
    @Published var theme = "eyes"
    @Published var options: [String: String] = [:]
    @Published var screen: [String: Any] = [:]
    @Published var captions: [Caption] = []
    @Published var heard = ""
    @Published var answer = ""
    @Published var items: [Item] = []
    @Published var alarmLabel = ""
    @Published var photo: PlatformImage?
    @Published var scanning = false
    @Published var photoFading = false
    @Published var cameraShown = false
    @Published var pausedWhy = ""  // paused: why (microphone, call, interrupted) and by which app, if known
    @Published var pausedApp = ""

    private static let looksLike = ["connected": "awake", "listening": "awake", "recording": "hearing",
                                    "repeating": "speaking", "transcribing": "thinking", "connecting": "awake",
                                    "paused": "asleep"]
    private static let pauses = ["microphone", "call", "interrupted"]

    /// The state as the themes draw it (several states look the same).
    var look: String { problem != nil ? "error" : FaceModel.looksLike[state] ?? state }

    // MARK: Texts and settings

    func text(_ key: String, _ values: [String: String] = [:]) -> String {
        if texts.isEmpty { return "" }  // nothing until the Mac's texts arrive
        var found = texts[key] ?? key
        for (name, value) in values { found = found.replacingOccurrences(of: "{\(name)}", with: value) }
        return found
    }

    func shows(_ key: String, _ otherwise: Bool = true) -> Bool { screen[key] as? Bool ?? otherwise }

    var history: Int { screen["history"] as? Int ?? 2 }

    /// The status line, as the page writes it.
    var status: String {
        if let problem { return problem }
        switch state {
        case "alarm": return text("alarm", ["label": alarmLabel])
        case "paused":  // «En pausa: Zoom usa el micrófono»
            let why = FaceModel.pauses.contains(pausedWhy) ? pausedWhy : "microphone"
            return text(pausedApp.isEmpty ? "paused_" + why : "paused_app", ["app": pausedApp])
        case "asleep": return shows("show_hint") ? text("asleep", ["wake": wake.isEmpty ? name : wake]) : ""
        default: return shows("show_status") || state == "error" ? text(state) : ""
        }
    }

    func color(_ key: String, _ otherwise: Color) -> Color { options[key].flatMap(Color.init(hex:)) ?? otherwise }

    var background: Color { color("background", .black) }

    func configure(_ config: [String: Any]) {
        lang = config["lang"] as? String ?? lang
        name = config["name"] as? String ?? name
        wake = config["wake_phrase"] as? String ?? wake
        screen = config["screen"] as? [String: Any] ?? [:]
        var found = config["ui"] as? [String: String] ?? [:]
        let themeInfo = config["theme"] as? [String: Any] ?? [:]
        for (key, value) in themeInfo["ui"] as? [String: String] ?? [:] { found[key] = value }  // the theme's own words
        texts = found
        theme = themeInfo["name"] as? String ?? "eyes"
        options = (themeInfo["options"] as? [String: Any] ?? [:]).compactMapValues { $0 as? String }
    }

    // MARK: The Mac's messages

    func receive(_ message: [String: Any]) {
        switch message["type"] as? String {
        case "state":
            state = message["state"] as? String ?? state
            if let phrase = message["wake_phrase"] as? String, !phrase.isEmpty { wake = phrase }
            pausedWhy = message["why"] as? String ?? ""
            pausedApp = message["app"] as? String ?? ""
            if look != "looking" && look != "thinking" { photoDone() }
            if look == "asleep" { cameraShown = false }
        case "text":
            caption(message)
        case "timers":
            items = (message["items"] as? [[String: Any]] ?? []).compactMap { item in
                guard let at = (item["at"] as? NSNumber)?.doubleValue else { return nil }
                return Item(kind: item["kind"] as? String ?? "timer", at: at, label: item["label"] as? String ?? "")
            }
        case "alarm":
            alarmLabel = message["label"] as? String ?? ""
        case "camera":
            cameraShown = message["on"] as? Bool ?? false
        default:
            break
        }
    }

    /// What you said and its answer (in pieces with the same id: the same line, updated).
    private func caption(_ message: [String: Any]) {
        guard let text = message["text"] as? String else { return }
        let assistant = message["author"] as? String == "assistant"
        guard shows(assistant ? "show_answer" : "show_heard") else { return }
        if assistant { answer = text } else { heard = text }
        let id = (message["id"]).map { "\($0)" }
        if let id, let index = captions.firstIndex(where: { $0.id == "a-\(id)" }) {
            captions[index].text = text
            return
        }
        captions.append(Caption(id: id.map { "a-\($0)" } ?? UUID().uuidString, text: text, assistant: assistant))
        if captions.count > history + 1 { captions.removeFirst(captions.count - history - 1) }
    }

    /// «¿Qué ves?»: the photo it looks at, with a scanning sweep until it answers.
    func show(photo image: PlatformImage) {
        photo = image
        photoFading = false
        scanning = true
    }

    private func photoDone() {
        guard photo != nil, !photoFading else { return }
        scanning = false
        photoFading = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            if self?.photoFading == true { self?.photo = nil; self?.photoFading = false }
        }
    }

    // MARK: The clock and the timers, in the Mac's language

    var locale: Locale { Locale(identifier: lang) }

    func time(_ date: Date) -> String {
        let clock = screen["clock"] as? String ?? "auto"
        let template = clock == "12" ? "hmm" : clock == "24" ? "Hmm" : "jmm"
        let format = DateFormatter()
        format.locale = locale
        format.setLocalizedDateFormatFromTemplate(template)
        return format.string(from: date)
    }

    func day(_ date: Date) -> String {
        let format = DateFormatter()
        format.locale = locale
        format.setLocalizedDateFormatFromTemplate("EEEEdMMMM")
        return format.string(from: date)
    }

    /// «4:59 · pasta», «7:30 · gym»: a countdown for timers, the time for the rest.
    func line(_ item: Item, now: Date) -> String {
        let when: String
        if item.kind == "timer" {
            let left = max(0, Int((item.at - now.timeIntervalSince1970).rounded()))
            let (h, m, s) = (left / 3600, left / 60 % 60, left % 60)
            when = h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
        } else {
            when = time(Date(timeIntervalSince1970: item.at))
        }
        return when + (item.label.isEmpty ? "" : " · " + item.label)
    }
}

/// Your voice and its own (0…1), apart: they change many times a second.
@MainActor
final class Levels: ObservableObject {
    @Published var voice: CGFloat = 0
    @Published var speech: CGFloat = 0
}

extension Color {
    /// «#34aff7», «#000».
    init?(hex: String) {
        var digits = hex.trimmingCharacters(in: .whitespaces)
        guard digits.hasPrefix("#") else { return nil }
        digits.removeFirst()
        if digits.count == 3 { digits = digits.map { "\($0)\($0)" }.joined() }
        guard digits.count == 6, let value = Int(digits, radix: 16) else { return nil }
        self.init(red: Double(value >> 16 & 255) / 255, green: Double(value >> 8 & 255) / 255, blue: Double(value & 255) / 255)
    }
}

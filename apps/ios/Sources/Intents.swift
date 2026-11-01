// «Talk to AnyAssistant»: for Siri, the Shortcuts app and the iPhone's Action button (Settings →
// Action Button → Shortcut). It opens the app listening, as if you had said its name. iOS 16 or
// later (on iOS 15 there is no such thing).

import AppIntents

@available(iOS 16.0, *)
struct TalkIntent: AppIntent {
    static var title: LocalizedStringResource = "Talk to AnyAssistant"
    static var description = IntentDescription("Opens AnyAssistant listening, as if you had said its name.")
    static var openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        NotificationCenter.default.post(name: .talk, object: nil)
        return .result()
    }
}

@available(iOS 16.0, *)
struct Shortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: TalkIntent(), phrases: ["Talk to \(.applicationName)", "Hey \(.applicationName)"])
    }
}

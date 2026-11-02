// «Talk to AnyAssistant»: for Siri («Habla con AnyAssistant»), the Shortcuts app and the Apple
// Watch Ultra's Action button (Settings → Action Button → Shortcut). It opens the app, which
// listens as soon as it is in front.

import AppIntents

struct TalkIntent: AppIntent {
    static var title: LocalizedStringResource = "Talk to AnyAssistant"
    static var description = IntentDescription("Opens AnyAssistant listening, as if you had said its name.")
    static var openAppWhenRun = true

    func perform() async throws -> some IntentResult {
        .result()
    }
}

struct Shortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: TalkIntent(), phrases: ["Talk to \(.applicationName)", "Hey \(.applicationName)"])
    }
}

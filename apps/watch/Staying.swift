// Keeps the app running while it thinks and speaks, though the wrist goes down or the screen
// sleeps: without it watchOS stops the app, and the answer with it. An extended runtime session
// («self-care»: WKBackgroundModes in project.yml), begun when a sentence is sent (the app is in
// front then, as it must be) and ended when the answer has been said.

import WatchKit

@MainActor
final class Staying: NSObject, WKExtendedRuntimeSessionDelegate {
    private var session: WKExtendedRuntimeSession?

    func begin() {
        if let session, session.state == .running || session.state == .scheduled { return }
        let found = WKExtendedRuntimeSession()  // each one starts once
        found.delegate = self
        found.start()
        session = found
    }

    func end() {
        session?.invalidate()
        session = nil
    }

    nonisolated func extendedRuntimeSessionDidStart(_ extendedRuntimeSession: WKExtendedRuntimeSession) {}

    nonisolated func extendedRuntimeSessionWillExpire(_ extendedRuntimeSession: WKExtendedRuntimeSession) {}

    nonisolated func extendedRuntimeSession(_ extendedRuntimeSession: WKExtendedRuntimeSession,
                                            didInvalidateWith reason: WKExtendedRuntimeSessionInvalidationReason,
                                            error: Error?) {
        Task { @MainActor in
            if self.session === extendedRuntimeSession { self.session = nil }
        }
    }
}

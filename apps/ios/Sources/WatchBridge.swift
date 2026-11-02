// The Apple Watch gets its pairing from here: the server's IP (the watch resolves no «.local»
// names and has no Bonjour), its port, its HTTPS authority and the pairing's cookie (Mac.handoff),
// as WatchConnectivity's application context: the watch has the latest even if its app wasn't
// open. Sent again when it changes (paired or not, the server's IP: Mac.handoffChanged), and
// given when the watch asks (iOS wakes this app for it). The watch then talks to the server
// itself, as its own device; nothing it says goes through here. The timers, alarms and reminders
// the server sends here go to the watch too, for its complication (at once when it is on the face).

#if os(iOS)
import WatchConnectivity

final class WatchBridge: NSObject, WCSessionDelegate {
    static let shared = WatchBridge()

    func start() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
        NotificationCenter.default.addObserver(forName: Mac.handoffChanged, object: nil, queue: .main) { [weak self] _ in
            self?.send()
        }
        NotificationCenter.default.addObserver(forName: FaceModel.timersArrived, object: nil, queue: .main) { [weak self] note in
            self?.timers(note.object as? [[String: Any]] ?? [])
        }
    }

    private func timers(_ items: [[String: Any]]) {
        let session = WCSession.default
        guard session.activationState == .activated, session.isPaired, session.isWatchAppInstalled else { return }
        let next = items.map { item in item.filter { ["kind", "at", "label", "set"].contains($0.key) } }
        if session.isComplicationEnabled {
            session.transferCurrentComplicationUserInfo(["timers": next])  // wakes the watch's app: shown at once
        } else {
            session.transferUserInfo(["timers": next])
        }
    }

    private func send() {
        let session = WCSession.default
        guard session.activationState == .activated, session.isPaired, session.isWatchAppInstalled else { return }
        try? session.updateApplicationContext(Mac.handoff())
    }

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        DispatchQueue.main.async { self.send() }
    }

    /// The watch app installed, or another watch: it gets it again.
    func sessionWatchStateDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.send() }
    }

    /// The watch asks (its app opened, not paired yet).
    func session(_ session: WCSession, didReceiveMessage message: [String: Any], replyHandler: @escaping ([String: Any]) -> Void) {
        replyHandler(Mac.handoff())
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    /// Another watch chosen: this session ends, a new one begins.
    func sessionDidDeactivate(_ session: WCSession) {
        WCSession.default.activate()
    }
}
#endif

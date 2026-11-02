// The pairing comes from the iPhone (its app's WatchBridge): the server's IP, port, HTTPS
// authority and the pairing's cookie, as WatchConnectivity's application context (the latest,
// even if this app wasn't open), and asked for when the app opens unpaired. Not paired there: not
// paired here either. The watch then talks to the server itself.

import WatchConnectivity

final class Companion: NSObject, WCSessionDelegate {
    static let shared = Companion()
    private weak var mac: Mac?

    @MainActor func start(_ mac: Mac) {
        self.mac = mac
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    /// Asks the iPhone for it (iOS wakes its app): when the app opens unpaired.
    @MainActor func ask() {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else { return }
        session.sendMessage(["handoff": true], replyHandler: { [weak self] handoff in
            self?.adopt(handoff)
        }, errorHandler: nil)
    }

    private func adopt(_ handoff: [String: Any]) {
        DispatchQueue.main.async {
            MainActor.assumeIsolated { self.mac?.adopt(handoff) }
        }
    }

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        let latest = session.receivedApplicationContext
        if !latest.isEmpty { adopt(latest) }
        DispatchQueue.main.async {
            MainActor.assumeIsolated { if self.mac?.paired == false { self.ask() } }
        }
    }

    func session(_ session: WCSession, didReceiveApplicationContext context: [String: Any]) {
        adopt(context)
    }

    /// The iPhone came near (or its app woke): asked again if still unpaired.
    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            MainActor.assumeIsolated { if self.mac?.paired == false { self.ask() } }
        }
    }
}

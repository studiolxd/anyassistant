// The connection with the Mac (the plugin «stream-api»): a WebSocket with the microphone going
// up and its voice coming down, and the page's messages both ways. It reconnects by itself
// (the Wi-Fi drops, the Mac restarts), and keeps what the page shows to show it again when the
// app comes back from the background.

import Foundation
import WebKit

@MainActor
final class Link: NSObject, ObservableObject {
    enum State: String { case connecting, connected, lost, unpaired }

    let mac: Mac
    let audio = Audio()
    weak var web: WKWebView?
    @Published private(set) var state = State.connecting

    private var socket: URLSessionWebSocketTask?
    private var wanted = false
    private var dialing = false  // looking for the Mac (once at a time)
    private var pageReady = false
    private var tapWhenConnected = false
    private var shown: [String: [String: Any]] = [:]  // the last state, timers, alarm: for the page again
    private var lastLevel = Date.distantPast

    init(mac: Mac) {
        self.mac = mac
        super.init()
        audio.onRestartNeeded = { [weak self] in Task { @MainActor in self?.restartAudio() } }
    }

    // MARK: Connecting

    func start() {
        wanted = true
        connect()
    }

    func stop() {
        wanted = false
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        audio.stop()
        set(.lost)
    }

    func restart() {
        stop()
        pageReady = false
        start()
        loadPage()
    }

    private func connect() {
        guard wanted, socket == nil, !dialing else { return }
        dialing = true
        set(.connecting)
        Task {
            let found = await mac.url()
            dialing = false
            guard wanted, socket == nil else { return }
            guard let base = found else { return lost() }
            var parts = URLComponents(url: base.appendingPathComponent("stream"), resolvingAgainstBaseURL: false)!
            parts.scheme = parts.scheme == "https" ? "wss" : "ws"
            parts.queryItems = [URLQueryItem(name: "device", value: mac.device)]
            var request = URLRequest(url: parts.url!)
            for (name, value) in HTTPCookie.requestHeaderFields(with: mac.cookies(for: base)) {
                request.setValue(value, forHTTPHeaderField: name)
            }
            request.setValue(mac.agent, forHTTPHeaderField: "User-Agent")
            let task = mac.session.webSocketTask(with: request)
            task.maximumMessageSize = 1 << 20
            socket = task
            task.resume()
            receive(task)
        }
    }

    private func receive(_ task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.socket === task else { return }
                switch result {
                case .success(let message):
                    if self.state != .connected { self.connected() }
                    switch message {
                    case .data(let pcm): self.audio.play(pcm)
                    case .string(let text): self.handle(text)
                    @unknown default: break
                    }
                    self.receive(task)
                case .failure:
                    self.dropped(task)
                }
            }
        }
    }

    private func connected() {
        set(.connected)
        do {
            try audio.start { [weak self] pcm, level in
                Task { @MainActor in self?.heard(pcm, level) }
            }
        } catch {
            NSLog("AnyAssistant: no microphone: \(error)")
        }
        if tapWhenConnected {
            tapWhenConnected = false
            send(["type": "tap"])
        }
    }

    private func dropped(_ task: URLSessionWebSocketTask) {
        socket = nil
        audio.stop()
        if (task.response as? HTTPURLResponse)?.statusCode == 403 {  // unpaired on the Mac
            set(.unpaired)
            wanted = false
            mac.unpair()
            return
        }
        lost()
    }

    private func lost() {
        socket = nil
        set(.lost)
        guard wanted else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in self?.connect() }
    }

    private func set(_ new: State) {
        guard state != new else { return }
        state = new
        toPage(["type": "link", "state": new.rawValue])
    }

    private func restartAudio() {
        guard state == .connected else { return }
        audio.stop()
        connected()
    }

    // MARK: Both ways

    private func heard(_ pcm: Data, _ level: Float) {
        socket?.send(.data(pcm)) { _ in }
        if Date().timeIntervalSince(lastLevel) > 0.05 {  // the face follows your voice
            lastLevel = Date()
            toPage(["type": "level", "value": level])
        }
    }

    func send(_ message: [String: Any]) {
        guard let socket, let data = try? JSONSerialization.data(withJSONObject: message),
              let text = String(data: data, encoding: .utf8) else { return }
        socket.send(.string(text)) { _ in }
    }

    /// An alarm stopped on the phone: if the Mac is ringing, a tap stops it there too.
    func stopRinging() {
        if (shown["state"]?["state"] as? String) == "alarm" { send(["type": "tap"]) }
    }

    /// «Talk to AnyAssistant»: as a tap on its face (it wakes up, or stops talking).
    func talk() {
        if state == .connected { send(["type": "tap"]) } else { tapWhenConnected = true; start() }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = message["type"] as? String else { return }
        if type == "hush" { return audio.hush() }
        if ["state", "timers", "alarm"].contains(type) { shown[type] = message }
        Notices.shared.handle(message)
        toPage(message)
    }

    // MARK: The page

    /// The Mac's page, as the face (paired: its cookie; HTTPS: only its authority is trusted).
    func loadPage() {
        guard let web else { return }
        Task {
            guard let base = await mac.url() else {
                web.loadHTMLString(Link.waiting, baseURL: nil)
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.loadPage() }
                return
            }
            let store = web.configuration.websiteDataStore.httpCookieStore
            for cookie in mac.cookies(for: base) { await store.setCookie(cookie) }
            web.load(URLRequest(url: base))
        }
    }

    func pageFailed() {
        pageReady = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.loadPage() }
    }

    func fromPage(_ message: [String: Any]) {
        if message["type"] as? String == "ready" {
            pageReady = true
            showAgain()
        } else {
            send(message)  // tap, skin, ping
        }
    }

    /// What the page missed (it was in the background, or loading).
    func showAgain() {
        guard pageReady else { return }
        toPage(["type": "link", "state": state.rawValue])
        for type in ["alarm", "timers", "state"] { if let message = shown[type] { toPage(message) } }
    }

    private func toPage(_ message: [String: Any]) {
        guard pageReady, let web, let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.fromApp && window.fromApp(\(json))", completionHandler: nil)
    }

    private static var waiting: String {
        "<meta name=viewport content='width=device-width'><body style='background:#000;color:#999;"
            + "font:17px -apple-system;display:flex;align-items:center;justify-content:center;height:90vh;"
            + "text-align:center;padding:24px'>" + T("Looking for your Mac…") + "</body>"
    }
}

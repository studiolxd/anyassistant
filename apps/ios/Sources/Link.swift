// The connection with the Mac (the plugin «stream-api»): a WebSocket with the microphone going
// up and its voice coming down, and the messages both ways, which change the face (FaceModel).
// It reconnects by itself (the network drops, the Mac restarts); while disconnected in the
// background, the microphone stays on so iOS keeps the app alive to reconnect.

import Foundation

@MainActor
final class Link: NSObject, ObservableObject {
    enum State: String { case connecting, connected, lost, unpaired }

    let mac: Mac
    let audio = Audio()
    let camera = Camera()
    let face = FaceModel()
    let levels = Levels()
    @Published private(set) var state = State.connecting

    private var socket: URLSessionWebSocketTask?
    private var wanted = false
    private var dialing = false  // looking for the Mac (once at a time)
    private var tapWhenConnected = false
    private var eyes = false  // the Mac has «eyes» on: the camera may be used
    private var inFront = true  // the app is on screen (the camera only works then)
    private var lastLevel = Date.distantPast

    init(mac: Mac) {
        self.mac = mac
        super.init()
        audio.onRestartNeeded = { [weak self] in Task { @MainActor in self?.restartAudio() } }
        audio.onSpeech = { [weak self] level in Task { @MainActor in self?.levels.speech = CGFloat(level) } }
        camera.onFrame = { [weak self] jpeg in
            Task { @MainActor in self?.send(["type": "frame", "jpeg": jpeg.base64EncodedString()]) }
        }
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
        camera.stop()
        set(.lost)
    }

    func restart() {
        stop()
        start()
    }

    private func connect() {
        guard wanted, socket == nil, !dialing else { return }
        dialing = true
        if state != .lost { set(.connecting) }
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
            report("no microphone: \(error.localizedDescription)")
        }
        Task { await configure() }
        if tapWhenConnected {
            tapWhenConnected = false
            send(["type": "tap"])
        }
    }

    private func dropped(_ task: URLSessionWebSocketTask) {
        socket = nil
        camera.stop()
        if (task.response as? HTTPURLResponse)?.statusCode == 403 {  // unpaired on the Mac
            set(.unpaired)
            wanted = false
            audio.stop()
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
        state = new
        switch new {
        case .connected: face.problem = nil
        case .connecting: face.problem = nil; face.state = "connecting"
        case .lost:
            let said = face.text("connection_lost")
            face.problem = said.isEmpty || said == "connection_lost" ? T("Looking for the server…") : said
        case .unpaired: face.problem = T("It has to be paired again.")
        }
    }

    private func restartAudio() {
        guard state == .connected else { return }
        report("audio restarted (interrupted or its route changed)")
        audio.stop()
        connected()
    }

    /// The face's texts, theme and screen settings: the Mac's /config (as the page's), for this
    /// device's theme («pon el tema orb aquí»).
    func configure() async {
        guard let base = await mac.url() else { return }
        var parts = URLComponents(url: base.appendingPathComponent("config"), resolvingAgainstBaseURL: false)!
        // «skin»: remembered by an older app
        if let theme = UserDefaults.standard.string(forKey: "theme") ?? UserDefaults.standard.string(forKey: "skin") { parts.queryItems = [URLQueryItem(name: "theme", value: theme)] }
        guard let (data, _) = try? await mac.session.data(from: parts.url!),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        face.configure(config)
        #if os(iOS)
        Notices.shared.name = face.name
        #endif
        send(["type": "theme", "name": face.theme])  // its theme's sounds are played from the Mac
    }

    // MARK: Both ways

    private func heard(_ pcm: Data, _ level: Float) {
        socket?.send(.data(pcm)) { _ in }
        if Date().timeIntervalSince(lastLevel) > 0.033 {  // the face follows your voice
            lastLevel = Date()
            levels.voice = CGFloat(level)
        }
    }

    func send(_ message: [String: Any]) {
        guard let socket, let data = try? JSONSerialization.data(withJSONObject: message),
              let text = String(data: data, encoding: .utf8) else { return }
        socket.send(.string(text)) { _ in }
    }

    /// A tap on the face: it stops talking (quiet at once here), or wakes up.
    func tap() {
        audio.hush()
        send(["type": "tap"])
    }

    /// «Talk to AnyAssistant»: as a tap on its face.
    func talk() {
        if state == .connected { tap() } else { tapWhenConnected = true; start() }
    }

    /// An alarm stopped on the phone: if the Mac is ringing, a tap stops it there too.
    func stopRinging() {
        if face.state == "alarm" { send(["type": "tap"]) }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = message["type"] as? String else { return }
        switch type {
        case "hush": audio.hush()
        case "hello": eyes = message["eyes"] as? Bool ?? false
        case "pong": break
        case "photo": takePhoto(message["id"])
        case "look": Task { await showPhoto() }
        case "config": Task { await configure() }
        case "theme":
            let name = message["name"] as? String ?? ""
            if name == "default" || name.isEmpty { UserDefaults.standard.removeObject(forKey: "theme") }
            else { UserDefaults.standard.set(name, forKey: "theme") }
            Task { await configure() }
        default:
            face.receive(message)
            #if os(iOS)
            Notices.shared.handle(message)
            #endif
            if type == "state" || type == "camera" { look() }
        }
    }

    /// A line in the Mac's log (stream-api), to see what happens inside the app.
    func report(_ text: String) {
        send(["type": "log", "text": text])
    }

    // MARK: The camera

    /// Awake, it looks (a frame a second, for «¿qué ves?»); asleep, the camera is off. Shown
    /// («muestra la cámara»), it's on whatever the state. On the Mac, only shown: for «¿qué ves?»
    /// the server asks for a photo.
    private func look() {
        let state = face.look
        #if os(macOS)
        let watching = false  // on a Mac its light would be on all the time: only when shown (photos on request)
        #else
        let watching = eyes && state != "asleep" && state != "error"
        #endif
        if inFront, face.cameraShown || watching {
            if !camera.running { camera.start() }
        } else if camera.running {
            camera.stop()
        }
    }

    func cameraAllowed(_ front: Bool) {
        inFront = front
        if !front { face.cameraShown = false }
        look()
    }

    /// The photo it looks at, from the Mac (/eyes.jpg), on the face.
    private func showPhoto() async {
        guard let base = await mac.url(),
              let (data, response) = try? await mac.session.data(from: base.appendingPathComponent("eyes.jpg")),
              (response as? HTTPURLResponse)?.statusCode == 200, let image = PlatformImage(data: data) else { return }
        face.show(photo: image)
    }

    /// «Lee esto»: a full-resolution photo, to the Mac (POST /photo).
    private func takePhoto(_ id: Any?) {
        #if os(macOS)
        let canSee = true  // a Mac's camera works with its window closed too (its light, a moment)
        #else
        let canSee = inFront  // iOS doesn't allow the camera in the background
        #endif
        guard eyes, canSee, let id = id as? Int else { return }
        camera.photo { [weak self] jpeg in
            Task { @MainActor in
                guard let self else { return }
                guard let jpeg, !jpeg.isEmpty else { return self.report("photo: none (no camera, or it failed)") }
                guard let base = await self.mac.url() else { return }
                var parts = URLComponents(url: base.appendingPathComponent("photo"), resolvingAgainstBaseURL: false)!
                parts.queryItems = [URLQueryItem(name: "id", value: "\(id)"), URLQueryItem(name: "how", value: "photo")]
                var request = URLRequest(url: parts.url!)
                request.httpMethod = "POST"
                request.httpBody = jpeg
                _ = try? await self.mac.session.data(for: request)
            }
        }
    }
}

// The connection with the Mac (the plugin «stream-api»): a WebSocket with the microphone going
// up and its voice coming down, and the messages both ways, which change the face (FaceModel).
// It reconnects by itself (the network drops, the Mac restarts); while disconnected in the
// background, the microphone stays on so iOS keeps the app alive to reconnect.
// Paused while another app uses the microphone (a call): the microphone stops, the WebSocket
// stays (its face and its voice go on: an alarm must ring) and the server is told («paused»,
// with why and the app; «listening» after), so its face explains it and nothing is transcribed.
// On iOS the system interrupts the audio (Audio.swift); on the Mac, MicrophoneWatch asks
// CoreAudio who else is recording.

import Foundation
#if os(iOS)
import CallKit
#endif

@MainActor
final class Link: NSObject, ObservableObject {
    enum State: String { case connecting, connected, lost, unpaired }

    /// Why it is paused (microphone, call, interrupted) and by which app, if known.
    struct Pause {
        let why: String
        let app: String
    }

    let mac: Mac
    let audio = Audio()
    let camera = Camera()
    let face = FaceModel()
    let levels = Levels()
    /// Every theme but Eyes: the server's page, fed from here (WebTheme.swift).
    lazy var web = WebFace(face: face, levels: levels)
    @Published private(set) var state = State.connecting
    @Published private(set) var paused: Pause?

    private var socket: URLSessionWebSocketTask?
    private var wanted = false
    private var dialing = false  // looking for the Mac (once at a time)
    private var tapWhenConnected = false
    private var eyes = false  // the Mac has «eyes» on: the camera may be used
    private var inFront = true  // the app is on screen (the camera only works then)
    private var lastLevel = Date.distantPast
    #if os(iOS)
    private let calls = CXCallObserver()  // whether a call is going on: «a call», not «another app»
    #endif

    init(mac: Mac) {
        self.mac = mac
        super.init()
        audio.onRestartNeeded = { [weak self] in Task { @MainActor in self?.restartAudio() } }
        audio.onInterruption = { [weak self] began in Task { @MainActor in self?.interrupted(began) } }
        audio.onSpeech = { [weak self] level in Task { @MainActor in self?.levels.speech = CGFloat(level) } }
        camera.onFrame = { [weak self] jpeg in
            Task { @MainActor in self?.send(["type": "frame", "jpeg": jpeg.base64EncodedString()]) }
        }
    }

    // MARK: Connecting

    func start() {
        wanted = true
        if paused?.why == "interrupted" || paused?.why == "call", state == .connected, !audio.running {
            resume()  // back in front after a call whose end never came (iOS, in the background)
        }
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
        if let paused {  // still paused (the server is new to it): it says so, without the microphone
            send(["type": "paused", "why": paused.why, "app": paused.app])
        } else {
            startAudio()
        }
        Task { await configure() }
        if tapWhenConnected {
            tapWhenConnected = false
            send(["type": "tap"])
        }
    }

    private func startAudio() {
        do {
            try audio.start { [weak self] pcm, level in
                Task { @MainActor in self?.heard(pcm, level) }
            }
        } catch {
            report("no microphone: \(error.localizedDescription)")
        }
    }

    // MARK: Paused: another app uses the microphone

    /// Stops the microphone and tells the server why («microphone»: another app records, with its
    /// name if known; «call»; «interrupted»: iOS gave the audio to another app). The face and the
    /// voice go on. Nothing if the server doesn't want it (settings «pause_when_microphone_busy»).
    func pause(why: String, app: String = "") {
        guard face.shows("pause_when_microphone_busy") else { return }
        if let paused, paused.why == why, paused.app == app { return }
        let first = paused == nil
        paused = Pause(why: why, app: app)
        if first {
            report("paused: \(why)\(app.isEmpty ? "" : " (\(app))")")
            audio.stop()
        }
        send(["type": "paused", "why": why, "app": app])
    }

    /// The microphone again, and the server told.
    func resume() {
        guard paused != nil else { return }
        paused = nil
        report("listening again")
        if state == .connected { startAudio() }
        send(["type": "listening"])
    }

    /// iOS interrupted the audio (began), or the interruption ended. A call (CallKit knows: the
    /// phone, FaceTime, WhatsApp…) is said as such. The ending may not come in the background:
    /// the app resumes too when it comes to the front (App.swift: link.start()).
    private func interrupted(_ began: Bool) {
        if began {
            #if os(iOS)
            let inCall = calls.calls.contains { !$0.hasEnded }
            #else
            let inCall = false
            #endif
            pause(why: inCall ? "call" : "interrupted")
        } else {
            resume()
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
        guard state == .connected, paused == nil else { return }
        report("audio restarted (its route changed)")
        audio.stop()
        startAudio()
    }

    /// The face's texts, theme and screen settings: the Mac's /config (as the page's), for this
    /// device's theme («pon el tema orb aquí») and its interface's language (the app's setting, kept
    /// on the server for this device too: a choice made here goes there; one made there, in the
    /// Mac's Devices, comes here).
    func configure(again: Bool = true) async {
        guard let base = await mac.url() else { return }
        if Interface.unsaved { await saveInterfaceLanguage(base) }
        var parts = URLComponents(url: base.appendingPathComponent("config"), resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "device", value: mac.device), URLQueryItem(name: "ui", value: Interface.code)]
        if let theme = UserDefaults.standard.string(forKey: "theme") { parts.queryItems?.append(URLQueryItem(name: "theme", value: theme)) }
        guard let (data, _) = try? await mac.session.data(from: parts.url!),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        if let theirs = config["ui_language"] as? String, theirs != Interface.chosen, !Interface.unsaved, again {
            Interface.choose(theirs, fromServer: true)  // changed in the Mac's Devices: this app too
            return await configure(again: false)
        }
        web.configured(base: base, cookies: mac.cookies(for: base))
        face.configure(config)
        web.forward(["type": "config", "ui": face.lang])  // the page reads its texts and settings again
        #if os(iOS)
        Notices.shared.name = face.name
        await Notices.shared.fetchAlarmSound(from: base, theme: face.theme, session: mac.session)
        #endif
        send(["type": "theme", "name": face.theme])  // its theme's sounds are played from the Mac
    }

    /// The interface's language chosen in the app's settings: saved on the server for this device,
    /// and the face's texts in it.
    func interfaceLanguageChanged() {
        Task { await configure(again: false) }
    }

    private func saveInterfaceLanguage(_ base: URL) async {
        var request = URLRequest(url: base.appendingPathComponent("devices/ui_language"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["device": mac.device, "ui_language": Interface.chosen])
        if let (_, response) = try? await mac.session.data(for: request),
           [200, 404].contains((response as? HTTPURLResponse)?.statusCode ?? 0) {
            Interface.unsaved = false  // saved (404: the plugin «devices» is off; nothing to keep in step)
        }
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
        case "look":  // the page shows it itself; Eyes, here
            if web.shows(face.theme) { web.forward(message) } else { Task { await showPhoto() } }
        case "config": Task { await configure() }
        case "theme":
            let name = message["name"] as? String ?? ""
            if name == "default" || name.isEmpty { UserDefaults.standard.removeObject(forKey: "theme") }
            else { UserDefaults.standard.set(name, forKey: "theme") }
            Task { await configure() }
        default:
            face.receive(message)
            web.forward(message)
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

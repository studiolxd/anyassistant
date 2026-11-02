// The assistant on this Mac too: the same client as the iPhone's (Client/ links the iPhone
// app's own files: its face, microphone, camera and link), in a window and in the menu bar.
// It talks to this Mac's server (no code: the server trusts its own Mac) or, on a Mac
// without the server, only to another Mac's (paired with its code, as a phone).

import AppKit
import AVFoundation
import Combine
import SwiftUI

@MainActor
final class Client: ObservableObject {
    static let shared = Client()

    enum Role: String { case server, client }

    /// This Mac runs the server (and talks to it), or only talks to another Mac's.
    @Published var role: Role = Role(rawValue: UserDefaults.standard.string(forKey: "role") ?? "") ?? .server {
        didSet { UserDefaults.standard.set(role.rawValue, forKey: "role") }
    }
    /// Its microphone on: you can talk to it on this Mac (it says so in the menu bar).
    /// Its face's window is open (the menu says «Hide Eva» then): from the windows themselves
    /// (SwiftUI doesn't always say when one is dismissed).
    @Published var faceShown = false

    /// The face's window (kept when it appears: WindowFinder).
    weak var faceWindowSeen: NSWindow?

    static func faceWindow() -> NSWindow? { shared.faceWindowSeen }

    /// Whether its window is on screen now (on any window opening or closing).
    func followFace(closing: NSWindow? = nil) {
        let window = Client.faceWindow()
        let shown = window != nil && window !== closing && window!.isVisible
        if shown != faceShown { faceShown = shown }
        link.cameraAllowed(shown)
    }

    func hideFace() {
        Client.faceWindow()?.close()
    }
    @Published var listening = UserDefaults.standard.object(forKey: "listening") as? Bool ?? true {
        didSet { UserDefaults.standard.set(listening, forKey: "listening"); update() }
    }
    let mac = Mac(agent: "AnyAssistant Mac")
    let link: Link
    /// Who else records on this Mac (a call in Zoom, FaceTime…): while they do, it is paused.
    let microphone = MicrophoneWatch()
    private var watching: Set<AnyCancellable> = []

    private init() {
        link = Link(mac: mac)
        link.cameraAllowed(false)  // only while its window is open
        // The menu bar follows the link, whether it is paused, and the face's name.
        link.$state.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watching)
        link.$paused.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watching)
        link.face.$name.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watching)
        microphone.onChange = { [weak self] app in
            guard let self else { return }
            if let app { link.pause(why: "microphone", app: app) } else { link.resume() }
        }
    }

    var name: String { link.face.name }

    /// «Paused: Zoom is using the microphone», for the menu; nil while it listens.
    var pausedText: String? {
        guard let paused = link.paused else { return nil }
        return paused.app.isEmpty ? T("Paused: another app is using the microphone")
            : String(format: T("Paused: %@ is using the microphone"), paused.app)
    }

    /// Whether it has a server to talk to: this Mac's, or the one it's paired with.
    var ready: Bool { role == .server ? Server.shared.installed : mac.paired }

    func begin() {
        if role == .server { here() }
        update()
        checkPermissions()
        // Every few seconds too: a permission changed in System Settings shows in the menu.
        guard permissionsTimer == nil else { return }
        permissionsTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { _ in
            MainActor.assumeIsolated { Client.shared.checkPermissions() }
        }
    }

    /// This Mac's own server.
    private func here() {
        mac.host = "127.0.0.1"
        mac.port = Server.shared.port
    }

    /// The microphone isn't allowed (System Settings → Privacy → Microphone).
    @Published private(set) var refused = false
    /// The camera isn't allowed (System Settings → Privacy → Camera): «muestra la cámara», «¿qué ves?».
    @Published private(set) var cameraRefused = false
    private var permissionsTimer: Timer?

    /// The permissions as macOS has them now (they change in System Settings, not here).
    func checkPermissions() {
        let camera = AVCaptureDevice.authorizationStatus(for: .video)
        cameraRefused = camera == .denied || camera == .restricted
        let microphone = AVCaptureDevice.authorizationStatus(for: .audio)
        if microphone == .authorized, refused { update() }  // allowed meanwhile: it hears now
    }

    func update() {
        guard listening && ready else {
            microphone.stop()
            return link.stop()
        }
        microphone.start()  // it pauses the link while another app records (if the settings want it)
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .notDetermined:  // asked once, before the microphone is opened
            AVCaptureDevice.requestAccess(for: .audio) { _ in Task { @MainActor in self.update() } }
        case .authorized:
            refused = false
            link.start()
        default:
            refused = true
            link.start()  // its face and its voice, without hearing you
        }
    }

    /// Only a client of another Mac's server: its address and the code its app shows.
    func useAnother(host: String, port: Int, code: String) async throws {
        link.stop()
        mac.forget()
        mac.host = host
        mac.port = port
        try await mac.pair(code: code)
        Server.shared.stop()
        role = .client
        update()
    }

    /// The server on this Mac again.
    func useThisMac() {
        link.stop()
        mac.forget()
        role = .server
        begin()
    }

    /// What the menu says about it, as a client of another Mac.
    var status: String {
        switch link.state {
        case .connected: pausedText ?? String(format: T("Connected to %@"), mac.host)
        case .unpaired: T("It has to be paired again.")
        default: listening ? T("Looking for the server…") : T("The microphone is off")
        }
    }

    /// Where to allow the microphone.
    func openPrivacy(_ what: String = "Privacy_Microphone") {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?\(what)")!)
    }
}

/// Its face in a window: tap it to wake it up, or to stop it talking.
struct FaceWindow: View {
    @ObservedObject var client: Client

    var body: some View {
        let link = client.link
        ThemeView(face: link.face, levels: link.levels, camera: link.camera)
            .contentShape(Rectangle())
            .onTapGesture { link.tap() }
            .overlay(alignment: .bottom) {
                if !client.listening {
                    Button(T("Turn the microphone on")) { client.listening = true }
                        .padding(.bottom, 20)
                } else if client.refused {
                    Button(T("Allow the microphone…")) { client.openPrivacy() }
                        .padding(.bottom, 20)
                }
            }
            .navigationTitle(client.name)
            .background(WindowFinder { window in client.faceWindowSeen = window; client.followFace() })
            .onAppear { client.followFace() }  // «¿qué ves?», «muestra la cámara»: its camera while it shows
            .onDisappear { client.followFace() }
    }
}

/// The NSWindow a view is in, once it has one.
struct WindowFinder: NSViewRepresentable {
    let found: (NSWindow) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { if let window = view.window { found(window) } }
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        DispatchQueue.main.async { if let window = view.window { found(window) } }
    }
}

/// Connecting to another server (this device only talks to it), as the iPhone pairs: the servers
/// announcing themselves on this network (Bonjour) or «Other server…» (its host and port), then its
/// pairing code, if it asks for one. «Back» and the step's action at the bottom, as the installer's.
struct AnotherMacView: View {
    @ObservedObject var client: Client
    var done: () -> Void
    var back: () -> Void

    enum Step { case choose, manual, code }
    @StateObject private var browser = ServerBrowser()
    @State private var step = Step.choose
    @State private var chosen: String?  // the server picked in the list (its id), or «other»
    @State private var server = ""  // «Eva en MacBook-Air-de-Suvi», or the host typed
    @State private var host = ""
    @State private var port = 8080
    @State private var code = ""
    @State private var working = false
    @State private var problem: String?
    @FocusState private var typing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            switch step {
            case .choose: choose
            case .manual: manual
            case .code: codeStep
            }
            if let problem { Text(problem).foregroundStyle(.red).font(.callout) }
            Spacer(minLength: 0)
            HStack {
                Button(T("Back")) {
                    problem = nil
                    switch step {
                    case .choose: back()
                    case .manual: step = .choose
                    case .code: step = chosen == "other" ? .manual : .choose
                    }
                }
                Spacer()
                if working { ProgressView().controlSize(.small) }
                Button(step == .code ? T("Pair") : T("Next")) { Task { await next() } }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                    .disabled(working || !ready)
            }
        }
        .onAppear { browser.start() }
        .onDisappear { browser.stop() }
    }

    /// The servers found, but not this Mac's own (if it is one too): this device talks to another.
    var others: [ServerBrowser.Found] {
        let own = try? String(contentsOf: Server.shared.data.appending(path: "server-id"), encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return browser.servers.filter { $0.server == nil || $0.server != own }
    }

    var ready: Bool {
        switch step {
        case .choose: chosen != nil
        case .manual: !host.trimmingCharacters(in: .whitespaces).isEmpty
        case .code: code.count == 6
        }
    }

    var choose: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(T("Another Mac's server")).font(.title2.bold())
            Text(T("This device will only be used to talk to the assistant.")).foregroundStyle(.secondary)
            Form {
                Section {
                    if others.isEmpty {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text(T("Searching…")).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(others) { found in
                        row(found.assistant, found.computer, "server.rack", selected: chosen == found.id)
                            .onTapGesture { chosen = found.id; problem = nil }
                    }
                } header: {
                    Text(T("Servers on this network"))
                } footer: {
                    Text(T("AnyAssistant servers on this network are shown here.")).font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    row(T("Other server…"), nil, "ellipsis.circle", selected: chosen == "other")
                        .onTapGesture { chosen = "other"; problem = nil }
                }
            }
            .formStyle(.grouped)
        }
    }

    func row(_ title: String, _ detail: String?, _ symbol: String, selected: Bool) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).font(.title3).foregroundStyle(Color.accentColor).frame(width: 26)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                if let detail { Text(detail).font(.callout).foregroundStyle(.secondary) }
            }
            Spacer()
            if selected { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
        }
        .contentShape(Rectangle())
    }

    var manual: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(T("Other server")).font(.title2.bold())
            Form {
                Section {
                    TextField(T("Host"), text: $host, prompt: Text("anyassistant.local"))
                    TextField(T("Port"), value: $port, format: .number.grouping(.never))
                } footer: {
                    Text(T("The name or IP address of the server.")).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
        }
    }

    var codeStep: some View {
        VStack(spacing: 22) {
            VStack(spacing: 6) {
                Text(T("Pairing code")).font(.title2.bold())
                Text(server).foregroundStyle(.secondary)
            }
            .padding(.top, 24)
            ZStack {
                TextField("", text: $code)  // the real field, behind the boxes
                    .focused($typing)
                    .opacity(0.01)
                    .onChange(of: code) { _, new in
                        code = String(new.filter(\.isNumber).prefix(6))
                        if code.count == 6 { Task { await next() } }
                    }
                HStack(spacing: 10) {
                    ForEach(0..<6, id: \.self) { i in
                        Text(i < code.count ? String(Array(code)[i]) : "")
                            .font(.title.monospacedDigit().weight(.semibold))
                            .frame(width: 46, height: 56)
                            .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.07)))
                            .overlay(RoundedRectangle(cornerRadius: 10)
                                .stroke(i == code.count && typing ? Color.accentColor : .clear, lineWidth: 2))
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { typing = true }
            }
            Text(T("To get the code, open AnyAssistant on the server and select Connect another device."))
                .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .onAppear { typing = true }
    }

    func next() async {
        guard !working else { return }
        problem = nil
        switch step {
        case .choose:
            if chosen == "other" { step = .manual; return }
            guard let found = browser.servers.first(where: { $0.id == chosen }) else { return }
            host = found.address
            port = found.port
            server = String(format: T("%@ on %@"), found.assistant, found.computer)
            if found.pairing { code = ""; step = .code } else { await connect() }
        case .manual:
            host = host.trimmingCharacters(in: .whitespaces)
            server = host
            client.mac.host = host
            client.mac.port = port
            working = true
            let asks = await client.mac.needsCode()
            working = false
            switch asks {
            case .some(true): code = ""; step = .code
            case .some(false): await connect()
            case .none: problem = T("That Mac doesn't answer: is AnyAssistant running there, on this network?")
            }
        case .code:
            await connect()
        }
    }

    func connect() async {
        working = true
        defer { working = false }
        do {
            try await client.useAnother(host: host, port: port, code: code)
            done()
        } catch Mac.Failure.wrongCode {
            problem = T("That code isn't right (or it's too old): ask for another.")
            code = ""
        } catch {
            problem = T("That Mac doesn't answer: is AnyAssistant running there, on this network?")
        }
    }
}

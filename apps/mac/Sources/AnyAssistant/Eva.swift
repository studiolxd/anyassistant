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
    private var watching: Set<AnyCancellable> = []

    private init() {
        link = Link(mac: mac)
        link.cameraAllowed(false)  // only while its window is open
        // The menu bar follows the link and the face's name.
        link.$state.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watching)
        link.face.$name.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &watching)
    }

    var name: String { link.face.name }

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
        guard listening && ready else { return link.stop() }
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
        case .connected: String(format: T("Connected to %@"), mac.host)
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
        SkinView(face: link.face, levels: link.levels, camera: link.camera)
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

/// On a Mac without the server: the other Mac's address and its code.
struct AnotherMacView: View {
    @ObservedObject var client: Client
    var done: () -> Void
    var back: () -> Void
    @State private var host = "anyassistant.local"
    @State private var port = 8080
    @State private var code = ""
    @State private var working = false
    @State private var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(T("Another Mac's server")).font(.title2.bold())
            Text(T("This Mac is only its microphone, speaker, camera and screen. On the Mac with the server: AnyAssistant → Pair a device…, for the code."))
                .foregroundStyle(.secondary)
            Form {
                TextField(T("Host"), text: $host)
                TextField(T("Port"), value: $port, format: .number.grouping(.never))
                TextField(T("Code"), text: $code)
            }
            .formStyle(.grouped)
            if let problem { Text(problem).foregroundStyle(.red) }
            Spacer()
            HStack {
                Button(T("Back"), action: back)
                Spacer()
                if working { ProgressView().controlSize(.small) }
                Button(T("Connect")) { Task { await connect() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(working || host.isEmpty)
            }
        }
    }

    func connect() async {
        working = true
        problem = nil
        defer { working = false }
        do {
            try await client.useAnother(host: host.trimmingCharacters(in: .whitespaces), port: port,
                                        code: code.filter(\.isNumber))
            done()
        } catch Mac.Failure.wrongCode {
            problem = T("That code isn't right (or it's too old): ask for another.")
        } catch {
            problem = T("That Mac doesn't answer: is AnyAssistant running there, on this network?")
        }
    }
}

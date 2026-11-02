// AnyAssistant on the iPhone and the iPad, native: its face is one of the themes (Themes.swift,
// drawn as the page's: Eyes, Orb, Bedside, Minimal), following the Mac's state, texts and
// settings; the microphone and the speaker go over a WebSocket (plugin «stream-api»), so it
// keeps listening with the screen off. Alarms, timers and reminders are also the phone's own
// notifications (they ring with the app closed); answers and messages arrive as notifications
// while it's in the background. Siri, Shortcuts and the Action button: «Talk to AnyAssistant».
// Paired once with the 6-digit code the Mac app shows («Pair a device…»). iOS 15 or later.

import SwiftUI

@main
struct AnyAssistantApp: App {
    @StateObject private var mac = Mac(agent: AnyAssistantApp.agent)

    /// How it introduces itself to the Mac: «AnyAssistant iPhone», «… iPad».
    static var agent: String {
        "AnyAssistant " + UIDevice.current.model
    }

    init() {
        Notices.shared.start()
    }

    var body: some Scene {
        WindowGroup {
            if mac.paired {
                MainView(mac: mac)
            } else {
                PairView(mac: mac)
                    .onOpenURL(perform: open)
            }
        }
    }

    /// Opened by «Abrir en la app» on the QR's page (anyassistant://connect?…): it pairs by itself.
    func open(_ url: URL) {
        if let invitation = Mac.Invitation(url) { mac.invite(invitation) }
    }
}

extension Notification.Name {
    /// «Talk to AnyAssistant» (Siri, Shortcuts, the Action button): as if you had said its name.
    static let talk = Notification.Name("talk")
}

struct MainView: View {
    @ObservedObject var mac: Mac
    @StateObject private var link: Link
    @Environment(\.scenePhase) private var phase
    @AppStorage("background") private var background = true
    @AppStorage("awake") private var awake = true
    @State private var settings = false

    init(mac: Mac) {
        self.mac = mac
        _link = StateObject(wrappedValue: Link(mac: mac))
    }

    var body: some View {
        ThemeView(face: link.face, levels: link.levels, camera: link.camera)
            .contentShape(Rectangle())
            .onTapGesture { link.tap() }  // it stops talking, or wakes up
            .onLongPressGesture(minimumDuration: 0.8) { settings = true }  // always, whatever the theme
            .overlay { SettingsButton(face: link.face) { settings = true } }
            .statusBarHidden(true)
            .modifier(Quiet())
            .background(Orientation())
            .sheet(isPresented: $settings) { SettingsView(mac: mac, link: link) }
            .onAppear {
                link.start()
                UIApplication.shared.isIdleTimerDisabled = awake
            }
            .onChange(of: phase) { now in
                switch now {
                case .active:
                    Notices.shared.foreground = true
                    UIApplication.shared.isIdleTimerDisabled = awake
                    link.cameraAllowed(true)
                    link.start()
                case .background:
                    Notices.shared.foreground = false
                    link.cameraAllowed(false)
                    if !background { link.stop() }
                default:
                    break
                }
            }
            .onChange(of: awake) { on in UIApplication.shared.isIdleTimerDisabled = on }
            .onReceive(NotificationCenter.default.publisher(for: .talk)) { _ in link.talk() }
            .onReceive(NotificationCenter.default.publisher(for: .stopRinging)) { _ in link.stopRinging() }
            .onOpenURL { url in  // the QR page's link while paired: to that server (a way back if it fails)
                if let invitation = Mac.Invitation(url) { link.stop(); mac.invite(invitation) }
            }
    }
}

/// «Ajustes», only asleep or in error (where it's needed: its address, pairing again…), inside
/// the safe area. Where it goes and its colour are the theme's (its options «settings»: bottom, top,
/// bottom-left…; «settings_style»: text or icon; «settings_color», else its accent).
/// Holding the screen opens it too, always.
struct SettingsButton: View {
    @ObservedObject var face: FaceModel
    let open: () -> Void

    var body: some View {
        if face.look == "asleep" || face.look == "error" {
            Button(action: open) {
                if face.options["settings_style"] == "icon" {
                    Image(systemName: "gearshape.fill")
                        .font(.body)
                        .foregroundColor(tint.opacity(0.8))
                        .frame(width: 40, height: 40)
                        .background(Circle().fill(tint.opacity(0.14)))
                } else {
                    Text(T("Settings"))
                        .font(.subheadline.weight(.medium))
                        .foregroundColor(tint.opacity(0.85))
                        .padding(.horizontal, 18)
                        .padding(.vertical, 9)
                        .background(Capsule().fill(tint.opacity(0.14)))
                }
            }
            .accessibilityLabel(T("Settings"))
            .padding(12)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: place)
            .transition(.opacity)
        }
    }

    var tint: Color { face.color("settings_color", face.color("accent", face.color("glow", .white))) }

    var place: Alignment {
        switch face.options["settings"] ?? "bottom" {
        case "top": return .top
        case "top-left": return .topLeading
        case "top-right": return .topTrailing
        case "bottom-left": return .bottomLeading
        case "bottom-right": return .bottomTrailing
        default: return .bottom
        }
    }
}

struct SettingsView: View {
    @ObservedObject var mac: Mac
    @ObservedObject var link: Link
    @State private var connectedTo: (host: String, port: Int)?  // where it was when the settings opened
    @State private var checking = false  // «Connect» pressed: trying it
    @State private var problem: String?  // it didn't answer there

    /// The address or port changed here: connecting again is what applies it.
    var changed: Bool { connectedTo.map { $0.host != mac.host || $0.port != mac.port } ?? false }
    @AppStorage("background") private var background = true
    @AppStorage("awake") private var awake = true
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationView {
            Form {
                Section {
                    Toggle(T("Keep listening with the screen off"), isOn: $background)
                    Toggle(T("Keep the screen on"), isOn: $awake)
                } footer: {
                    Text(T("With the screen off it listens as long as the app isn't closed; iOS shows the microphone in use."))
                }
                Section(T("Server")) { ServerFields(mac: mac) }
                Section {
                    // «Connected» (nothing to do) while it is, at the address it has; «Connect» if it
                    // isn't, or the address or port changed (leaving the settings connects too);
                    // «Connecting…» while it tries, and why not if it doesn't answer.
                    let connected = link.state == .connected && !changed
                    Button(action: connect) {
                        HStack {
                            Text(checking ? T("Connecting…") : connected ? T("Connected") : T("Connect"))
                            if checking { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(connected || checking)
                } footer: {
                    if let problem { Text(problem).foregroundColor(.red) }
                }
                Section {
                    Button(T("Pair again"), role: .destructive) { link.stop(); mac.pairAgain(); dismiss() }
                }
            }
            .onAppear { connectedTo = (mac.host, mac.port) }
            .onChange(of: mac.host) { _ in problem = nil }
            .onChange(of: mac.port) { _ in problem = nil }
            .onDisappear { if changed { mac.moved(); link.restart() } }
            .navigationTitle(T("Settings"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(T("Done")) { dismiss() } } }
        }
    }

    func connect() {
        if changed { mac.moved() }
        connectedTo = (mac.host, mac.port)
        problem = nil
        checking = true
        link.restart()
        Task {
            let answers = await mac.url() != nil
            checking = false
            if !answers {
                problem = T("The server isn't answering: is AnyAssistant running and this device on the same network?")
            }
        }
    }
}

/// No home bar while it's the face (iOS 16 or later; it comes back with a swipe).
struct Quiet: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 16.0, *) {
            content.persistentSystemOverlays(.hidden)
        } else {
            content
        }
    }
}

/// Keeps the screen's orientation for the camera (upright photos).
struct Orientation: View {
    var body: some View {
        GeometryReader { _ in
            Color.clear.onAppear(perform: update)
                .onReceive(NotificationCenter.default.publisher(for: UIDevice.orientationDidChangeNotification)) { _ in update() }
        }
    }

    func update() {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        Camera.interface = scene?.interfaceOrientation ?? .portrait
    }
}


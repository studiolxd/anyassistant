// AnyAssistant on the iPhone and the iPad, native: its face is one of the skins (Skins.swift,
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
            }
        }
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
        SkinView(face: link.face, levels: link.levels, camera: link.camera)
            .contentShape(Rectangle())
            .onTapGesture { link.tap() }  // it stops talking, or wakes up
            .overlay(alignment: .bottomTrailing) {
                Image(systemName: "gearshape")
                    .font(.title3)
                    .foregroundColor(.white.opacity(0.35))
                    .frame(width: 56, height: 56)
                    .contentShape(Rectangle())
                    .onTapGesture { settings = true }
                    .accessibilityLabel(T("Settings"))
                    .accessibilityAddTraits(.isButton)
                    .padding(.trailing, 6)
                    .padding(.bottom, 6)
            }
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
    }
}

struct SettingsView: View {
    @ObservedObject var mac: Mac
    @ObservedObject var link: Link
    @State private var connectedTo: (host: String, port: Int)?  // where it was when the settings opened

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
                Section(T("Mac")) {
                    TextField(T("Address"), text: $mac.host).autocapitalization(.none).disableAutocorrection(true)
                    TextField(T("Port"), value: $mac.port, format: .number.grouping(.never)).keyboardType(.numberPad)
                    // «Connected» (nothing to do) while it is, at the address it has; «Connect» if it
                    // isn't, or the address or port changed (leaving the settings connects too).
                    let connected = link.state == .connected && !changed
                    Button(connected ? T("Connected") : T("Connect")) {
                        link.restart()
                        connectedTo = (mac.host, mac.port)
                    }
                    .disabled(connected)
                }
                Section {
                    Button(T("Pair again"), role: .destructive) { link.stop(); mac.pairAgain(); dismiss() }
                }
            }
            .onAppear { connectedTo = (mac.host, mac.port) }
            .onDisappear { if changed { link.restart() } }
            .navigationTitle(T("Settings"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(T("Done")) { dismiss() } } }
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


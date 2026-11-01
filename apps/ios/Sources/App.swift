// AnyAssistant on the iPhone and the iPad: the face is the Mac's own page (with its skins), in a
// web view; the microphone and the speaker are the app's (plugin «stream-api»: a WebSocket), so
// it keeps listening with the screen off. Alarms, timers and reminders are also the phone's own
// notifications (they ring with the app closed); answers and messages arrive as notifications
// while it's in the background. Siri, Shortcuts and the Action button: «Talk to AnyAssistant».
// Paired once with the 6-digit code the Mac app shows («Pair a device…»). iOS 15 or later.

import SwiftUI

@main
struct AnyAssistantApp: App {
    @StateObject private var mac = Mac(agent: "AnyAssistant " + UIDevice.current.model)  // iPhone, iPad

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
        ZStack {
            Color.black.ignoresSafeArea()
            Face(link: link).ignoresSafeArea()
        }
        // The gear: on its own layer above the web view (which otherwise takes the taps), with
        // a finger-sized area to tap.
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
                link.start()
                link.showAgain()
            case .background:
                Notices.shared.foreground = false
                if !background { link.stop() }
            default:
                break
            }
        }
        .onChange(of: awake) { on in UIApplication.shared.isIdleTimerDisabled = on }
        .onReceive(NotificationCenter.default.publisher(for: .talk)) { _ in link.talk() }
    }
}

struct SettingsView: View {
    @ObservedObject var mac: Mac
    let link: Link
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
                    Button(T("Reconnect")) { link.restart(); dismiss() }
                }
                Section {
                    Button(T("Pair again"), role: .destructive) { link.stop(); mac.unpair(); dismiss() }
                }
            }
            .navigationTitle(T("Settings"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(T("Done")) { dismiss() } } }
        }
    }
}

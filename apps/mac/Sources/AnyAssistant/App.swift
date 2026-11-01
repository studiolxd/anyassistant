// AnyAssistant: in the menu bar. The first time, it installs the server (with what
// comes, or step by step); then it runs it, says how it is, and pairs devices. The
// assistant is on this Mac too (Eva.swift): its face in a window, its microphone and
// speaker. On a Mac without the server, it is only that: a client of another Mac's.

import AppKit
import CoreImage.CIFilterBuiltins
import ServiceManagement
import SwiftUI

@main
struct AnyAssistantApp: App {
    @StateObject private var server = Server.shared
    @StateObject private var client = Client.shared
    @StateObject private var setup = Setup()
    @NSApplicationDelegateAdaptor private var delegate: Delegate

    var body: some Scene {
        MenuBarExtra {
            MenuView(server: server, client: client)
        } label: {
            Image(systemName: icon)
        }
        Window("AnyAssistant", id: "face") {
            FaceWindow(client: client)
                .frame(minWidth: 320, minHeight: 400)
        }
        .defaultSize(width: 480, height: 640)
        Window("AnyAssistant", id: "setup") {
            SetupView(setup: setup, client: client)
                .frame(width: 520, height: 480)
        }
        .windowResizability(.contentSize)
        Window(T("Settings"), id: "settings") {
            SettingsView()
                .frame(minWidth: 760, minHeight: 520)
        }
        Window(T("Devices"), id: "devices") {
            DevicesView()
                .frame(minWidth: 560, minHeight: 360)
        }
        Window(T("Pair a device"), id: "pair") {
            PairView(server: server)
                .frame(width: 660, height: 380)
        }
        .windowResizability(.contentSize)
    }

    var icon: String {
        if client.role == .client {
            return client.link.state == .connected ? "waveform.circle.fill" : "circle.dotted"
        }
        return switch server.state {
        case .running: server.connected ? "waveform.circle.fill" : "waveform.circle"
        case .failed: "exclamationmark.circle"
        default: "circle.dotted"
        }
    }
}

final class Delegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { @MainActor in
            let server = Server.shared
            let client = Client.shared
            defer { client.begin() }
            if client.role == .client { return }  // no server here: another Mac's
            if server.installed {
                server.launch()
            } else {
                server.state = .notInstalled
                Delegate.show("setup")
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated {
            Client.shared.link.stop()
            if Client.shared.role == .server { Server.shared.stop() }
        }
        Thread.sleep(forTimeInterval: 1)
    }

    /// Opens one of the app's windows (a menu bar app has to bring itself forward).
    @MainActor static func show(_ id: String) {
        NSApp.activate(ignoringOtherApps: true)
        NotificationCenter.default.post(name: .open, object: id)
    }
}

extension Notification.Name {
    static let open = Notification.Name("AnyAssistantOpen")
}

// MARK: - The menu

struct MenuView: View {
    @ObservedObject var server: Server
    @ObservedObject var client: Client
    @Environment(\.openWindow) private var openWindow
    @State private var login = SMAppService.mainApp.status == .enabled

    var body: some View {
        if client.role == .client { clientMenu } else { serverMenu }
    }

    /// A client of another Mac's server: its face and its microphone, nothing else here.
    @ViewBuilder var clientMenu: some View {
        Text(client.status)
        Divider()
        Button(String(format: T("Show %@"), client.name)) { open("face") }
        Toggle(T("Listen on this Mac"), isOn: $client.listening)
        if client.refused { Button(T("Allow the microphone…")) { client.openPrivacy() } }
        Divider()
        Button(T("Run the server on this Mac…")) {
            client.useThisMac()
            if server.installed { server.launch() } else { open("setup") }
        }
        loginToggle
        Divider()
        quit
    }

    var loginToggle: some View {
        Toggle(T("Open at login"), isOn: $login)
            .onChange(of: login) { _, on in
                if on { try? SMAppService.mainApp.register() } else { try? SMAppService.mainApp.unregister() }
            }
    }

    var quit: some View {
        Button(T("Quit AnyAssistant")) { NSApp.terminate(nil) }
            .keyboardShortcut("q")
            .onReceive(NotificationCenter.default.publisher(for: .open)) { note in
                if let id = note.object as? String { openWindow(id: id) }
            }
    }

    @ViewBuilder var serverMenu: some View {
        Text(status)
        ForEach(Array(server.devices.enumerated()), id: \.offset) { _, device in  // which ones
            Text("   " + (device.name.isEmpty ? T("a device") : device.name)
                 + (device.current && server.devices.count > 1 ? " · " + T("talking to you") : ""))
        }
        if let busy = server.busy { Text(busy) }
        Divider()
        if server.state == .notInstalled {
            Button(T("Install…")) { open("setup") }
        } else {
            Button(String(format: T("Show %@"), client.name)) { open("face") }
            Toggle(T("Listen on this Mac"), isOn: $client.listening)
            if client.refused { Button(T("Allow the microphone…")) { client.openPrivacy() } }
            Divider()
            Button(T("Pair a device…")) { open("pair") }
            Button(T("Devices…")) { open("devices") }
            Button(T("Skins…")) {  // every state of each skin, to see them (the plugin «skins»)
                NSWorkspace.shared.open(URL(string: "http://127.0.0.1:\(server.port)/skins")!)
            }
            Divider()
            if server.state == .stopped {
                Button(T("Start")) { server.start() }
            } else {
                Button(T("Restart")) { server.restart() }
                Button(T("Stop")) { server.stop() }
            }
            Button(T("Show the log")) {
                NSWorkspace.shared.open([server.log], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Console.app"),
                                        configuration: NSWorkspace.OpenConfiguration())
            }
            Button(T("Settings…")) { open("settings") }
                .keyboardShortcut(",")
            Button(T("Install steps again…")) { open("setup") }
            loginToggle
        }
        Divider()
        quit
    }

    var status: String {
        switch server.state {
        case .notInstalled: T("Not installed yet")
        case .stopped: T("Stopped")
        case .starting: T("Starting…")
        case .running:
            switch server.devices.count {
            case 0: server.connected ? T("Running · a device connected") : T("Running · no device")
            case 1: T("Running · a device connected")
            default: String(format: T("Running · %d devices connected"), server.devices.count)
            }
        case .failed(let why): why
        }
    }

    func open(_ id: String) {
        NSApp.activate(ignoringOtherApps: true)
        openWindow(id: id)
    }
}

// MARK: - Installing

struct SetupView: View {
    @ObservedObject var setup: Setup
    @ObservedObject var client: Client
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            switch setup.phase {
            case .welcome: welcome
            case .another:
                AnotherMacView(client: client, done: {
                    dismissWindow(id: "setup")
                    NSApp.activate(ignoringOtherApps: true)
                    openWindow(id: "face")
                }, back: { setup.phase = .welcome })
            case .preparing: working(setup.note)
            case .questions: form
            case .installing, .finished: progress
            }
        }
        .padding(24)
        .onReceive(NotificationCenter.default.publisher(for: .open)) { note in
            if let id = note.object as? String { openWindow(id: id) }
        }
    }

    var welcome: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("AnyAssistant").font(.largeTitle.bold())
            Text(T("A voice assistant on this Mac, with an old phone or tablet as its eyes, mouth and ears."))
                .foregroundStyle(.secondary)
            Spacer()
            Button {
                Task { await setup.installWithDefaults() }
            } label: {
                Label(T("Install with what comes"), systemImage: "bolt.fill")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large).buttonStyle(.borderedProminent)
            Button {
                Task { await setup.askQuestions() }
            } label: {
                Label(T("Set it up step by step"), systemImage: "list.number")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large)
            Text(T("You can change everything later. The speech models download once (a few hundred MB)."))
                .font(.footnote).foregroundStyle(.secondary)
            Button(T("The server is on another Mac: use this one only to talk to it")) { setup.phase = .another }
                .buttonStyle(.link)
        }
    }

    func working(_ text: String) -> some View {
        VStack(spacing: 12) {
            Spacer()
            ProgressView()
            Text(text).foregroundStyle(.secondary)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    var form: some View {
        VStack(alignment: .leading) {
            Text(T("Step by step")).font(.title2.bold())
            Form {
                ForEach($setup.questions) { $question in
                    Section {
                        if let choices = question.choices {
                            Picker(question.title, selection: $question.answer) {
                                ForEach(choices, id: \.self) { Text($0.label).tag($0.value) }
                            }
                        } else {
                            TextField(question.title, text: Binding(
                                get: { question.answer as? String ?? "" }, set: { question.answer = $0 }))
                        }
                    } footer: {
                        if !question.help.isEmpty { Text(question.help).font(.footnote).foregroundStyle(.secondary) }
                    }
                }
                Toggle(T("Open AnyAssistant at login"), isOn: $setup.startAtLogin)
            }
            .formStyle(.grouped)
            Button(T("Install")) { Task { await setup.installWithAnswers() } }
                .buttonStyle(.borderedProminent).frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    var progress: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(setup.phase == .finished ? (setup.failed ? T("Installed, with problems")
                                                          : T("Installed"))
                                          : T("Installing…"))
                .font(.title2.bold())
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(setup.steps) { step in
                        HStack(alignment: .top) {
                            symbol(step.status).frame(width: 18)
                            VStack(alignment: .leading) {
                                Text(step.title)
                                if !step.text.isEmpty {
                                    Text(step.text).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                }
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if setup.phase == .finished {
                Button(T("Pair your tablet or phone")) {
                    dismissWindow(id: "setup")
                    NSApp.activate(ignoringOtherApps: true)
                    openWindow(id: "pair")
                }
                .buttonStyle(.borderedProminent).frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
    }

    @ViewBuilder func symbol(_ status: StepRow.Status) -> some View {
        switch status {
        case .running: ProgressView().controlSize(.small)
        case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .skipped: Image(systemName: "minus.circle").foregroundStyle(.secondary)
        case .failed: Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
        }
    }
}

// MARK: - Pairing a device

/// The address a device opens: anyassistant.local (Bonjour) or, on old devices that don't
/// resolve .local names, the Mac's address; over HTTPS if the plugin «https» is on.
struct PairView: View {
    @ObservedObject var server: Server
    @State private var code: String?
    @State private var asked = false
    @State private var pairingOff = false
    @State private var waiting = true  // until the server answers (it may be starting)
    @State private var httpsPort: Int?  // the plugin «https»: the page with its own certificate
    @State private var step = 0  // with HTTPS: 0 the certificate, 1 the page
    @State private var old = false  // an old device: the address instead of anyassistant.local

    var host: String { old ? server.address : "anyassistant.local" }
    var page: String { httpsPort.map { $0 == 443 ? "https://\(host)" : "https://\(host):\($0)" } ?? "http://\(host):\(server.port)" }
    var certificate: String { "http://\(host):\(server.port)/https/ca.crt" }
    /// What the QR opens: the page with the code, so it pairs by itself.
    var pageWithCode: String { code.map { "\(page)/?code=\($0)" } ?? page }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if waiting {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(T("Waiting for the server…")).foregroundStyle(.secondary)
                }
            }
            if httpsPort != nil {
                Picker("", selection: $step) {
                    Text(T("1. The certificate")).tag(0)
                    Text(T("2. The page")).tag(1)
                }
                .pickerStyle(.segmented).labelsHidden().frame(maxWidth: 320)
            }
            HStack(alignment: .top, spacing: 24) {
                qrCode(httpsPort != nil && step == 0 ? certificate : pageWithCode)
                VStack(alignment: .leading, spacing: 10) {
                    if httpsPort != nil && step == 0 {
                        Text(T("Install the certificate")).font(.title3.weight(.semibold))
                        Text(T("Once per device: scan it, or open this address, to download it."))
                        address(certificate)
                        Text(T("If it doesn't install by itself, on Android: Settings → Security → Install from storage → AnyAssistant.crt (as «VPN and apps»)."))
                            .foregroundStyle(.secondary)
                        Button(T("Done: the page")) { step = 1 }.padding(.top, 4)
                    } else {
                        Text(T("Open the page")).font(.title3.weight(.semibold))
                        Text(T("Scan it with the tablet or phone: it pairs by itself. Or open"))
                        address(page)
                        if let code {
                            Text(T("and type the code")).padding(.top, 4)
                            Text(code).font(.system(.largeTitle, design: .monospaced).weight(.semibold))
                                .textSelection(.enabled)
                            Text(T("Valid for 5 minutes, for one device.")).foregroundStyle(.secondary)
                            Button(T("Another code")) { Task { await ask() } }
                        } else if asked && pairingOff {
                            Text(T("No code needed: pairing is off.")).foregroundStyle(.secondary)
                        }
                    }
                }
                .font(.body)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer(minLength: 0)
            Toggle(T("An old device (it doesn't open .local names): use the address"), isOn: $old)
                .toggleStyle(.checkbox).foregroundStyle(.secondary)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task {
            waiting = true
            _ = await server.ready()
            httpsPort = await server.httpsPort()
            await ask()
            waiting = false
        }
    }

    func address(_ text: String) -> some View {
        Text(text).font(.system(.body, design: .monospaced)).textSelection(.enabled)
    }

    func ask() async {
        switch await server.pairingCode() {
        case .code(let found): code = found; pairingOff = false
        case .off: code = nil; pairingOff = true
        case .unreachable: code = nil; pairingOff = false
        }
        asked = true
    }

    @ViewBuilder func qrCode(_ text: String) -> some View {
        if let image = qr(text) {
            Image(nsImage: image).interpolation(.none).resizable().frame(width: 220, height: 220)
        }
    }

    func qr(_ text: String) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        let rep = NSCIImageRep(ciImage: output)
        let image = NSImage(size: rep.size)
        image.addRepresentation(rep)
        return image
    }
}

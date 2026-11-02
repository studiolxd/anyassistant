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
    @NSApplicationDelegateAdaptor private var delegate: Delegate

    var body: some Scene {
        // Not installed yet (nor using another server): no menu, only the installer's window.
        MenuBarExtra(isInserted: .constant(ready)) {
            MenuView(server: server, client: client)
        } label: {
            MenuBarIcon(symbol: icon)
        }
        Window("AnyAssistant", id: "face") {
            FaceWindow(client: client)
                .frame(minWidth: 320, minHeight: 400)
        }
        .defaultSize(width: 480, height: 640)
        Window(T("Settings"), id: "settings") {
            SettingsView()
                .frame(minWidth: 760, minHeight: 520)
        }
        Window(T("Devices"), id: "devices") {
            DevicesView()
                .frame(minWidth: 560, minHeight: 360)
        }
        Window(T("Themes"), id: "themes") {
            ThemesWindow()
                .frame(minWidth: 640, minHeight: 480)
        }
        .defaultSize(width: 1100, height: 780)
        .commands {
            CommandGroup(after: .toolbar) {  // View → Open in the Browser: the themes' page, for whoever edits one
                Button(T("Open Themes in the Browser")) { NSWorkspace.shared.open(ThemesWindow.page) }
            }
        }
        Window(T("Learn a voice"), id: "learn-voice") {
            LearnVoiceView()
                .frame(minWidth: 520, minHeight: 400)
        }
        .defaultSize(width: 560, height: 440)
        Window(T("Pair a device"), id: "pair") {
            PairView(server: server)
                .frame(minWidth: 680, minHeight: 440)
        }
        .defaultSize(width: 680, height: 500)
    }

    /// Installed, or using another server: the menu bar's.
    var ready: Bool {
        if client.role == .client { return true }
        if case .notInstalled = server.state { return false }
        return true
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
        followWindows()
        Task { @MainActor in
            let server = Server.shared
            let client = Client.shared
            defer { client.begin() }
            if client.role == .client { return }  // no server here: another Mac's
            if server.installed {
                server.launch()
            } else {
                server.state = .notInstalled
                Delegate.openSetup()
            }
        }
    }

    /// In the Dock (and ⌘⇥) while one of its windows is open; only in the menu bar otherwise.
    private func followWindows() {
        let center = NotificationCenter.default
        center.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
            MainActor.assumeIsolated { Client.shared.checkPermissions() }  // changed in System Settings
        }
        center.addObserver(forName: NSWindow.didBecomeKeyNotification, object: nil, queue: .main) { note in
            guard let window = note.object as? NSWindow, window.styleMask.contains(.titled) else { return }
            MainActor.assumeIsolated {
                if NSApp.activationPolicy() != .regular { NSApp.setActivationPolicy(.regular) }
                Client.shared.followFace()
            }
        }
        center.addObserver(forName: NSWindow.willCloseNotification, object: nil, queue: .main) { note in
            let closing = note.object as? NSWindow
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    let open = NSApp.windows.contains { $0 !== closing && $0.isVisible && $0.styleMask.contains(.titled) }
                    if !open { NSApp.setActivationPolicy(.accessory) }
                    Client.shared.followFace(closing: closing)
                }
            }
        }
    }

    /// Its icon in the Dock clicked with no window open: its face.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { MainActor.assumeIsolated { Delegate.show("face") } }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated {
            Client.shared.link.stop()
            if Client.shared.role == .server { Server.shared.stop() }
        }
        Thread.sleep(forTimeInterval: 1)
    }

    /// Opens one of the app's windows (a menu bar app has to bring itself forward). The icon in
    /// the menu bar opens it (it is there from the start, the menu only once clicked); asked before
    /// the icon is drawn (just launched), it opens it as soon as it is.
    @MainActor static var pending: String?
    @MainActor static var setupWindow: NSWindow?

    /// The installer: its own window (not a scene: before installing there is no menu to open it
    /// from). Closed before installing (nor using another server), the app quits: opening it
    /// again shows it again.
    @MainActor static func openSetup() {
        if Setup.shared.phase == .finished { Setup.shared.phase = .welcome }  // «Install steps again»
        if let window = setupWindow {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            return
        }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 520),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "AnyAssistant"
        window.titlebarAppearsTransparent = true
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: SetupView(setup: .shared, client: .shared) {
            window.close()
        }.frame(width: 520, height: 520))
        window.center()
        setupWindow = window
        NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: window, queue: .main) { _ in
            MainActor.assumeIsolated {
                setupWindow = nil
                if case .notInstalled = Server.shared.state, Client.shared.role != .client { NSApp.terminate(nil) }
            }
        }
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    @MainActor static func show(_ id: String) {
        NSApp.activate(ignoringOtherApps: true)
        pending = id
        NotificationCenter.default.post(name: .open, object: id)
    }
}

/// The icon in the menu bar; also what opens the windows asked for (Delegate.show).
struct MenuBarIcon: View {
    let symbol: String
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Image(systemName: symbol)
            .onAppear { openPending() }
            .onReceive(NotificationCenter.default.publisher(for: .open)) { _ in openPending() }
    }

    func openPending() {
        guard let id = Delegate.pending else { return }
        Delegate.pending = nil
        NSApp.activate(ignoringOtherApps: true)
        openWindow(id: id)
    }
}

extension Notification.Name {
    static let open = Notification.Name("AnyAssistantOpen")
}

// MARK: - The menu

/// A menu item's text: without the «…» (in the menu, an item says what it does, plainly).
func M(_ english: String) -> String {
    T(english).trimmingCharacters(in: CharacterSet(charactersIn: "…").union(.whitespaces))
}

struct MenuView: View {
    @ObservedObject var server: Server
    @ObservedObject var client: Client
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    @State private var login = SMAppService.mainApp.status == .enabled

    var body: some View {
        if client.role == .client { clientMenu } else { serverMenu }
    }

    /// A client of another Mac's server: its face and its microphone, nothing else here.
    @ViewBuilder var clientMenu: some View {
        Text(client.status)
        Divider()
        faceItem
        Toggle(T("Listen on this Mac"), isOn: $client.listening)
        if client.refused { Button(M("Allow the microphone…")) { client.openPrivacy() } }
            if client.cameraRefused { Button(M("Allow the camera…")) { client.openPrivacy("Privacy_Camera") } }
        Divider()
        Button(M("Run the server on this Mac…")) {
            client.useThisMac()
            if server.installed { server.launch() } else { Delegate.openSetup() }
        }
        loginToggle
        Divider()
        quit
    }

    /// «Show Eva», or «Hide Eva» while its window is open.
    @ViewBuilder var faceItem: some View {
        if client.faceShown {
            Button(String(format: T("Hide %@"), client.name)) { client.hideFace() }
        } else {
            Button(String(format: T("Show %@"), client.name)) { open("face") }
        }
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
    }

    @ViewBuilder var serverMenu: some View {
        Label(status, systemImage: statusSymbol)
        if server.state == .running {
            Divider()
            if server.devices.isEmpty {
                Text(T("No device connected"))
            }
            // Each connected one: its icon, name, room and LLM; a click opens Devices (rename it,
            // its room, its own LLM).
            ForEach(server.devices.prefix(5), id: \.id) { device in
                Button { open("devices") } label: {
                    Label([device.name.isEmpty ? T("a device") : device.name, device.room, llmName(device.llm)]
                            .filter { !$0.isEmpty }.joined(separator: " · "), systemImage: device.symbol)
                }
            }
            if server.devices.count > 5 {
                Button(String(format: T("and %d more"), server.devices.count - 5)) { open("devices") }
            }
        }
        if let busy = server.busy { Text(busy) }
        // The server, right under how it is: start it when stopped (or failed); while it starts,
        // only stop it; running, restart or stop.
        switch server.state {
        case .notInstalled: EmptyView()
        case .stopped, .failed: Button(T("Start")) { server.start() }
        case .starting: Button(T("Stop")) { server.stop() }
        case .running:
            Button(T("Restart")) { server.restart() }
            Button(T("Stop")) { server.stop() }
        }
        Divider()
        if server.state == .notInstalled {
            Button(M("Install…")) { Delegate.openSetup() }
        } else {
            faceItem
            Toggle(T("Listen on this Mac"), isOn: $client.listening)
            if client.refused { Button(M("Allow the microphone…")) { client.openPrivacy() } }
            if client.cameraRefused { Button(M("Allow the camera…")) { client.openPrivacy("Privacy_Camera") } }
            Button(M("Themes…")) { open("themes") }  // every state of each theme, to see them (the plugin «themes»)
            Divider()
            Button(M("Pair a device…")) { open("pair") }
            Button(M("Devices…")) { open("devices") }
            Divider()
            Button(T("Show the log")) {
                NSWorkspace.shared.open([server.log], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Console.app"),
                                        configuration: NSWorkspace.OpenConfiguration())
            }
            Button(M("Settings…")) { open("settings") }
                .keyboardShortcut(",")
            Button(M("Install steps again…")) { Delegate.openSetup() }
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
        case .running: T("Running")
        case .failed(let why): why
        }
    }

    /// How it is, at a glance (a menu draws its symbols in one colour).
    var statusSymbol: String {
        switch server.state {
        case .notInstalled: "arrow.down.circle"
        case .stopped: "stop.circle"
        case .starting: "hourglass"
        case .running: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
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
    var close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            switch setup.phase {
            case .welcome: welcome
            case .another:
                AnotherMacView(client: client, done: {
                    close()
                    Delegate.show("face")
                }, back: { setup.phase = .welcome })
            case .preparing: working(setup.note)
            case .questions: form
            case .installing, .finished: progress
            }
        }
        .padding(28)
    }

    var welcome: some View {
        VStack(spacing: 14) {
            Spacer(minLength: 8)
            Image(nsImage: NSApp.applicationIconImage)
                .resizable().frame(width: 112, height: 112)
            Text("AnyAssistant").font(.largeTitle.bold())
            Text(T("A voice assistant on this Mac, with an old phone or tablet as its eyes, mouth and ears."))
                .font(.title3).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button {
                Task { await setup.installWithDefaults() }
            } label: {
                Text(T("Install with what comes")).frame(maxWidth: 240)
            }
            .controlSize(.large).buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
            Button {
                Task { await setup.askQuestions() }
            } label: {
                Text(T("Set it up step by step")).frame(maxWidth: 240)
            }
            .controlSize(.large)
            Button(T("The server is on another Mac: use this one only to talk to it")) { setup.phase = .another }
                .buttonStyle(.link).padding(.top, 4)
            Spacer().frame(height: 6)
            Text(T("You can change everything later. The speech models download once (a few hundred MB)."))
                .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }

    func working(_ text: String) -> some View {
        VStack(spacing: 12) {
            Spacer()
            if setup.failed {
                Image(systemName: "exclamationmark.triangle.fill").font(.largeTitle).foregroundStyle(.orange)
            } else {
                ProgressView()
            }
            Text(text).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Spacer()
            if setup.failed {
                Button(T("Back")) { setup.failed = false; setup.phase = .welcome }
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
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
            HStack {
                Button(T("Back")) { setup.phase = .welcome }
                Spacer()
                Button(T("Install")) { Task { await setup.installWithAnswers() } }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
            }
        }
    }

    /// Installing: a bar and the steps as they go; finished: how it went at a glance, the steps as
    /// a summary (title, what it did) and the buttons together on the right, the main one blue.
    var progress: some View {
        let finished = setup.phase == .finished
        return VStack(spacing: 14) {
            VStack(spacing: 8) {
                if finished {
                    Image(systemName: setup.failed ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                        .font(.system(size: 46)).foregroundStyle(setup.failed ? .orange : .green)
                } else {
                    Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 64, height: 64)
                }
                Text(finished ? (setup.failed ? T("Installed, with problems") : T("Installed")) : T("Installing…"))
                    .font(.title2.bold())
                if finished && !setup.failed {
                    Text(T("AnyAssistant is now running on this device.")).foregroundStyle(.secondary)
                } else if !finished {
                    ProgressView(value: Double(setup.steps.filter { $0.status != .running }.count),
                                 total: Double(max(setup.total, setup.steps.count, 1)))
                        .frame(width: 280)
                }
            }
            ScrollViewReader { scroller in
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(setup.steps) { step in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                symbol(step.status).frame(width: 16)
                                Text(step.title)
                                Spacer(minLength: 12)
                                Text(step.text).foregroundStyle(step.status == .failed ? .red : .secondary)
                                    .lineLimit(1).truncationMode(.middle)
                            }
                            .font(.callout)
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .id(step.id)
                            if step.id != setup.steps.last?.id { Divider().padding(.leading, 38) }
                        }
                    }
                }
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
                .onChange(of: setup.steps.count) { _, _ in
                    if let last = setup.steps.last { scroller.scrollTo(last.id, anchor: .bottom) }
                }
            }
            if finished {
                HStack {
                    Spacer()
                    Button(T("Close"), action: close)
                    Button(T("Pair your tablet or phone")) {
                        close()
                        Delegate.show("pair")
                    }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                }
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

/// «Conectar otro dispositivo», as the admin page's section: one QR for everything (the server
/// itself by its address now, /connect with the code: the app pairs by itself, a browser goes on
/// to the page), the code big, and «Conectar a mano» folded (the app's choice, the browser's
/// addresses; the certificate first, for the browser only, with HTTPS). Plain layout, as the
/// other windows (no navigation: it breaks the title bar).
struct PairView: View {
    @ObservedObject var server: Server
    @Environment(\.dismissWindow) private var dismissWindow
    @State private var code: String?
    @State private var info: Server.Connecting?
    @State private var waiting = true  // until the server answers (it may be starting)
    @State private var manual = false

    /// What the QR says: /connect by the server's address, with the code if one is needed.
    var qrText: String {
        guard let info else { return "" }
        return code.map { "\(info.connect)?code=\($0)" } ?? info.connect
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text(T("Pair a device")).font(.title2.bold())
                    if waiting {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text(T("Waiting for the server…")).foregroundStyle(.secondary)
                        }
                    } else if let info {
                        HStack(alignment: .top, spacing: 24) {
                            qrCode(qrText, size: 200)
                            VStack(alignment: .leading, spacing: 16) {
                                Text(T("Scan the code with the device's camera. With the app installed, it connects by itself; otherwise, it goes on in the browser."))
                                if info.pairing {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(T("Pairing code")).font(.headline)
                                        if let code {
                                            Text(code).font(.system(size: 40, design: .monospaced).weight(.semibold))
                                                .textSelection(.enabled)
                                        } else {
                                            ProgressView().controlSize(.small).padding(.vertical, 12)
                                        }
                                        HStack(spacing: 4) {
                                            Text(T("Valid for 5 minutes") + " ·").foregroundStyle(.secondary)
                                            Button(T("Another code")) { Task { await ask() } }.buttonStyle(.link)
                                        }
                                    }
                                } else {
                                    Text(T("No code needed: pairing is off.")).foregroundStyle(.secondary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        DisclosureGroup(isExpanded: $manual) {
                            VStack(alignment: .leading, spacing: 14) {
                                step(T("App")) {
                                    Text(String(format: T("Choose «%@ on %@»"), info.name, info.computer)
                                         + (info.pairing ? " " + T("and type the code") : ""))
                                }
                                step(T("Browser")) {
                                    if let certificate = info.certificate {
                                        Text(T("First, install the certificate:"))
                                        HStack(alignment: .top, spacing: 12) {
                                            VStack(alignment: .leading, spacing: 4) {
                                                address(certificate)
                                                Text(T("If it doesn't install by itself, on Android: Settings → Security → Install from storage → AnyAssistant.crt (as «VPN and apps»)."))
                                                    .font(.callout).foregroundStyle(.secondary)
                                            }
                                            qrCode(certificate, size: 96)
                                        }
                                        Text(T("Then, open:")).padding(.top, 4)
                                    }
                                    address(info.local)
                                    Text(String(format: T("On old devices: %@"), "http://\(info.address):\(info.port)"))
                                        .font(.system(.callout, design: .monospaced)).foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                }
                            }
                            .padding(.top, 10)
                        } label: {
                            Text(T("Connect by hand")).font(.headline)
                        }
                    } else {
                        Text(T("The server isn't answering: is it running?")).foregroundStyle(.secondary)
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack {
                Spacer()
                Button(T("Done")) { dismissWindow(id: "pair") }.keyboardShortcut(.defaultAction)
            }
            .padding([.horizontal, .bottom], 20)
        }
        .task {
            waiting = true
            _ = await server.ready()
            await ask()
            info = await server.connecting() ?? fallback
            waiting = false
        }
    }

    /// Without the plugin «admin»: the same from what the app knows.
    var fallback: Server.Connecting? {
        guard code != nil || server.state == .running else { return nil }
        return Server.Connecting(name: "AnyAssistant", computer: Host.current().localizedName ?? "", port: server.port,
                                 address: server.address, connect: "http://\(server.address):\(server.port)/connect",
                                 local: "http://anyassistant.local:\(server.port)", certificate: nil, pairing: code != nil)
    }

    /// «App» / «Navegador»: a title and how, under «Conectar a mano».
    func step<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(title).font(.body.weight(.medium)).frame(width: 90, alignment: .leading)
            VStack(alignment: .leading, spacing: 6, content: content)
        }
    }

    func address(_ text: String) -> some View {
        Text(text).font(.system(.body, design: .monospaced)).textSelection(.enabled)
    }

    func ask() async {
        switch await server.pairingCode() {
        case .code(let found): code = found
        case .off, .unreachable: code = nil
        }
    }

    @ViewBuilder func qrCode(_ text: String, size: CGFloat) -> some View {
        if let image = qr(text) {
            Image(nsImage: image).interpolation(.none).resizable().frame(width: size, height: size)
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

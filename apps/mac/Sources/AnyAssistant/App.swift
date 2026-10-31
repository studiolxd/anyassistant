// AnyAssistant: in the menu bar. The first time, it installs the server (with what
// comes, or step by step); then it runs it, says how it is, and pairs devices.

import AppKit
import CoreImage.CIFilterBuiltins
import ServiceManagement
import SwiftUI

@main
struct AnyAssistantApp: App {
    @StateObject private var server = Server.shared
    @StateObject private var setup = Setup()
    @NSApplicationDelegateAdaptor private var delegate: Delegate

    var body: some Scene {
        MenuBarExtra {
            MenuView(server: server)
        } label: {
            Image(systemName: icon)
        }
        Window("AnyAssistant", id: "setup") {
            SetupView(setup: setup)
                .frame(width: 520, height: 480)
        }
        .windowResizability(.contentSize)
        Window(L("Pair a device", "Emparejar un dispositivo"), id: "pair") {
            PairView(server: server)
                .frame(width: 380, height: 460)
        }
        .windowResizability(.contentSize)
    }

    var icon: String {
        switch server.state {
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
            if server.installed {
                server.launch()
            } else {
                server.state = .notInstalled
                Delegate.show("setup")
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { Server.shared.stop() }
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
    @Environment(\.openWindow) private var openWindow
    @State private var login = SMAppService.mainApp.status == .enabled

    var body: some View {
        Text(status)
        if let busy = server.busy { Text(busy) }
        Divider()
        if server.state == .notInstalled {
            Button(L("Install…", "Instalar…")) { open("setup") }
        } else {
            Button(L("Open on this Mac", "Abrir en este Mac")) {
                NSWorkspace.shared.open(URL(string: "http://127.0.0.1:\(server.port)")!)
            }
            Button(L("Pair a device…", "Emparejar un dispositivo…")) { open("pair") }
            Divider()
            if server.state == .stopped {
                Button(L("Start", "Arrancar")) { server.start() }
            } else {
                Button(L("Restart", "Reiniciar")) { server.restart() }
                Button(L("Stop", "Parar")) { server.stop() }
            }
            Button(L("Show the log", "Ver el registro")) {
                NSWorkspace.shared.open([server.log], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Console.app"),
                                        configuration: NSWorkspace.OpenConfiguration())
            }
            Button(L("Settings and steps again…", "Ajustes y pasos de nuevo…")) { open("setup") }
            Toggle(L("Open at login", "Abrir al iniciar sesión"), isOn: $login)
                .onChange(of: login) { _, on in
                    if on { try? SMAppService.mainApp.register() } else { try? SMAppService.mainApp.unregister() }
                }
        }
        Divider()
        Button(L("Quit AnyAssistant", "Salir de AnyAssistant")) { NSApp.terminate(nil) }
            .keyboardShortcut("q")
            .onReceive(NotificationCenter.default.publisher(for: .open)) { note in
                if let id = note.object as? String { openWindow(id: id) }
            }
    }

    var status: String {
        switch server.state {
        case .notInstalled: L("Not installed yet", "Aún no está instalado")
        case .stopped: L("Stopped", "Parado")
        case .starting: L("Starting…", "Arrancando…")
        case .running: server.connected ? L("Running · a device connected", "En marcha · un dispositivo conectado")
                                         : L("Running · no device", "En marcha · ningún dispositivo")
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
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            switch setup.phase {
            case .welcome: welcome
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
            Text(L("A voice assistant on this Mac, with an old phone or tablet as its eyes, mouth and ears.",
                   "Un asistente de voz en este Mac, con un móvil o una tablet vieja como ojos, boca y oídos."))
                .foregroundStyle(.secondary)
            Spacer()
            Button {
                Task { await setup.installWithDefaults() }
            } label: {
                Label(L("Install with what comes", "Instalar con lo de serie"), systemImage: "bolt.fill")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large).buttonStyle(.borderedProminent)
            Button {
                Task { await setup.askQuestions() }
            } label: {
                Label(L("Set it up step by step", "Configurarlo paso a paso"), systemImage: "list.number")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large)
            Text(L("You can change everything later. The speech models download once (a few hundred MB).",
                   "Podrás cambiarlo todo después. Los modelos de voz se descargan una vez (unos cientos de MB)."))
                .font(.footnote).foregroundStyle(.secondary)
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
            Text(L("Step by step", "Paso a paso")).font(.title2.bold())
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
                Toggle(L("Open AnyAssistant at login", "Abrir AnyAssistant al iniciar sesión"), isOn: $setup.startAtLogin)
            }
            .formStyle(.grouped)
            Button(L("Install", "Instalar")) { Task { await setup.installWithAnswers() } }
                .buttonStyle(.borderedProminent).frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    var progress: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(setup.phase == .finished ? (setup.failed ? L("Installed, with problems", "Instalado, con problemas")
                                                          : L("Installed", "Instalado"))
                                          : L("Installing…", "Instalando…"))
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
                Button(L("Pair your tablet or phone", "Emparejar tu tablet o móvil")) {
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

struct PairView: View {
    @ObservedObject var server: Server
    @State private var code: String?
    @State private var asked = false

    var body: some View {
        VStack(spacing: 14) {
            Text(L("On the tablet or phone, open", "En la tablet o el móvil, abre")).foregroundStyle(.secondary)
            Text(server.url).font(.title2.monospaced()).textSelection(.enabled)
            if let image = qr(server.url) {
                Image(nsImage: image).interpolation(.none).resizable().frame(width: 200, height: 200)
            }
            if let code {
                Text(L("and type the code", "y escribe el código")).foregroundStyle(.secondary)
                Text(code).font(.system(size: 40, weight: .bold, design: .monospaced)).textSelection(.enabled)
                Text(L("Valid for 5 minutes, for one device.", "Vale 5 minutos, para un dispositivo."))
                    .font(.footnote).foregroundStyle(.secondary)
            } else if asked {
                Text(L("No code needed: pairing is off.", "No hace falta código: el emparejamiento está apagado."))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Button(L("Another code", "Otro código")) { Task { await ask() } }
        }
        .padding(24)
        .task { await ask() }
    }

    func ask() async {
        code = await server.pairingCode()
        asked = true
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

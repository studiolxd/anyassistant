// Pairing, once, as iOS's own Wi-Fi settings: the servers announcing themselves on this network
// (Bonjour) or «Other server…», then the pairing code («Conectar otro dispositivo» on the server
// shows it). A server that asks for no code connects at once. Back is the navigation bar's; the
// step's action, its top right; nothing but fields and rows in the content.

import SwiftUI

struct PairView: View {
    @ObservedObject var mac: Mac
    @StateObject private var browser = ServerBrowser()
    @State private var connecting: String?  // the server connecting without a code
    @State private var problem: String?

    var body: some View {
        NavigationView {
            List {
                Section {
                    if browser.servers.isEmpty {
                        HStack(spacing: 12) {
                            ProgressView()
                            Text(T("Searching…")).foregroundColor(.secondary)
                        }
                        .padding(.vertical, 6)
                    }
                    ForEach(browser.servers) { server in
                        if server.pairing {
                            NavigationLink {
                                CodeView(mac: mac, server: String(format: T("%@ on %@"), server.assistant, server.computer),
                                         host: server.address, port: server.port)
                            } label: { row(server) }
                        } else {
                            Button { connect(server) } label: { row(server) }
                        }
                    }
                } header: {
                    Text(T("Servers on this network"))
                } footer: {
                    Text(problem ?? T("AnyAssistant servers on this network are shown here."))
                        .foregroundColor(problem == nil ? .secondary : .red)
                }
                Section {
                    NavigationLink(T("Other server…")) { OtherServerView(mac: mac) }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle(T("Connect"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {  // from «Pair again»: back as it was
                    if mac.repairing { Button(T("Cancel")) { mac.cancelPairing() } }  // (a view's «if»: iOS 15 too)
                }
            }
        }
        .navigationViewStyle(.stack)
        .onAppear { browser.start() }
        .onDisappear { browser.stop() }
    }

    func row(_ server: ServerBrowser.Found) -> some View {
        HStack(spacing: 14) {
            Image(systemName: "server.rack").font(.title3).foregroundColor(.accentColor).frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(server.assistant).foregroundColor(.primary)
                Text(server.computer).font(.subheadline).foregroundColor(.secondary)
            }
            Spacer()
            if connecting == server.id { ProgressView() }
        }
        .padding(.vertical, 6)
    }

    /// Pairing is off on that server: nothing to type.
    func connect(_ server: ServerBrowser.Found) {
        mac.host = server.address
        mac.port = server.port
        mac.moved()
        connecting = server.id
        problem = nil
        Task {
            defer { connecting = nil }
            do { try await mac.pair(code: "") } catch {
                problem = T("The server isn't answering: is AnyAssistant running and this device on the same network?")
            }
        }
    }
}

/// «Other server…»: its host and port typed; «Next» finds out whether it asks for a code.
struct OtherServerView: View {
    @ObservedObject var mac: Mac
    @State private var checking = false
    @State private var problem: String?
    @State private var showCode = false

    var body: some View {
        Form {
            Section {
                ServerFields(mac: mac)
            } footer: {
                Text(problem ?? T("The name or IP address of the server."))
                    .foregroundColor(problem == nil ? .secondary : .red)
            }
        }
        .background(  // pushed by «Next», not a row of the form
            NavigationLink(isActive: $showCode) {
                CodeView(mac: mac, server: mac.host, host: mac.host, port: mac.port)
            } label: { EmptyView() }
            .hidden()
        )
        .navigationTitle(T("Other server"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if checking { ProgressView() } else {
                    Button(T("Next")) { Task { await next() } }
                        .disabled(mac.host.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }

    func next() async {
        checking = true
        problem = nil
        mac.moved()
        defer { checking = false }
        switch await mac.needsCode() {
        case .some(true): showCode = true
        case .some(false):
            do { try await mac.pair(code: "") } catch {
                problem = T("The server isn't answering: is AnyAssistant running and this device on the same network?")
            }
        case .none: problem = T("The server isn't answering: is AnyAssistant running and this device on the same network?")
        }
    }
}

/// The pairing code: six boxes, one per digit (the keyboard offers one from Messages too); it
/// pairs by itself with the sixth, and «Pair» (top right) tries again.
struct CodeView: View {
    @ObservedObject var mac: Mac
    let server: String  // «Eva on MacBook-Air-de-Suvi», or the host typed: never an IP it found
    let host: String
    let port: Int
    @State private var code = ""
    @State private var busy = false
    @State private var problem: String?
    @FocusState private var typing: Bool

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                VStack(spacing: 8) {
                    Text(T("Pairing code")).font(.title2.bold())
                    Text(server).foregroundColor(.secondary)
                }
                ZStack {
                    TextField("", text: $code)  // the real field, behind the boxes
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                        .focused($typing)
                        .opacity(0.01)
                        .onChange(of: code) { new in
                            code = String(new.filter(\.isNumber).prefix(6))
                            if code.count == 6 { pair() }
                        }
                    HStack(spacing: 10) {
                        ForEach(0..<6, id: \.self) { i in
                            Text(i < code.count ? String(Array(code)[i]) : "")
                                .font(.title.monospacedDigit().weight(.semibold))
                                .frame(width: 46, height: 58)
                                .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
                                .overlay(RoundedRectangle(cornerRadius: 12)
                                    .stroke(i == code.count && typing ? Color.accentColor : .clear, lineWidth: 2))
                        }
                    }
                    .onTapGesture { typing = true }
                }
                Text(problem ?? T("To get the code, open AnyAssistant on the server and select Connect another device."))
                    .font(.footnote)
                    .foregroundColor(problem == nil ? .secondary : .red)
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 24)
            .padding(.top, 32)
        }
        .navigationTitle(T("Pair"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if busy { ProgressView() } else {
                    Button(T("Pair"), action: pair).disabled(code.count != 6)
                }
            }
        }
        .onAppear {
            mac.host = host
            mac.port = port
            mac.moved()
            typing = true
        }
    }

    func pair() {
        guard !busy, code.count == 6 else { return }
        busy = true
        problem = nil
        Task {
            defer { busy = false }
            do {
                try await mac.pair(code: code)
            } catch Mac.Failure.wrongCode {
                problem = T("That code isn't right (or it expired).")
                code = ""
            } catch {
                problem = T("The server isn't answering: is AnyAssistant running and this device on the same network?")
            }
        }
    }
}

/// Where the server is: its host (a name or an IP) and its port, in a form's section.
struct ServerFields: View {
    @ObservedObject var mac: Mac

    var body: some View {
        HStack {
            Text(T("Host"))
            TextField("anyassistant.local", text: $mac.host)
                .multilineTextAlignment(.trailing).autocapitalization(.none).disableAutocorrection(true)
                .keyboardType(.URL)
        }
        HStack {
            Text(T("Port"))
            TextField("8080", value: $mac.port, format: .number.grouping(.never))
                .multilineTextAlignment(.trailing).keyboardType(.numberPad)
        }
    }
}

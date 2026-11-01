// Pairing, once, in two steps: the server (the ones announcing themselves on this network, by
// Bonjour; or its host typed by hand), then its 6-digit code («Conectar otro dispositivo» on the
// server shows it). A server that asks for no code connects at once.

import SwiftUI

struct PairView: View {
    @ObservedObject var mac: Mac
    @StateObject private var browser = ServerBrowser()
    @State private var step = Step.choose
    @State private var checking = false
    @State private var problem: String?

    enum Step: Equatable { case choose, manual, code(String) }  // code: the server's name, to show it

    var body: some View {
        NavigationView {
            Group {
                switch step {
                case .choose: choose
                case .manual: manual
                case .code(let server): CodeStep(mac: mac, server: server) { step = .choose }
                }
            }
            .navigationBarTitleDisplayMode(.inline)
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

    // MARK: Step 1: the server

    var choose: some View {
        Form {
            Section {
                if browser.servers.isEmpty {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text(T("Looking for servers on this network…")).foregroundColor(.secondary)
                    }
                }
                ForEach(browser.servers) { server in
                    Button { chosen(server) } label: {
                        HStack {
                            Image(systemName: "server.rack").foregroundColor(.accentColor)
                            VStack(alignment: .leading) {
                                Text(server.assistant).foregroundColor(.primary)
                                Text(server.computer).font(.caption).foregroundColor(.secondary)
                            }
                            Spacer()
                            if checking { ProgressView() } else { Image(systemName: "chevron.right").foregroundColor(.secondary) }
                        }
                    }
                    .disabled(checking)
                }
            } header: {
                Text(T("Choose your server"))
            } footer: {
                Text(problem ?? T("AnyAssistant running on a computer of this network shows up here."))
                    .foregroundColor(problem == nil ? .secondary : .red)
            }
            Section {
                Button(T("Type its host")) { problem = nil; step = .manual }
            }
        }
    }

    func chosen(_ server: ServerBrowser.Found) {
        mac.host = server.address
        mac.port = server.port
        if server.pairing {
            step = .code(server.computer)
        } else {
            connectWithoutCode()
        }
    }

    // MARK: Step 1, by hand

    var manual: some View {
        Form {
            ServerFields(mac: mac)
            Section {
                Button {
                    Task { await check() }
                } label: {
                    HStack {
                        Text(T("Continue"))
                        if checking { Spacer(); ProgressView() }
                    }
                }
                .disabled(checking || mac.host.trimmingCharacters(in: .whitespaces).isEmpty)
            } footer: {
                if let problem { Text(problem).foregroundColor(.red) }
            }
            Section {
                Button(T("Back")) { problem = nil; step = .choose }
            }
        }
    }

    /// Typed by hand: whether it answers, and whether it asks for a code.
    func check() async {
        checking = true
        problem = nil
        defer { checking = false }
        switch await mac.needsCode() {
        case .some(true): step = .code(mac.host)
        case .some(false): connectWithoutCode()
        case .none: problem = T("The server isn't answering: is AnyAssistant running, and this device on the same Wi-Fi?")
        }
    }

    /// Pairing is off on that server: nothing to type.
    func connectWithoutCode() {
        checking = true
        Task {
            defer { checking = false }
            do { try await mac.pair(code: "") } catch {
                problem = T("The server isn't answering: is AnyAssistant running, and this device on the same Wi-Fi?")
            }
        }
    }
}

// MARK: Step 2: the code

/// Six boxes, one per digit (the keyboard offers a code from Messages too); it pairs by itself
/// with the sixth, and «Pair» is there to try again.
struct CodeStep: View {
    @ObservedObject var mac: Mac
    let server: String
    let back: () -> Void
    @State private var code = ""
    @State private var busy = false
    @State private var problem: String?
    @FocusState private var typing: Bool

    var body: some View {
        VStack(spacing: 22) {
            VStack(spacing: 6) {
                Text(T("Code from the server")).font(.title2.bold())
                Text(server).foregroundColor(.secondary)
            }
            .padding(.top, 24)
            ZStack {
                TextField("", text: $code)  // the real field, hidden behind the boxes
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
                        let digit = i < code.count ? String(Array(code)[i]) : ""
                        Text(digit)
                            .font(.title.monospacedDigit().weight(.semibold))
                            .frame(width: 44, height: 56)
                            .background(RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground)))
                            .overlay(RoundedRectangle(cornerRadius: 10)
                                .stroke(i == code.count && typing ? Color.accentColor : .clear, lineWidth: 2))
                    }
                }
                .onTapGesture { typing = true }
            }
            Button(action: pair) {
                HStack {
                    if busy { ProgressView().tint(.white) }
                    Text(T("Pair")).bold()
                }
                .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .disabled(busy || code.count != 6)
            Text(problem ?? T("On the server, open AnyAssistant and choose «Connect another device»: it shows the code."))
                .font(.footnote)
                .foregroundColor(problem == nil ? .secondary : .red)
                .multilineTextAlignment(.center)
            Spacer()
            Button(T("Back"), action: back)
        }
        .padding(.horizontal, 24)
        .onAppear { typing = true }
    }

    func pair() {
        guard !busy else { return }
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
                problem = T("The server isn't answering: is AnyAssistant running, and this device on the same Wi-Fi?")
            }
        }
    }
}

/// Where the server is: its host (a name or an IP) and its port.
struct ServerFields: View {
    @ObservedObject var mac: Mac

    var body: some View {
        Section(T("Server")) {
            HStack {
                Text(T("Host"))
                TextField(T("anyassistant.local or 192.168.1.10"), text: $mac.host)
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
}

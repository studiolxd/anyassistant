// Pairing, once: the 6-digit code the Mac app shows («Pair a device…»). Its address can be
// changed first, if this device doesn't find anyassistant.local.

import SwiftUI

struct PairView: View {
    @ObservedObject var mac: Mac
    @State private var code = ""
    @State private var busy = false
    @State private var problem: String?
    @FocusState private var typing: Bool

    var body: some View {
        NavigationView {
            Form {
                ServerFields(mac: mac)  // first: where the server is, then its code
                Section {
                    TextField("123456", text: $code)
                        .keyboardType(.numberPad)
                        .font(.title2.monospacedDigit())
                        .focused($typing)
                        .onChange(of: code) { new in code = String(new.filter(\.isNumber).prefix(6)) }
                    Button(action: pair) {
                        HStack {
                            Text(T("Pair"))
                            if busy { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(busy || code.count != 6)
                } header: {
                    Text(T("Code from the server"))
                } footer: {
                    Text(problem ?? T("On the server, open AnyAssistant and choose «Connect another device»: it shows the code."))
                        .foregroundColor(problem == nil ? .secondary : .red)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {  // from «Pair again»: back as it was
                    if mac.repairing { Button(T("Cancel")) { mac.cancelPairing() } }  // (a view's «if»: iOS 15 too)
                }
            }
            .onAppear { typing = true }
        }
        .navigationViewStyle(.stack)
    }

    func pair() {
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

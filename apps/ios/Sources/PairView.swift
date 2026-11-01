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
                    Text(T("Code from your Mac"))
                } footer: {
                    Text(problem ?? T("On your Mac, open AnyAssistant's menu and choose «Pair a device…»: it shows the code."))
                        .foregroundColor(problem == nil ? .secondary : .red)
                }
                Section(T("Mac")) {
                    TextField(T("Address"), text: $mac.host).autocapitalization(.none).disableAutocorrection(true)
                    TextField(T("Port"), value: $mac.port, format: .number.grouping(.never)).keyboardType(.numberPad)
                }
            }
            .navigationTitle("AnyAssistant")
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
                problem = T("Your Mac isn't answering: is AnyAssistant running, and this device on the same Wi-Fi?")
            }
        }
    }
}

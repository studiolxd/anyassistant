// Pairing, once: the 6-digit code the Mac app shows («Pair a device…»), typed on a keypad. If the
// Mac doesn't ask for one (pairing off), any code goes. Its address can be changed first, if
// the watch doesn't find anyassistant.local.

import SwiftUI

struct PairView: View {
    @ObservedObject var mac: Mac
    @State private var code = ""
    @State private var busy = false
    @State private var problem: String?
    @State private var settings = false

    private let keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✓"]

    var body: some View {
        ScrollView {
            VStack(spacing: 6) {
                Text(T("Code from your Mac")).font(.footnote).foregroundStyle(.secondary)
                Text(code.isEmpty ? "······" : code).font(.title3.monospacedDigit())
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 3), spacing: 4) {
                    ForEach(keys, id: \.self) { key in
                        Button(key) { tap(key) }
                            .disabled(busy || (key == "✓" && code.count != 6))
                    }
                }
                if busy { ProgressView() }
                if let problem { Text(problem).font(.footnote).foregroundStyle(.red) }
                Button(T("Mac: ") + mac.host) { settings = true }.font(.footnote).buttonStyle(.borderless)
            }
        }
        .sheet(isPresented: $settings) { SettingsView(mac: mac) }
    }

    func tap(_ key: String) {
        switch key {
        case "⌫": code = String(code.dropLast())
        case "✓": pair()
        default: if code.count < 6 { code += key }
        }
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
                problem = T("Your Mac isn't answering: is AnyAssistant running, and the watch on the same network?")
            }
        }
    }
}

// Pairing, once: the 6-digit code the Mac app shows («Pair a device…»), typed on a keypad that
// fills the screen (as the Phone app's: no scrolling). If the server doesn't ask for one (pairing
// off), any code goes. Its address can be changed first (the gear), if the watch doesn't find
// anyassistant.local.

import SwiftUI

struct PairView: View {
    @ObservedObject var mac: Mac
    @State private var code = ""
    @State private var busy = false
    @State private var problem: String?
    @State private var settings = false

    private let keys = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["⌫", "0", "✓"]]

    var body: some View {
        NavigationStack {
            GeometryReader { geometry in
                let gap: CGFloat = 4
                let top: CGFloat = 26  // the code, or what went wrong
                let row = max((geometry.size.height - top - gap * 4) / 4, 20)
                VStack(spacing: gap) {
                    header.frame(height: top)
                    ForEach(keys, id: \.self) { line in
                        HStack(spacing: gap) {
                            ForEach(line, id: \.self) { key in
                                Button { tap(key) } label: { label(key) }
                                    .buttonStyle(Key(height: row, accent: key == "✓"))
                                    .disabled(busy || (key == "✓" && code.count != 6) || (key == "⌫" && code.isEmpty))
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, 2)
            .padding(.bottom, 4)
            .ignoresSafeArea(edges: .bottom)  // down to the screen's rounded edge
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { settings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel(T("Server"))
                }
            }
            .sheet(isPresented: $settings) { SettingsView(mac: mac) }
        }
    }

    @ViewBuilder private var header: some View {
        if let problem {
            Text(problem).font(.system(size: 11)).foregroundStyle(.red)
                .multilineTextAlignment(.center).lineLimit(2).minimumScaleFactor(0.7)
        } else if code.isEmpty {
            Text(T("Code from the server")).font(.footnote).foregroundStyle(.secondary)
                .lineLimit(1).minimumScaleFactor(0.7)
        } else {
            Text(code + String(repeating: "·", count: 6 - code.count))
                .font(.title3.monospacedDigit()).tracking(3)
        }
    }

    @ViewBuilder private func label(_ key: String) -> some View {
        switch key {
        case "⌫": Image(systemName: "delete.left")
        case "✓": if busy { ProgressView() } else { Image(systemName: "checkmark") }
        default: Text(key)
        }
    }

    func tap(_ key: String) {
        problem = nil
        switch key {
        case "⌫": code = String(code.dropLast())
        case "✓": pair()
        default: if code.count < 6 { code += key }
        }
    }

    func pair() {
        busy = true
        Task {
            defer { busy = false }
            do {
                try await mac.pair(code: code)
            } catch Mac.Failure.wrongCode {
                problem = T("That code isn't right (or it expired).")
                code = ""
            } catch {
                problem = T("The server isn't answering: is AnyAssistant running, and the watch on the same network?")
            }
        }
    }
}

/// A key: as tall as the screen allows, rounded, lighter while pressed.
private struct Key: ButtonStyle {
    let height: CGFloat
    let accent: Bool
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: min(height * 0.55, 22), weight: .medium, design: .rounded))
            .frame(maxWidth: .infinity)
            .frame(height: height)
            .background(RoundedRectangle(cornerRadius: height * 0.3)
                .fill(accent ? Color.accentColor : Color.gray.opacity(0.28))
                .opacity(configuration.isPressed ? 0.6 : 1))
            .opacity(enabled ? 1 : 0.35)
    }
}

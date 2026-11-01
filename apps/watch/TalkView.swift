// Press to talk: tap the button, say it, tap again (or it stops by itself after 15 s). What it
// heard and its answer stay on screen; the answer is also said aloud.

import SwiftUI
import WatchKit

struct TalkView: View {
    @ObservedObject var mac: Mac
    @StateObject private var voice = Voice()
    @State private var heard = ""
    @State private var answer = ""
    @State private var waiting = false
    @State private var problem: String?
    @State private var settings = false

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Button(action: press) {
                    ZStack {
                        Circle().fill(voice.recording ? Color.red : Color.accentColor).frame(width: 84, height: 84)
                        if waiting {
                            ProgressView()
                        } else {
                            Image(systemName: voice.recording ? "stop.fill" : "mic.fill").font(.title)
                        }
                    }
                }
                .buttonStyle(.plain)
                .disabled(waiting)
                Text(voice.recording ? T("Listening… tap to send") : waiting ? T("Thinking…") : T("Tap and talk"))
                    .font(.footnote).foregroundStyle(.secondary)
                if !heard.isEmpty { Text("«\(heard)»").font(.footnote).foregroundStyle(.secondary) }
                if !answer.isEmpty { Text(answer).font(.body) }
                if let problem { Text(problem).font(.footnote).foregroundStyle(.red) }
                Button(T("Settings")) { settings = true }.font(.footnote).buttonStyle(.borderless).padding(.top, 8)
            }
            .padding(.horizontal, 4)
        }
        .sheet(isPresented: $settings) { SettingsView(mac: mac) }
    }

    func press() {
        if voice.recording {
            guard let wav = voice.stop() else { return }
            send(wav)
            return
        }
        Task {
            guard await voice.allowed() else { problem = T("It needs the microphone (Settings → Privacy)."); return }
            do {
                try voice.start()
                problem = nil
                WKInterfaceDevice.current().play(.start)
            } catch {
                problem = error.localizedDescription
            }
        }
    }

    func send(_ wav: Data) {
        waiting = true
        WKInterfaceDevice.current().play(.click)
        Task {
            defer { waiting = false }
            do {
                let found = try await mac.talk(wav)
                heard = found.heard
                answer = found.answer
                voice.play(found.audio)
                if found.heard.isEmpty && found.answer.isEmpty { problem = T("It didn't catch that.") }
            } catch Mac.Failure.unreachable {
                problem = T("The server isn't answering: is AnyAssistant running, and the watch on the same network?")
            } catch Mac.Failure.wrongCode {
                problem = T("It has to be paired again.")
            } catch {
                problem = "\(error)"
            }
        }
    }
}

struct SettingsView: View {
    @ObservedObject var mac: Mac
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section(T("Server")) {
                TextField(T("Address"), text: $mac.host)
                TextField(T("Port"), value: $mac.port, format: .number.grouping(.never))
            }
            Button(T("Pair again"), role: .destructive) {
                mac.unpair()
                dismiss()
            }
        }
    }
}

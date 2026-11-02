// The face, alone: Eyes' eyes and mouth on black, nothing else. While you look at it, it listens:
// say something and it hears (its eyes grow with your voice), thinks, and answers aloud (its
// mouth moves); then it listens again. Wrist down, it sleeps and the microphone is closed. A tap,
// or a double tap of your fingers (watchOS 11), does what matters now: it stops talking, forgets
// the question it is thinking about, or sends what it hears without waiting for the quiet. Holding
// the face opens its settings (its server, and what went wrong, if something did: then the face
// is sad and the watch taps your wrist). While it thinks and
// speaks it stays on, wrist down too (Staying), so the answer is heard to its end.
// «-demo <look>» (a launch argument): that face, still, without the microphone (the simulator's
// can't be opened; and to see each face).

import SwiftUI
import WatchKit

struct TalkView: View {
    @ObservedObject var mac: Mac
    @StateObject private var voice = Voice()
    @Environment(\.scenePhase) private var phase
    @Environment(\.isLuminanceReduced) private var dimmed
    @State private var waiting = false
    @State private var problem: String?
    @State private var settings = false
    @State private var staying = Staying()
    @State private var asking: Task<Void, Never>?
    @State private var held = false  // holding the face opened the settings: that touch is no tap
    private let demo = UserDefaults.standard.string(forKey: "demo")

    /// In front, lit, and not in its settings: it may listen.
    private var awake: Bool { phase == .active && !dimmed && !settings }

    private var look: String {
        if let demo { return demo }
        if waiting { return "thinking" }
        if voice.playing { return "speaking" }  // wrist down too: it is still saying it
        if !awake { return "asleep" }
        if voice.hearing { return "hearing" }
        return problem != nil ? "error" : "awake"
    }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            // The face as large as it fits: 62 v × 45 v at rest, up to 83 v wide (eyes grown by
            // the voice heard, or looking aside) and 50 v high (floating, looking up).
            let v = min(size.width * 0.94 / 83, size.height * 0.85 / 50)
            Button(action: tap) {
                EyesFace(look: look, accent: Color(red: 0x34 / 255, green: 0xaf / 255, blue: 0xf7 / 255),
                         voice: demo != nil ? 1 : voice.voice, speech: demo != nil ? 0.7 : voice.speech, v: v)
                    .frame(width: size.width, height: size.height)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .modifier(DoubleTap())
            .simultaneousGesture(LongPressGesture(minimumDuration: 0.8).onEnded { _ in
                held = true
                settings = true
            })
        }
        .background(Color.black)
        .ignoresSafeArea()
        .persistentSystemOverlays(.hidden)
        .sheet(isPresented: $settings) { SettingsView(mac: mac, problem: problem) }
        .onAppear {
            voice.heard = { send($0) }
            update()
        }
        .onChange(of: awake) { update() }
        .onChange(of: settings) { _, open in if !open { held = false } }
        .onChange(of: waiting) { update(); stay() }
        .onChange(of: voice.playing) { update(); stay() }
        .onChange(of: voice.hearing) { _, now in if now { problem = nil } }
    }

    /// The microphone open while it may listen and has nothing else to do; closed otherwise.
    private func update() {
        guard demo == nil, awake, !waiting, !voice.playing else {
            voice.close()
            return
        }
        Task {
            guard await voice.allowed() else {
                fail(T("It needs the microphone (Settings → Privacy)."))
                return
            }
            guard awake, !waiting, !voice.playing else { return }
            do {
                try voice.listen()
            } catch {
                fail(error.localizedDescription)
            }
        }
    }

    /// On while it thinks or speaks; then as any app (wrist down: the clock).
    private func stay() {
        if waiting || voice.playing { staying.begin() } else { staying.end() }
    }

    private func tap() {
        if held { return }
        if voice.playing {
            voice.stopPlaying()
        } else if waiting {
            asking?.cancel()  // forgotten: its answer, if it comes, isn't said
            asking = nil
            waiting = false
            WKInterfaceDevice.current().play(.directionDown)
        } else if voice.hearing {
            voice.finish()
        } else if problem != nil {
            problem = nil
            update()
        }
    }

    private func send(_ wav: Data) {
        waiting = true
        WKInterfaceDevice.current().play(.click)
        asking = Task {
            defer {  // after the answer starts: the microphone stays closed meanwhile
                if !Task.isCancelled { waiting = false }
            }
            do {
                let found = try await mac.talk(wav)
                if let timers = found.timers { Upcoming.keep(timers) }  // «pon un temporizador»: on the face at once
                guard !Task.isCancelled else { return }
                voice.play(found.audio)  // nothing heard, nothing said: it listens again
            } catch where Task.isCancelled {
                return
            } catch Mac.Failure.unreachable {
                fail(T("The server isn't answering: is AnyAssistant running, and the watch on the same network?"))
            } catch Mac.Failure.wrongCode {
                fail(T("It has to be paired again."))
            } catch {
                fail("\(error)")
            }
        }
    }

    private func fail(_ why: String) {
        problem = why
        WKInterfaceDevice.current().play(.failure)
    }
}

/// A double tap of the fingers (watchOS 11 and later, Series 9 and later) presses the face.
private struct DoubleTap: ViewModifier {
    func body(content: Content) -> some View {
        if #available(watchOS 11.0, *) {
            content.handGestureShortcut(.primaryAction)
        } else {
            content
        }
    }
}

struct SettingsView: View {
    @ObservedObject var mac: Mac
    var problem: String? = nil

    var body: some View {
        Form {
            if let problem {
                Section { Text(problem).font(.footnote).foregroundStyle(.red) }
            }
            Section(T("Server")) {
                Text("\(mac.host):\(String(mac.port))").font(.footnote)
                Text(T("Paired as the iPhone is.")).font(.footnote).foregroundStyle(.secondary)
            }
        }
    }
}

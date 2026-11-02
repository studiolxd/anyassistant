// AnyAssistant on the Apple Watch: Eyes' face, listening while you look at it. Each sentence goes
// to your server (POST /talk, the plugin «talk-api»), which answers in voice, as on any other device: its own
// conversation, your voice checked, «dile a la cocina…». Paired as its iPhone is (Companion):
// nothing to type here. What is next (timers, alarms, reminders) for the complication: asked when
// it opens and now and then in the background (GET /timers), and with each answer.

import SwiftUI
import WatchKit

@main
struct AnyAssistantApp: App {
    @StateObject private var mac = Mac(agent: "AnyAssistant Watch")
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            Group {
                if mac.paired {
                    TalkView(mac: mac)
                } else {
                    Unpaired()
                }
            }
            .onAppear { Companion.shared.start(mac) }
        }
        .onChange(of: phase) { _, now in
            if now == .active { Task { await AnyAssistantApp.refresh() } }
        }
        .backgroundTask(.appRefresh("timers")) {
            await AnyAssistantApp.refresh()
        }
    }

    /// What is next, from the server (paired only); and again in a while, in the background.
    @MainActor static func refresh() async {
        let mac = Mac(agent: "AnyAssistant Watch")
        if mac.paired, let timers = await mac.timers(), Upcoming.keep(timers) { Companion.shared.pass(timers) }
        WKApplication.shared().scheduleBackgroundRefresh(withPreferredDate: Date().addingTimeInterval(15 * 60),
                                                         userInfo: "timers" as NSString) { _ in }
    }
}

/// Not paired: the iPhone's app isn't (or hasn't said so yet). Asleep, and what to do.
struct Unpaired: View {
    var body: some View {
        GeometryReader { geometry in
            let v = min(geometry.size.width * 0.94 / 83, geometry.size.height * 0.85 / 50)
            VStack(spacing: 6 * v) {
                EyesFace(look: "asleep", accent: Color(red: 0x34 / 255, green: 0xaf / 255, blue: 0xf7 / 255),
                         voice: 0, speech: 0, v: v * 0.8)
                    .frame(height: 36 * v)
                Text(T("Pair AnyAssistant on the iPhone.")).font(.footnote).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .background(Color.black)
        .ignoresSafeArea()
    }
}

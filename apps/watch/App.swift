// AnyAssistant on the Apple Watch: Eyes' face, listening while you look at it. Each sentence goes
// to your server (POST /talk, the plugin «talk-api»), which answers in voice, as on any other device: its own
// conversation, your voice checked, «dile a la cocina…». Paired once with the 6-digit code the
// Mac app shows («Pair a device…»).

import SwiftUI

@main
struct AnyAssistantApp: App {
    @StateObject private var mac = Mac(agent: "AnyAssistant Watch")

    var body: some Scene {
        WindowGroup {
            if mac.paired {
                TalkView(mac: mac)
            } else {
                PairView(mac: mac)
            }
        }
    }
}

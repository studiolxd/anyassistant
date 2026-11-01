// AnyAssistant on the Apple Watch: press to talk. The sentence goes to your Mac (POST /talk, the
// plugin «talk-api»), which answers in text and voice, as on any other device: its own
// conversation, your voice checked, «dile a la cocina…». Paired once with the 6-digit code the
// Mac app shows («Pair a device…»).

import SwiftUI

@main
struct AnyAssistantApp: App {
    @StateObject private var mac = Mac()

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

/// A text in the watch's language (Resources/<lang>.lproj/Localizable.strings; the English is the key).
func T(_ key: String) -> String { NSLocalizedString(key, comment: "") }

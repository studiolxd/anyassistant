// The app's own updates (Sparkle): once a day it looks at the latest release's appcast.xml
// (apps/release.sh makes it, signed with the key in this Mac's Keychain: see docs/versiones) and,
// if there is a newer version, shows it with its notes and «Instalar actualización»: one click, it
// downloads, installs and opens the new one (which updates the server it carries, as on any launch).
// Nothing is installed by itself. «Buscar actualizaciones…» in the menu looks now. Only in the
// built app (its Info.plist has the feed and the key); not while developing with swift run.

import Foundation
import Sparkle

@MainActor
final class AppUpdates: ObservableObject {
    static let shared = AppUpdates()
    private var controller: SPUStandardUpdaterController?

    /// Whether this app can update itself (the built one).
    var available: Bool { controller != nil }

    func begin() {
        guard controller == nil, Bundle.main.object(forInfoDictionaryKey: "SUPublicEDKey") != nil else { return }
        controller = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
    }

    func check() {
        controller?.checkForUpdates(nil)
    }
}

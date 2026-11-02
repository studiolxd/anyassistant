// The apps' texts (Resources/<lang>.lproj/Localizable.strings of each app; the English is the key),
// in the interface's language: the app's setting «Idioma de la interfaz» (Automático: the device's
// system language). Not the language the assistant speaks, which is the server's.
//
// The iPhone, iPad and Mac apps keep their choice on the server too, for this device (its page and
// the face's texts, /config, follow it there; the Mac's Devices can change it): Link.configure keeps
// both in step. The watch follows its own system's language (the iPhone's, unless set apart).

import Foundation

enum Interface {
    static let key = "ui_language"
    /// The languages the apps have texts in.
    static let languages = ["en", "es"]

    /// «auto», «es», «en».
    static var chosen: String {
        let found = UserDefaults.standard.string(forKey: key) ?? "auto"
        return languages.contains(found) ? found : "auto"
    }

    /// The language it is in now: the chosen one, or the system's among the app's.
    static var code: String {
        chosen != "auto" ? chosen : (Bundle.main.preferredLocalizations.first.flatMap { languages.contains($0) ? $0 : nil } ?? "en")
    }

    /// A choice made here that the server doesn't have yet (it was unreachable): it is sent first next time.
    static var unsaved: Bool {
        get { UserDefaults.standard.bool(forKey: key + "_unsaved") }
        set { UserDefaults.standard.set(newValue, forKey: key + "_unsaved") }
    }

    /// Chooses it (here: from the app's settings, unsaved until the server has it; or from the server).
    static func choose(_ code: String, fromServer: Bool = false) {
        UserDefaults.standard.set(languages.contains(code) ? code : "auto", forKey: key)
        if !fromServer { unsaved = true }
        bundle = load()
        NotificationCenter.default.post(name: changed, object: nil)
    }

    static let changed = Notification.Name("interfaceLanguage")

    /// The chosen language's texts (its .lproj), or the system's choice (the main bundle).
    static var bundle: Bundle = load()

    private static func load() -> Bundle {
        guard chosen != "auto", let path = Bundle.main.path(forResource: chosen, ofType: "lproj"),
              let found = Bundle(path: path) else { return .main }
        return found
    }
}

func T(_ key: String) -> String { NSLocalizedString(key, bundle: Interface.bundle, comment: "") }

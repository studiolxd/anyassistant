// Updates of what came from the community (the plugin «community»): the server looks for them once
// a day; the app shows a notification once per new version («There's an update of Bedside
// (1.1.0)»), and an item in its menu while they wait. A click opens where to install them: the
// Themes window's «From the community» tab, or Settings → Plugins → From the community. Nothing is
// installed by itself.

import AppKit
import Foundation
import UserNotifications

struct CommunityUpdate: Equatable {
    let kind: String  // "theme" or "plugin"
    let id: String
    let name: String
    let to: String
}

@MainActor
final class CommunityUpdates: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = CommunityUpdates()

    @Published var pending: [CommunityUpdate] = []  // the ones waiting: the menu's item
    private var poll: Timer?
    private let seenKey = "communityNotice"  // the last notice shown (its number)

    /// Asks the server every minute (cheap: it doesn't read the catalog then, only says what it
    /// found, once a day; and what you install meanwhile leaves the menu).
    func begin() {
        guard poll == nil else { return }
        UNUserNotificationCenter.current().delegate = self
        poll = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            Task { @MainActor in await CommunityUpdates.shared.check() }
        }
        Task { await check() }
    }

    func check() async {
        let server = Server.shared
        guard Client.shared.role != .client, server.state == .running else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/community/updates")!)
        request.timeoutInterval = 5
        guard let (raw, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            pending = []  // the plugin is off, or the server doesn't answer
            return
        }
        pending = Self.parse(answer["updates"])
        guard let notice = answer["notice"] as? [String: Any], let number = notice["id"] as? Int else { return }
        let defaults = UserDefaults.standard
        guard number > defaults.integer(forKey: seenKey) else { return }
        defaults.set(number, forKey: seenKey)
        let new = Self.parse(notice["updates"])
        if !new.isEmpty { await notify(new) }
    }

    static func parse(_ raw: Any?) -> [CommunityUpdate] {
        (raw as? [[String: Any]] ?? []).map {
            CommunityUpdate(kind: $0["kind"] as? String ?? "", id: $0["id"] as? String ?? "",
                            name: $0["name"] as? String ?? "", to: $0["to"] as? String ?? "")
        }
    }

    /// «There's an update of Bedside (1.1.0)», or «There are updates of 2 themes and plugins».
    static func sentence(_ updates: [CommunityUpdate]) -> String {
        if updates.count == 1, let one = updates.first {
            return String(format: T("There's an update of %@ (%@)"), one.name, one.to)
        }
        return String(format: T("There are updates of %d themes and plugins"), updates.count)
    }

    private func notify(_ updates: [CommunityUpdate]) async {
        let center = UNUserNotificationCenter.current()
        guard (try? await center.requestAuthorization(options: [.alert, .sound])) == true else { return }
        let content = UNMutableNotificationContent()
        content.title = Self.sentence(updates)
        content.userInfo = ["where": Self.place(updates)]
        try? await center.add(UNNotificationRequest(identifier: "community-updates", content: content, trigger: nil))
    }

    /// Where to install them: the Themes window if they are all themes; else Settings → Plugins.
    static func place(_ updates: [CommunityUpdate]) -> String {
        updates.allSatisfy { $0.kind == "theme" } ? "themes" : "plugins"
    }

    /// Opens where to install them.
    static func open(_ place: String) {
        if place == "themes" {
            ThemesWindow.showCommunity()
        } else {
            SettingsView.showCommunity()
        }
    }

    // Shown also while the app is in front; a click opens where to install.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler done: @escaping () -> Void) {
        let place = response.notification.request.content.userInfo["where"] as? String ?? "plugins"
        Task { @MainActor in CommunityUpdates.open(place) }
        done()
    }
}

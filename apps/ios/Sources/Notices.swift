// The phone's own notifications. Alarms, timers and reminders are scheduled on it as the Mac
// tells them (they ring even with the app closed; on iOS 26 or later they are alarms: Alarms); while it is in the background, its answers
// and messages from other rooms appear as notifications too. With the app open, the Mac's
// voice says them: no notification.

import UserNotifications

@MainActor
final class Notices: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notices()
    var foreground = true
    private let center = UNUserNotificationCenter.current()
    private let prefix = "anyassistant-"

    func start() {
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    func handle(_ message: [String: Any]) {
        switch message["type"] as? String {
        case "timers":
            let items = message["items"] as? [[String: Any]] ?? []
            if #available(iOS 26.0, *) {
                Task {  // the phone's own alarms; notifications only if it doesn't let it
                    if await Alarms.shared.set(items) { self.schedule([]) } else { self.schedule(items) }
                }
            } else {
                schedule(items)
            }
        case "text":
            guard !foreground, message["author"] as? String == "assistant", message["partial"] as? Bool != true,
                  let text = message["text"] as? String, !text.isEmpty else { return }
            let content = UNMutableNotificationContent()
            content.title = "AnyAssistant"
            content.body = text
            content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        default:
            break
        }
    }

    /// The Mac's running timers, alarms and reminders, as the phone's own (again each time they change).
    private func schedule(_ items: [[String: Any]]) {
        center.getPendingNotificationRequests { [prefix, center] pending in
            center.removePendingNotificationRequests(withIdentifiers: pending.map(\.identifier).filter { $0.hasPrefix(prefix) })
            let now = Date().timeIntervalSince1970
            for item in items {
                guard let at = item["at"] as? Double, at > now + 1 else { continue }
                let kind = item["kind"] as? String ?? "timer"
                let content = UNMutableNotificationContent()
                content.title = T(kind == "alarm" ? "Alarm" : kind == "reminder" ? "Reminder" : "Timer")
                content.body = item["label"] as? String ?? ""
                content.sound = .default
                content.interruptionLevel = .timeSensitive
                let trigger = UNTimeIntervalNotificationTrigger(timeInterval: at - now, repeats: false)
                center.add(UNNotificationRequest(identifier: "\(prefix)\(kind)-\(Int(at))", content: content, trigger: trigger))
            }
        }
    }

    // With the app open, the Mac says it: the notification isn't shown.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        Task { @MainActor in completionHandler(self.foreground ? [] : [.banner, .sound]) }
    }
}

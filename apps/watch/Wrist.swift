// The notices the watch missed (the agenda's, «dile al reloj…»: the server keeps them, since the
// watch never stays connected), shown on the wrist as notifications, with its tap: asked for when
// the app opens and now and then in the background (GET /notices), and with each answer.

import UserNotifications

final class Wrist: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Wrist()
    private let center = UNUserNotificationCenter.current()

    func start() {
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func show(_ notices: [String]) {
        for text in notices where !text.isEmpty {
            let content = UNMutableNotificationContent()
            content.title = "AnyAssistant"
            content.body = text
            content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }

    /// With the app open too: it wasn't said.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

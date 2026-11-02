// The phone's own notifications. Alarms, timers and reminders are scheduled on it as the Mac
// tells them (they ring even with the app closed; on iOS 26 or later alarms and timers are the
// phone's alarms: Alarms). Alarms and timers ring with the theme's alarm (the Mac's /alarm.wav,
// kept in Library/Sounds); reminders are plain notifications. While it is in the background, its
// answers and messages from other rooms appear as notifications too. With the app open, the
// Mac's voice says them: no notification.

import UserNotifications

@MainActor
final class Notices: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Notices()
    var foreground = true
    var name = "AnyAssistant"  // the assistant's (the Mac's settings), for its notifications
    private let center = UNUserNotificationCenter.current()
    private let prefix = "anyassistant-"

    func start() {
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    /// The theme's alarm, as a sound the phone can ring with (in Library/Sounds): its name, once fetched
    /// (kept: the app woken by the watch, without a connection yet, rings with it too).
    private(set) var alarmSound: String? = UserDefaults.standard.string(forKey: "alarmSound") {
        didSet { UserDefaults.standard.set(alarmSound, forKey: "alarmSound") }
    }

    /// Fetches the theme's alarm from the Mac (/alarm.wav: as it rings there, under 30 s) into
    /// Library/Sounds, where notifications and alarms find it by name. Again when the theme changes.
    func fetchAlarmSound(from base: URL, theme: String, session: URLSession) async {
        var parts = URLComponents(url: base.appendingPathComponent("alarm.wav"), resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "theme", value: theme)]
        guard let (data, response) = try? await session.data(from: parts.url!),
              (response as? HTTPURLResponse)?.statusCode == 200, data.count > 44,
              let library = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first else { return }
        let folder = library.appendingPathComponent("Sounds")
        let name = "anyassistant-alarm-\(theme).wav"
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appendingPathComponent(name)
        if (try? Data(contentsOf: file)) != data { try? data.write(to: file, options: .atomic) }
        if alarmSound != name {  // what is already set rings with it from now on
            alarmSound = name
            if let timers { handle(timers) }
        }
    }
    private var timers: [String: Any]?  // the last «timers», to set them again with a new sound

    func handle(_ message: [String: Any]) {
        switch message["type"] as? String {
        case "timers":
            timers = message
            let items = message["items"] as? [[String: Any]] ?? []
            let reminders = items.filter { $0["kind"] as? String == "reminder" }  // plain notifications
            let ringing = items.filter { $0["kind"] as? String != "reminder" }
            if #available(iOS 26.0, *) {
                Task {  // the phone's own alarms; notifications only if it doesn't let it
                    if await Alarms.shared.set(ringing, sound: self.alarmSound) { self.schedule(reminders) } else { self.schedule(items) }
                }
            } else {
                schedule(items)
            }
        case "text":
            guard !foreground, message["author"] as? String == "assistant", message["partial"] as? Bool != true,
                  let text = message["text"] as? String, !text.isEmpty else { return }
            let content = UNMutableNotificationContent()
            content.title = name
            content.body = text
            content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        default:
            break
        }
    }

    /// The Mac's running timers, alarms and reminders, as the phone's own (again each time they change).
    private func schedule(_ items: [[String: Any]]) {
        let sound = alarmSound
        center.getPendingNotificationRequests { [prefix, center] pending in
            center.removePendingNotificationRequests(withIdentifiers: pending.map(\.identifier).filter { $0.hasPrefix(prefix) })
            let now = Date().timeIntervalSince1970
            for item in items {
                guard let at = item["at"] as? Double, at > now + 1 else { continue }
                let kind = item["kind"] as? String ?? "timer"
                let content = UNMutableNotificationContent()
                content.title = T(kind == "alarm" ? "Alarm" : kind == "reminder" ? "Reminder" : "Timer")
                content.body = item["label"] as? String ?? ""
                if kind == "reminder" {  // a plain notification
                    content.sound = .default
                } else {  // it rings with the theme's alarm, through Focus
                    content.sound = sound.map { UNNotificationSound(named: UNNotificationSoundName($0)) } ?? .default
                    content.interruptionLevel = .timeSensitive
                }
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

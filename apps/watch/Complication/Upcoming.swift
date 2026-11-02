// The timers, alarms and reminders to come, as the server last said (its «timers»: after each
// sentence, when the app opens, now and then in the background, and from the iPhone when they
// change). Kept where the app and its complication both see them: an App Group.

import Foundation
import WidgetKit

struct Upcoming: Equatable {
    let kind: String  // timer, alarm, reminder
    let at: Date
    let label: String
    let set: Date?  // a timer: when it was set (how much of it is left)

    static let group = "group.com.anyassistant"
    private static var store: UserDefaults? { UserDefaults(suiteName: group) }

    var icon: String { kind == "timer" ? "timer" : kind == "alarm" ? "alarm.fill" : "bell.fill" }

    /// What it is: its label («Pasta»), or its kind's name.
    var title: String {
        if label.isEmpty {
            return NSLocalizedString(kind == "timer" ? "Timer" : kind == "alarm" ? "Alarm" : "Reminder", comment: "")
        }
        return label.prefix(1).uppercased() + label.dropFirst()
    }

    /// The server's items, kept; the complication is told if they changed.
    static func keep(_ items: [[String: Any]]) {
        let clean: [[String: Any]] = items.compactMap { item in
            guard let at = (item["at"] as? NSNumber)?.doubleValue else { return nil }
            var found: [String: Any] = ["kind": item["kind"] as? String ?? "timer", "at": at,
                                        "label": item["label"] as? String ?? ""]
            if let set = (item["set"] as? NSNumber)?.doubleValue { found["set"] = set }
            return found
        }
        let before = store?.array(forKey: "timers") as NSArray?
        guard before == nil || !before!.isEqual(to: clean) else { return }
        store?.set(clean, forKey: "timers")
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Those to come, soonest first.
    static func all(after now: Date = Date()) -> [Upcoming] {
        let items = store?.array(forKey: "timers") as? [[String: Any]] ?? []
        return items.compactMap { item -> Upcoming? in
            guard let at = (item["at"] as? NSNumber)?.doubleValue else { return nil }
            return Upcoming(kind: item["kind"] as? String ?? "timer", at: Date(timeIntervalSince1970: at),
                            label: item["label"] as? String ?? "",
                            set: (item["set"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) })
        }
        .filter { $0.at > now }
        .sorted { $0.at < $1.at }
    }
}

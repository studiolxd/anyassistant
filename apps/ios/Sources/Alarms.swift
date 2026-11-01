// On iOS 26 or later, the Mac's alarms, timers and reminders are the phone's own alarms
// (AlarmKit): they ring like the Clock's, even on silent, full screen, with the app closed.
// Stopped on the phone, the Mac stops ringing too (a tap, as on its face); stopped on the Mac
// («para»), it goes from the phone. Before iOS 26 they are notifications (Notices).

import Foundation

extension Notification.Name {
    /// An alarm stopped on the phone: the Mac stops ringing too.
    static let stopRinging = Notification.Name("stopRinging")
}

#if !targetEnvironment(macCatalyst)  // no AlarmKit on the Mac: notifications there
import AlarmKit
import AppIntents
import SwiftUI

@available(iOS 26.0, *)
struct Ringing: AlarmMetadata {}

@available(iOS 26.0, *)
@MainActor
final class Alarms {
    static let shared = Alarms()
    private let manager = AlarmManager.shared
    private let key = "alarms"  // «<kind>-<at>» → the alarm's id

    /// Whether the phone lets it set alarms (asked once).
    func allowed() async -> Bool {
        switch manager.authorizationState {
        case .authorized: return true
        case .denied: return false
        default: return (try? await manager.requestAuthorization()) == .authorized
        }
    }

    /// The Mac's running timers, alarms and reminders, as the phone's (each time they change).
    func set(_ items: [[String: Any]]) async -> Bool {
        guard await allowed() else { return false }
        var known = UserDefaults.standard.dictionary(forKey: key) as? [String: String] ?? [:]
        let now = Date().timeIntervalSince1970
        var wanted: [String: (Double, String, String)] = [:]
        for item in items {
            guard let at = item["at"] as? Double, at > now + 1 else { continue }
            let kind = item["kind"] as? String ?? "timer"
            wanted["\(kind)-\(Int(at))"] = (at, kind, item["label"] as? String ?? "")
        }
        for (name, id) in known where wanted[name] == nil {  // stopped, done or removed on the Mac
            if let uuid = UUID(uuidString: id) { try? manager.cancel(id: uuid) }
            known[name] = nil
        }
        for (name, (at, kind, label)) in wanted where known[name] == nil {
            let id = UUID()
            let title = T(kind == "alarm" ? "Alarm" : kind == "reminder" ? "Reminder" : "Timer") + (label.isEmpty ? "" : " · " + label)
            let alert: AlarmPresentation.Alert
            if #available(iOS 26.1, *) {
                alert = AlarmPresentation.Alert(title: LocalizedStringResource(stringLiteral: title))
            } else {
                alert = AlarmPresentation.Alert(title: LocalizedStringResource(stringLiteral: title),
                                                stopButton: AlarmButton(text: LocalizedStringResource(stringLiteral: T("Stop")),
                                                                        textColor: .white, systemImageName: "stop.circle"))
            }
            let attributes = AlarmAttributes<Ringing>(presentation: AlarmPresentation(alert: alert), tintColor: .blue)
            let configuration = AlarmManager.AlarmConfiguration.alarm(
                schedule: .fixed(Date(timeIntervalSince1970: at)), attributes: attributes, stopIntent: StopRinging())
            if (try? await manager.schedule(id: id, configuration: configuration)) != nil {
                known[name] = id.uuidString
            }
        }
        UserDefaults.standard.set(known, forKey: key)
        return true
    }
}

/// The alarm's «Stop» on the phone.
@available(iOS 26.0, *)
struct StopRinging: LiveActivityIntent {
    static var title: LocalizedStringResource = "Stop"
    static var isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        NotificationCenter.default.post(name: .stopRinging, object: nil)
        return .result()
    }
}

#endif

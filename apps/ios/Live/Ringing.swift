// What the phone's alarms (AlarmKit: Alarms.swift) carry, for their Live Activity (LiveTimer.swift):
// shared by the app and its widget.

import AlarmKit

@available(iOS 26.0, *)
struct Ringing: AlarmMetadata {
    /// What it is: «Temporizador · Pasta», «Alarma».
    var title: String = ""
}

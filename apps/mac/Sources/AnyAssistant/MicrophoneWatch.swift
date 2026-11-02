// Who else is recording on this Mac, asked of CoreAudio (macOS 14 or later): the system keeps an
// object per process with audio (kAudioHardwarePropertyProcessObjectList) that says whether it has
// an input stream running, its PID and its bundle ID. No permission: they're properties of the HAL.
// Apple's own daemons (Siri, CoreSpeech, Control Center…) turn the input on all the time: every
// com.apple.* is left out but the apps a person calls or records with (FaceTime, QuickTime, Voice
// Memos, Safari, Messages); a process without a bundle ID counts as a person's. Never from the
// audio thread (reading properties may block): a timer twice a second, and the condition has to
// hold a while before it counts (busy a second to pause, free two seconds to resume): a change of
// a moment is normal. The result goes to Link.pause (why «microphone», the app's name) and resume.

import AppKit
import CoreAudio

@MainActor
final class MicrophoneWatch {
    /// Apple's apps a person records or calls with: they count, the rest of com.apple.* doesn't.
    static let people: Set<String> = ["com.apple.FaceTime", "com.apple.QuickTimePlayerX", "com.apple.VoiceMemos",
                                      "com.apple.Safari", "com.apple.MobileSMS", "com.apple.iChat"]
    static let every: TimeInterval = 0.5
    static let busyAfter: TimeInterval = 1.0
    static let freeAfter: TimeInterval = 2.0

    struct Recorder {
        let pid: pid_t
        let bundle: String

        /// The app's name as the Finder shows it («Zoom»), or its bundle's last word, or nothing.
        var name: String {
            if let app = NSRunningApplication(processIdentifier: pid), let found = app.localizedName, !found.isEmpty { return found }
            return bundle.split(separator: ".").last.map(String.init) ?? ""
        }
    }

    /// Another app has been recording for a second (its name, maybe empty), or none has for two (nil).
    var onChange: ((String?) -> Void)?
    private(set) var busy = false
    private var since: Date?  // when the state last differed from what was reported
    private var timer: Timer?

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: MicrophoneWatch.every, repeats: true) { _ in
            MainActor.assumeIsolated { self.tick() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        since = nil
        if busy {
            busy = false
            onChange?(nil)
        }
    }

    private func tick() {
        let others = MicrophoneWatch.recording()
        let now = Date()
        guard others.isEmpty == busy else {  // as reported: nothing to count
            since = nil
            return
        }
        let start = since ?? now
        since = start
        if now.timeIntervalSince(start) >= (busy ? MicrophoneWatch.freeAfter : MicrophoneWatch.busyAfter) {
            busy = !others.isEmpty
            since = nil
            onChange?(busy ? others[0].name : nil)
        }
    }

    /// Whether a process is a person's (not one of Apple's daemons), by its bundle ID.
    static func isPerson(_ bundle: String) -> Bool {
        bundle.isEmpty || !bundle.hasPrefix("com.apple.") || people.contains(bundle)
    }

    /// The other processes recording right now (ours and Apple's daemons left out).
    static func recording() -> [Recorder] {
        let me = getpid()
        return processes().compactMap { object in
            guard uint32(object, kAudioProcessPropertyIsRunningInput) == 1 else { return nil }
            let pid = pid_t(int32(object, kAudioProcessPropertyPID))
            guard pid != me, pid > 0 else { return nil }
            let bundle = string(object, kAudioProcessPropertyBundleID)
            return isPerson(bundle) ? Recorder(pid: pid, bundle: bundle) : nil
        }
    }

    private static func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    }

    private static func processes() -> [AudioObjectID] {
        var where_ = address(kAudioHardwarePropertyProcessObjectList)
        let system = AudioObjectID(kAudioObjectSystemObject)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(system, &where_, 0, nil, &size) == noErr, size > 0 else { return [] }
        var objects = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        guard AudioObjectGetPropertyData(system, &where_, 0, nil, &size, &objects) == noErr else { return [] }
        return Array(objects.prefix(Int(size) / MemoryLayout<AudioObjectID>.size))
    }

    private static func uint32(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32 {
        var where_ = address(selector)
        var value: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        return AudioObjectGetPropertyData(object, &where_, 0, nil, &size, &value) == noErr ? value : 0
    }

    private static func int32(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> Int32 {
        var where_ = address(selector)
        var value: Int32 = 0
        var size = UInt32(MemoryLayout<Int32>.size)
        return AudioObjectGetPropertyData(object, &where_, 0, nil, &size, &value) == noErr ? value : 0
    }

    private static func string(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
        var where_ = address(selector)
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(object, &where_, 0, nil, &size, &value) == noErr, let value else { return "" }
        return value.takeRetainedValue() as String
    }
}

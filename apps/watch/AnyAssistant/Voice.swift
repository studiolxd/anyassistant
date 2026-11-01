// The watch's microphone and speaker: a sentence as a 16 kHz mono WAV, and the answer played.

import AVFoundation

@MainActor
final class Voice: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var recording = false
    @Published var playing = false
    private var recorder: AVAudioRecorder?
    private var player: AVAudioPlayer?
    private let file = FileManager.default.temporaryDirectory.appending(path: "sentence.wav")

    func allowed() async -> Bool {
        await AVAudioApplication.requestRecordPermission()
    }

    func start() throws {
        stopPlaying()
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.playAndRecord, mode: .default)
        try audio.setActive(true)
        let settings: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000,
                                       AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                                       AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false]
        recorder = try AVAudioRecorder(url: file, settings: settings)
        recorder?.record(forDuration: 15)  // a sentence; at most 15 s
        recording = true
    }

    /// The sentence, as a WAV (nil if it was too short to be one).
    func stop() -> Data? {
        let seconds = recorder?.currentTime ?? 0
        recorder?.stop()
        recording = false
        guard seconds > 0.4 else { return nil }
        return try? Data(contentsOf: file)
    }

    func play(_ wav: Data) {
        guard !wav.isEmpty, let found = try? AVAudioPlayer(data: wav) else { return }
        player = found
        found.delegate = self
        playing = found.play()
    }

    func stopPlaying() {
        player?.stop()
        playing = false
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.playing = false }
    }
}

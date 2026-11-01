// The microphone and the speaker: what it hears goes to the Mac as 16-bit mono PCM at 48 kHz
// (in small pieces), and what the Mac says, the same, is played in order. iOS's voice
// processing cancels the echo of its own voice, so it can hear you while it talks. It keeps
// going with the screen off (the app's background mode «audio»).

import AVFoundation

final class Audio {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let playing = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false)!
    private let wire = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 48000, channels: 1, interleaved: true)!
    private var converter: AVAudioConverter?
    private var mono: AVAudioFormat?
    private(set) var running = false
    /// The audio was cut off (a call, headphones plugged in…): it has to start again.
    var onRestartNeeded: (() -> Void)?
    /// How loud its own voice is now (0…1), for the face; about 20 times a second.
    var onSpeech: ((Float) -> Void)?

    init() {
        engine.attach(player)
        let center = NotificationCenter.default
        #if os(iOS)
        center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            let kind = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt).flatMap(AVAudioSession.InterruptionType.init)
            if kind == .ended { self?.onRestartNeeded?() }
        }
        #endif
        center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            self?.onRestartNeeded?()
        }
    }

    func start(heard: @escaping (Data, Float) -> Void) throws {
        guard !running else { return }
        #if os(macOS)  // without it, the engine waits for an answer on the main thread: asked first (Eva.swift)
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            throw NSError(domain: "Audio", code: 1, userInfo: [NSLocalizedDescriptionKey: "not allowed"])
        }
        #endif
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetooth])
        try session.setActive(true)
        #endif
        // The player wired first: on the Mac, voice processing fails to start its output otherwise.
        engine.connect(player, to: engine.mainMixerNode, format: playing)
        let input = engine.inputNode
        if !input.isVoiceProcessingEnabled { try input.setVoiceProcessingEnabled(true) }
        let format = input.outputFormat(forBus: 0)
        // With voice processing the Mac gives several channels: the first is your voice, cleaned.
        mono = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: format.sampleRate, channels: 1, interleaved: false)
        converter = mono.flatMap { AVAudioConverter(from: $0, to: wire) }
        input.installTap(onBus: 0, bufferSize: 960, format: format) { [weak self] buffer, _ in
            if let (pcm, level) = self?.convert(buffer) { heard(pcm, level) }
        }
        let mixer = engine.mainMixerNode
        mixer.installTap(onBus: 0, bufferSize: 2048, format: mixer.outputFormat(forBus: 0)) { [weak self] buffer, _ in
            guard let samples = buffer.floatChannelData?[0] else { return }
            var peak: Float = 0
            for i in 0..<Int(buffer.frameLength) { peak = max(peak, abs(samples[i])) }
            self?.onSpeech?(min(1, peak))
        }
        engine.prepare()
        try engine.start()
        player.play()
        running = true
    }

    func stop() {
        guard running else { return }
        running = false
        engine.inputNode.removeTap(onBus: 0)
        engine.mainMixerNode.removeTap(onBus: 0)
        onSpeech?(0)
        player.stop()
        engine.stop()
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    /// Its voice: 16-bit mono PCM at 48 kHz, after what is already queued.
    func play(_ pcm: Data) {
        let count = pcm.count / 2
        guard running, count > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: playing, frameCapacity: AVAudioFrameCount(count)),
              let target = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(count)
        pcm.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for i in 0..<count { target[i] = Float(samples[i]) / 32768 }
        }
        player.scheduleBuffer(buffer)
        if !player.isPlaying { player.play() }
    }

    /// Interrupted: what was left to say isn't said.
    func hush() {
        guard running else { return }
        player.stop()
        player.play()
    }

    /// The microphone's piece as the Mac wants it, and its loudest sample (0…1, for the face).
    private func convert(_ whole: AVAudioPCMBuffer) -> (Data, Float)? {
        guard let converter, let mono, let first = whole.floatChannelData?[0],
              let buffer = AVAudioPCMBuffer(pcmFormat: mono, frameCapacity: whole.frameLength),
              let target = buffer.floatChannelData?[0] else { return nil }
        buffer.frameLength = whole.frameLength
        target.update(from: first, count: Int(whole.frameLength))  // only the first channel
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * 48000 / buffer.format.sampleRate) + 32
        guard let output = AVAudioPCMBuffer(pcmFormat: wire, frameCapacity: capacity) else { return nil }
        var given = false
        var error: NSError?
        converter.convert(to: output, error: &error) { _, status in
            if given {
                status.pointee = .noDataNow
                return nil
            }
            given = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, output.frameLength > 0, let samples = output.int16ChannelData?[0] else { return nil }
        let count = Int(output.frameLength)
        var peak: Int32 = 0
        for i in 0..<count { peak = max(peak, abs(Int32(samples[i]))) }
        return (Data(bytes: samples, count: count * 2), Float(peak) / 32768)
    }
}

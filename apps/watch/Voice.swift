// The watch's microphone and speaker. While the app is in front, the microphone is open and it
// finds the sentences itself: one starts when the sound rises well above the room's, and ends after
// a moment of quiet (or 15 s); each goes out as a 16 kHz mono WAV (heard). While it sends one and
// while the answer is said, the microphone is closed (it doesn't hear itself); then it listens again.
// The voice heard and the voice said, 0…1, for the face.

import AVFoundation

@MainActor
final class Voice: NSObject, ObservableObject, AVAudioPlayerDelegate {
    /// The microphone is open.
    @Published private(set) var listening = false
    /// Within a sentence.
    @Published private(set) var hearing = false
    /// The answer is being said.
    @Published private(set) var playing = false
    @Published private(set) var voice: CGFloat = 0
    @Published private(set) var speech: CGFloat = 0
    /// A sentence heard, as a WAV.
    var heard: (Data) -> Void = { _ in }

    private let engine = AVAudioEngine()
    private var player: AVAudioPlayer?
    private var meter: Timer?

    // Finding the sentences (dBFS and seconds).
    private var rate: Double = 16000
    private var room: Float = -50  // the room's level, followed slowly while nobody speaks
    private var before: [Float] = []  // the last moments before a sentence (its first syllable)
    private var sentence: [Float] = []
    private var loud: Double = 0  // how long it has been loud within the sentence
    private var quiet: Double = 0  // how long it has been quiet since it was last loud
    private static let rise: Float = 14  // this much above the room starts a sentence
    private static let floor: Float = -48  // and never quieter than this
    private static let pause = 0.8  // this much quiet ends it
    private static let longest = 15.0
    private static let shortest = 0.25  // loud for less: a knock, not a sentence
    private static let lead = 0.3  // kept from before it started

    func allowed() async -> Bool {
        await AVAudioApplication.requestRecordPermission()
    }

    /// Opens the microphone (it was closed, or the answer ended).
    func listen() throws {
        guard !listening else { return }
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.playAndRecord, mode: .default)
        try audio.setActive(true)
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        rate = format.sampleRate
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            guard let channel = buffer.floatChannelData?[0] else { return }
            let samples = Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
            Task { @MainActor in self?.take(samples) }
        }
        engine.prepare()
        try engine.start()
        reset()
        listening = true
    }

    /// Closes the microphone; what was being heard is dropped.
    func close() {
        guard listening else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        listening = false
        hearing = false
        voice = 0
        reset()
    }

    /// Ends the sentence being heard now, without waiting for the quiet.
    func finish() {
        guard hearing else { return }
        end()
    }

    private func reset() {
        before = []
        sentence = []
        loud = 0
        quiet = 0
    }

    private func take(_ samples: [Float]) {
        guard listening, !samples.isEmpty else { return }
        let seconds = Double(samples.count) / rate
        let power = samples.reduce(Float(0)) { $0 + $1 * $1 } / Float(samples.count)
        let level = 10 * log10(max(power, 1e-10))
        voice = CGFloat(min(max((level - room) / 30, 0), 1))
        let threshold = max(room + Voice.rise, Voice.floor)
        if !hearing {
            room += (level < room ? 0.3 : 0.02) * (level - room)  // down fast, up slowly
            before += samples
            let keep = Int(Voice.lead * rate)
            if before.count > keep { before.removeFirst(before.count - keep) }
            if level > threshold {
                hearing = true
                sentence = before
                before = []
                loud = seconds
                quiet = 0
            }
            return
        }
        sentence += samples
        if level > threshold - 4 {
            loud += seconds
            quiet = 0
        } else {
            quiet += seconds
        }
        if quiet >= Voice.pause || Double(sentence.count) / rate >= Voice.longest { end() }
    }

    private func end() {
        let found = sentence, long = loud
        hearing = false
        reset()
        guard long >= Voice.shortest else { return }  // a knock: listening still
        close()
        heard(Voice.wav(found, rate: rate))
    }

    /// 16 kHz, 16 bits, mono (each output sample, the mean of the input's it covers).
    private static func wav(_ samples: [Float], rate: Double) -> Data {
        let out = 16000.0
        let step = rate / out
        let count = Int(Double(samples.count) / step)
        var pcm = Data(capacity: count * 2 + 44)
        func put<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { pcm.append(contentsOf: $0) } }
        pcm.append(contentsOf: Array("RIFF".utf8)); put(UInt32(36 + count * 2))
        pcm.append(contentsOf: Array("WAVEfmt ".utf8)); put(UInt32(16)); put(UInt16(1)); put(UInt16(1))
        put(UInt32(out)); put(UInt32(out * 2)); put(UInt16(2)); put(UInt16(16))
        pcm.append(contentsOf: Array("data".utf8)); put(UInt32(count * 2))
        for i in 0..<count {
            let from = Int(Double(i) * step), to = max(from + 1, min(Int(Double(i + 1) * step), samples.count))
            var sum: Float = 0
            for j in from..<to { sum += samples[j] }
            let value = max(-1, min(1, sum / Float(to - from)))
            put(Int16(value * 32767))
        }
        return pcm
    }

    // MARK: The answer

    /// Says the answer (false: there was none to say).
    @discardableResult
    func play(_ wav: Data) -> Bool {
        guard !wav.isEmpty, let found = try? AVAudioPlayer(data: wav) else { return false }
        player = found
        found.delegate = self
        found.isMeteringEnabled = true
        playing = found.play()
        if playing {
            meter = Timer.scheduledTimer(withTimeInterval: 1 / 20, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.measure() }
            }
        }
        return playing
    }

    func stopPlaying() {
        player?.stop()
        done()
    }

    private func measure() {
        guard let player, playing else { return }
        player.updateMeters()
        speech = CGFloat(min(max((player.averagePower(forChannel: 0) + 40) / 40, 0), 1))
    }

    private func done() {
        meter?.invalidate()
        meter = nil
        playing = false
        speech = 0
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.done() }
    }
}

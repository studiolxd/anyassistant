// Bridge between Python and AVSpeechSynthesizer: the voice stays loaded and each
// sentence takes ~50 ms (with `say`, which starts every time, ~600 ms).
//
// Reads JSON commands from stdin, one per line:
//   {"text": "...", "voice": "Mónica", "language": "es-ES", "rate": 180}
// and answers one line per command:
//   {"sample_rate": 22050, "audio": "<float32 mono in base64>"}   or   {"error": "..."}
//
// Built by the tts/avspeech.py plugin the first time (swiftc).

import AVFoundation

func emit(_ data: [String: Any]) {
    let json = try! JSONSerialization.data(withJSONObject: data)
    FileHandle.standardOutput.write(json + Data("\n".utf8))
}

let synthesizer = AVSpeechSynthesizer()
var voices: [String: AVSpeechSynthesisVoice] = [:]

/// By name ("Mónica") or identifier; among several, the one for `language` with the best quality.
func voice(_ name: String, language: String) -> AVSpeechSynthesisVoice? {
    let key = "\(name)|\(language)"
    if let cached = voices[key] { return cached }
    let candidates = AVSpeechSynthesisVoice.speechVoices()
        .filter { $0.name == name || $0.identifier == name }
        .sorted {
            ($0.language == language ? 1 : 0, $0.quality.rawValue)
                > ($1.language == language ? 1 : 0, $1.quality.rawValue)
        }
    voices[key] = candidates.first
    return candidates.first
}

func synthesize(_ text: String, voice: AVSpeechSynthesisVoice?, rate: Double?) async -> (Double, [Float]) {
    let utterance = AVSpeechUtterance(string: text)
    utterance.voice = voice
    if let rate {
        // ~180 words per minute is AVSpeech's normal rate.
        let value = AVSpeechUtteranceDefaultSpeechRate * Float(rate / 180)
        utterance.rate = min(max(value, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
    }
    return await withCheckedContinuation { continuation in
        var samples: [Float] = []
        var sampleRate = 22050.0
        var finished = false
        synthesizer.write(utterance) { buffer in
            guard let pcm = buffer as? AVAudioPCMBuffer, !finished else { return }
            if pcm.frameLength == 0 {  // an empty buffer marks the end
                finished = true
                continuation.resume(returning: (sampleRate, samples))
                return
            }
            sampleRate = pcm.format.sampleRate
            if let data = pcm.floatChannelData {
                samples += UnsafeBufferPointer(start: data[0], count: Int(pcm.frameLength))
            } else if let data = pcm.int16ChannelData {
                samples += UnsafeBufferPointer(start: data[0], count: Int(pcm.frameLength))
                    .map { Float($0) / 32768 }
            }
        }
    }
}

while let line = readLine() {
    guard let data = line.data(using: .utf8),
        let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
        let text = command["text"] as? String
    else { continue }
    let name = command["voice"] as? String ?? "Samantha"
    guard let chosen = voice(name, language: command["language"] as? String ?? "en-US") else {
        emit(["error": "no voice called \(name)"])
        continue
    }
    let (sampleRate, samples) = await synthesize(text, voice: chosen, rate: command["rate"] as? Double)
    let bytes = samples.withUnsafeBufferPointer { Data(buffer: $0) }
    emit(["sample_rate": sampleRate, "audio": bytes.base64EncodedString()])
}

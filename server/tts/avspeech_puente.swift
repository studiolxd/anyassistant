// Puente entre Python y AVSpeechSynthesizer: la voz se queda cargada y cada
// frase tarda ~50 ms (con `say`, que arranca cada vez, ~600 ms).
//
// Lee órdenes JSON por stdin, una por línea:
//   {"texto": "...", "voz": "Mónica", "velocidad": 180}
// y responde una línea por orden:
//   {"tasa": 22050, "audio": "<float32 mono en base64>"}   o   {"error": "..."}
//
// Lo compila el plugin tts/avspeech.py la primera vez (swiftc).

import AVFoundation

func emitir(_ datos: [String: Any]) {
    let json = try! JSONSerialization.data(withJSONObject: datos)
    FileHandle.standardOutput.write(json + Data("\n".utf8))
}

let sintetizador = AVSpeechSynthesizer()
var voces: [String: AVSpeechSynthesisVoice] = [:]

/// Por nombre ("Mónica") o identificador; entre varias, la de España y la de más calidad.
func voz(_ nombre: String) -> AVSpeechSynthesisVoice? {
    if let guardada = voces[nombre] { return guardada }
    let candidatas = AVSpeechSynthesisVoice.speechVoices()
        .filter { $0.name == nombre || $0.identifier == nombre }
        .sorted {
            ($0.language == "es-ES" ? 1 : 0, $0.quality.rawValue)
                > ($1.language == "es-ES" ? 1 : 0, $1.quality.rawValue)
        }
    voces[nombre] = candidatas.first
    return candidatas.first
}

func sintetizar(_ texto: String, voz: AVSpeechSynthesisVoice?, velocidad: Double?) async -> (Double, [Float]) {
    let frase = AVSpeechUtterance(string: texto)
    frase.voice = voz
    if let velocidad {
        // ~180 palabras por minuto es la velocidad normal de AVSpeech.
        let tasa = AVSpeechUtteranceDefaultSpeechRate * Float(velocidad / 180)
        frase.rate = min(max(tasa, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
    }
    return await withCheckedContinuation { continuacion in
        var muestras: [Float] = []
        var tasa = 22050.0
        var terminado = false
        sintetizador.write(frase) { buffer in
            guard let pcm = buffer as? AVAudioPCMBuffer, !terminado else { return }
            if pcm.frameLength == 0 {  // un búfer vacío marca el final
                terminado = true
                continuacion.resume(returning: (tasa, muestras))
                return
            }
            tasa = pcm.format.sampleRate
            if let datos = pcm.floatChannelData {
                muestras += UnsafeBufferPointer(start: datos[0], count: Int(pcm.frameLength))
            } else if let datos = pcm.int16ChannelData {
                muestras += UnsafeBufferPointer(start: datos[0], count: Int(pcm.frameLength))
                    .map { Float($0) / 32768 }
            }
        }
    }
}

while let linea = readLine() {
    guard let datos = linea.data(using: .utf8),
        let orden = try? JSONSerialization.jsonObject(with: datos) as? [String: Any],
        let texto = orden["texto"] as? String
    else { continue }
    let nombre = orden["voz"] as? String ?? "Mónica"
    guard let elegida = voz(nombre) else {
        emitir(["error": "no existe la voz \(nombre)"])
        continue
    }
    let (tasa, muestras) = await sintetizar(texto, voz: elegida, velocidad: orden["velocidad"] as? Double)
    let bytes = muestras.withUnsafeBufferPointer { Data(buffer: $0) }
    emitir(["tasa": tasa, "audio": bytes.base64EncodedString()])
}

// Puente entre Python y el modelo de Apple (Foundation Models, en el Mac).
//
// Lee órdenes JSON por stdin, una por línea:
//   {"tipo": "nueva", "instrucciones": "..."}   empieza una conversación
//   {"tipo": "preguntar", "texto": "...", "ahora": "..."}   responde en streaming
// y escribe por stdout, una por línea:
//   {"delta": "..."} ... {"fin": true}   o   {"error": "..."}
//
// Lo compila el plugin llm/apple.py la primera vez (swiftc).

import Foundation
import FoundationModels

func emitir(_ datos: [String: Any]) {
    let json = try! JSONSerialization.data(withJSONObject: datos)
    FileHandle.standardOutput.write(json + Data("\n".utf8))
}

var instrucciones = ""
var sesion = LanguageModelSession()
nonisolated(unsafe) var ahora = ""  // fecha y hora habladas, las manda Python

/// El modelo la consulta solo si le preguntan por la fecha o la hora; si se
/// le da en el prompt, la repite en todas las respuestas.
struct FechaHora: Tool {
    let name = "fechaHora"
    let description = "Devuelve la fecha y la hora actuales."

    @Generable
    struct Arguments {}

    func call(arguments: Arguments) async throws -> String {
        ahora
    }
}

@MainActor
func nuevaSesion() {
    sesion = LanguageModelSession(tools: [FechaHora()], instructions: instrucciones)
    sesion.prewarm()
}

@MainActor
func preguntar(_ texto: String, reintento: Bool = false) async {
    var previo = ""
    // GenerationError está marcado como obsoleto en macOS 27, pero sigue siendo
    // lo que lanza streamResponse; por él se distinguen estos dos casos.
    do {
        for try await parcial in sesion.streamResponse(to: texto) {
            let actual = parcial.content
            // Cada instantánea trae el texto acumulado; se envía solo lo nuevo.
            if actual.hasPrefix(previo), actual.count > previo.count {
                emitir(["delta": String(actual.dropFirst(previo.count))])
            }
            previo = actual
        }
        emitir(["fin": true])
    } catch LanguageModelSession.GenerationError.exceededContextWindowSize where !reintento {
        // Conversación demasiado larga para el modelo: se empieza otra y se repite.
        nuevaSesion()
        await preguntar(texto, reintento: true)
    } catch LanguageModelSession.GenerationError.guardrailViolation {
        emitir(["error": "guardrail", "mensaje": "Prefiero no responder a eso."])
    } catch {
        emitir(["error": "\(error)"])
    }
}

guard case .available = SystemLanguageModel.default.availability else {
    emitir(["error": "no disponible: \(SystemLanguageModel.default.availability)"])
    exit(1)
}
emitir(["listo": true])

while let linea = readLine() {
    guard let datos = linea.data(using: .utf8),
        let orden = try? JSONSerialization.jsonObject(with: datos) as? [String: Any],
        let tipo = orden["tipo"] as? String
    else { continue }
    switch tipo {
    case "nueva":
        instrucciones = orden["instrucciones"] as? String ?? ""
        nuevaSesion()
        emitir(["fin": true])
    case "preguntar":
        ahora = orden["ahora"] as? String ?? ""
        await preguntar(orden["texto"] as? String ?? "")
    default:
        emitir(["error": "orden desconocida: \(tipo)"])
    }
}

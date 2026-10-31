// Bridge between Python and Apple's model (Foundation Models, on the Mac).
//
// Reads JSON commands from stdin, one per line:
//   {"type": "new", "instructions": "..."}           starts a conversation
//   {"type": "ask", "text": "...", "now": "..."}     answers, streaming
// and writes to stdout, one per line:
//   {"delta": "..."} ... {"done": true}   or   {"error": "..."}
//
// Built by the llm/apple.py plugin the first time (swiftc).

import Foundation
import FoundationModels

func emit(_ data: [String: Any]) {
    let json = try! JSONSerialization.data(withJSONObject: data)
    FileHandle.standardOutput.write(json + Data("\n".utf8))
}

var instructions = ""
var session = LanguageModelSession()
nonisolated(unsafe) var now = ""  // date and time as spoken, sent by Python

/// The model calls it only when asked about the date or time; given in the
/// prompt, it repeated it in every answer.
struct DateTime: Tool {
    let name = "dateTime"
    let description = "Returns the current date and time."

    @Generable
    struct Arguments {}

    func call(arguments: Arguments) async throws -> String {
        now
    }
}

@MainActor
func newSession() {
    session = LanguageModelSession(tools: [DateTime()], instructions: instructions)
    session.prewarm()
}

@MainActor
func ask(_ text: String, retry: Bool = false) async {
    var previous = ""
    // GenerationError is marked deprecated in macOS 27, but it is still what
    // streamResponse throws; these two cases are told apart by it.
    do {
        for try await partial in session.streamResponse(to: text) {
            let current = partial.content
            // Each snapshot carries the accumulated text; only the new part is sent.
            if current.hasPrefix(previous), current.count > previous.count {
                emit(["delta": String(current.dropFirst(previous.count))])
            }
            previous = current
        }
        emit(["done": true])
    } catch LanguageModelSession.GenerationError.exceededContextWindowSize where !retry {
        // Conversation too long for the model: start another and try again.
        newSession()
        await ask(text, retry: true)
    } catch LanguageModelSession.GenerationError.guardrailViolation {
        emit(["error": "guardrail"])
    } catch {
        emit(["error": "\(error)"])
    }
}

guard case .available = SystemLanguageModel.default.availability else {
    emit(["error": "not available: \(SystemLanguageModel.default.availability)"])
    exit(1)
}
emit(["ready": true])

while let line = readLine() {
    guard let data = line.data(using: .utf8),
        let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
        let kind = command["type"] as? String
    else { continue }
    switch kind {
    case "new":
        instructions = command["instructions"] as? String ?? ""
        newSession()
        emit(["done": true])
    case "ask":
        now = command["now"] as? String ?? ""
        await ask(command["text"] as? String ?? "")
    default:
        emit(["error": "unknown command: \(kind)"])
    }
}

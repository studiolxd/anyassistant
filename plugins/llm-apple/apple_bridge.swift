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

/// What went wrong, as far as it matters here: a conversation too long for the model, its
/// guardrails, or anything else.
enum Failure { case tooLong, guardrail, other }

func failure(_ error: Error) -> Failure {
    if #available(macOS 27.0, *), let found = error as? LanguageModelError {
        switch found {
        case .contextSizeExceeded: return .tooLong
        case .guardrailViolation: return .guardrail
        default: return .other
        }
    }
    // macOS 26 throws LanguageModelSession.GenerationError (deprecated in 27): told by its case's
    // name, without naming the deprecated type.
    switch Mirror(reflecting: error).children.first?.label {
    case "exceededContextWindowSize": return .tooLong
    case "guardrailViolation": return .guardrail
    default: return .other
    }
}

@MainActor
func ask(_ text: String, retry: Bool = false) async {
    var previous = ""
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
    } catch {
        switch failure(error) {
        case .tooLong where !retry:
            // Conversation too long for the model: start another and try again.
            newSession()
            await ask(text, retry: true)
        case .guardrail:
            emit(["error": "guardrail"])
        default:
            emit(["error": "\(error)"])
        }
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

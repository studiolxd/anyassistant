// The server, run by the app: it is the app's own process, so it has the app's Local
// Network permission (launchd's would need its own). Where things live is what
// install.sh uses, so the terminal installer and the app share one installation.

import AppKit
import Foundation

/// A text in the Mac's language: the English one is the key (Resources/<lang>.lproj/Localizable.strings).
func T(_ english: String) -> String {
    NSLocalizedString(english, comment: "")
}

enum ServerState: Equatable {
    case notInstalled, stopped, starting, running, failed(String)
}

@MainActor
final class Server: ObservableObject {
    static let shared = Server()

    let home = FileManager.default.homeDirectoryForCurrentUser
    var program: URL { home.appending(path: "Applications/AnyAssistant") }
    var data: URL { home.appending(path: "Library/Application Support/AnyAssistant") }
    var cache: URL { home.appending(path: "Library/Caches/AnyAssistant") }
    var log: URL { cache.appending(path: "anyassistant.log") }
    /// What the app brings: the program (to install or update from) and uv.
    var bundled: URL { Bundle.main.resourceURL!.appending(path: "program") }
    var uv: URL { Bundle.main.resourceURL!.appending(path: "uv") }

    @Published var state: ServerState = .stopped
    @Published var connected = false
    @Published var busy: String?  // «Updating…»: something the app is doing

    private var process: Process?
    private var stopping = false
    private var poll: Timer?

    var installed: Bool {
        FileManager.default.fileExists(atPath: program.appending(path: "install.env").path)
            && FileManager.default.fileExists(atPath: program.appending(path: ".venv/bin/python").path)
    }

    var port: Int {
        guard let raw = try? Data(contentsOf: data.appending(path: "settings.json")),
              let settings = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
              let port = settings["port"] as? Int else { return 8080 }
        return port
    }

    /// The Mac's address on the network, for the devices.
    var address: String {
        var found = "127.0.0.1"
        var interfaces: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&interfaces) == 0, let first = interfaces else { return found }
        defer { freeifaddrs(interfaces) }
        for pointer in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let interface = pointer.pointee
            guard interface.ifa_addr.pointee.sa_family == UInt8(AF_INET) else { continue }
            let name = String(cString: interface.ifa_name)
            guard name.hasPrefix("en") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(interface.ifa_addr, socklen_t(interface.ifa_addr.pointee.sa_len), &host, socklen_t(host.count),
                        nil, 0, NI_NUMERICHOST)
            found = String(cString: host)
            break
        }
        return found
    }

    var url: String { "http://\(address):\(port)" }

    // MARK: Running it

    /// What a process the app starts needs: where things are, and a PATH with Claude, Homebrew…
    func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        let local = home.appending(path: ".local/bin").path
        env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:\(local)"
        env["ANYASSISTANT_HOME"] = data.path
        env["ANYASSISTANT_CACHE"] = cache.path
        env["UV"] = uv.path
        env["PYTHONUNBUFFERED"] = "1"
        env["ANYASSISTANT_APP"] = "1"  // the server follows the app: if it goes, so does the server
        return env
    }

    func launch() {
        guard installed else { state = .notInstalled; return }
        Task {
            await adoptLaunchd()
            if await outdated() { await update() }
            start()
        }
        poll = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
            Task { @MainActor in await Server.shared.check() }
        }
    }

    /// A server left from before (another way of starting it, an app that was killed): stopped first.
    private func stopLeftover() {
        guard let raw = try? String(contentsOf: cache.appending(path: "anyassistant.pid"), encoding: .utf8),
              let pid = pid_t(raw.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1,
              kill(pid, 0) == 0 else { return }
        kill(pid, SIGTERM)
        for _ in 0..<30 where kill(pid, 0) == 0 { usleep(250_000) }
        if kill(pid, 0) == 0 { kill(pid, SIGKILL) }
    }

    func start() {
        guard process == nil, installed else { return }
        stopLeftover()
        try? FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: log.path) {
            FileManager.default.createFile(atPath: log.path, contents: nil)
        }
        let output = try? FileHandle(forWritingTo: log)
        output?.seekToEndOfFile()
        let server = Process()
        server.executableURL = program.appending(path: "bin/anyassistant")
        server.arguments = ["run"]
        server.environment = environment()
        server.standardOutput = output
        server.standardError = output
        server.terminationHandler = { _ in
            Task { @MainActor in Server.shared.ended() }
        }
        do {
            try server.run()
            process = server
            stopping = false
            state = .starting
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func ended() {
        process = nil
        connected = false
        if stopping {
            state = .stopped
        } else {  // it fell: back in a moment, as launchd would
            state = .failed(T("It stopped; starting it again…"))
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { Server.shared.start() }
        }
    }

    func stop() {
        stopping = true
        process?.terminate()  // SIGTERM: it closes the sessions, Claude and the voice
    }

    func restart() {
        guard let process else { start(); return }
        kill(process.processIdentifier, SIGHUP)  // «restart», as by voice: same process, new code
    }

    func check() async {
        guard installed else { state = .notInstalled; return }
        guard process != nil else { return }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/status")!)
        request.timeoutInterval = 1.5
        guard let (raw, _) = try? await URLSession.shared.data(for: request),
              let status = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            if state == .running { state = .starting }
            return
        }
        state = .running
        connected = status["connected"] as? Bool ?? false
    }

    // MARK: Installing, updating

    /// The app starts the server now: an installation from the terminal (launchd) hands it over.
    func adoptLaunchd() async {
        let agent = home.appending(path: "Library/LaunchAgents/com.anyassistant.server.plist")
        guard let plist = try? String(contentsOf: agent, encoding: .utf8),
              plist.contains("\(program.path)/bin/anyassistant") else { return }
        busy = T("Taking over from launchd…")
        _ = await run(program.appending(path: "bin/anyassistant"), ["setup", "service", "--set", "service=false"])
        busy = nil
    }

    func version(_ folder: URL) -> String? {
        (try? String(contentsOf: folder.appending(path: "VERSION"), encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Whether the app brings a newer program than the installed one («<commits>-<hash>»: never older).
    func outdated() async -> Bool {
        func number(_ version: String?) -> Int { Int(version?.split(separator: "-").first ?? "") ?? 0 }
        guard let mine = version(bundled) else { return false }
        return number(mine) > number(version(program))
    }

    func update() async {
        busy = T("Updating…")
        _ = await run(bundled.appending(path: "install.sh"),
                      ["--to", program.path, "--data", data.path, "--cache", cache.path, "--update"])
        busy = nil
    }

    /// Runs a program to the end; its output, line by line, to `line` (and the exit code).
    @discardableResult
    func run(_ executable: URL, _ arguments: [String], line: ((String) -> Void)? = nil) async -> Int32 {
        await withCheckedContinuation { done in
            let task = Process()
            task.executableURL = executable
            task.arguments = arguments
            task.environment = environment()
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe
            var pending = Data()
            pipe.fileHandleForReading.readabilityHandler = { handle in
                let chunk = handle.availableData
                guard !chunk.isEmpty else { return }
                pending.append(chunk)
                while let newline = pending.firstIndex(of: 10) {
                    let text = String(decoding: pending[..<newline], as: UTF8.self)
                    pending.removeSubrange(...newline)
                    if let line { DispatchQueue.main.async { line(text) } }
                }
            }
            task.terminationHandler = { finished in
                pipe.fileHandleForReading.readabilityHandler = nil
                done.resume(returning: finished.terminationStatus)
            }
            do { try task.run() } catch { done.resume(returning: -1) }
        }
    }

    /// The HTTPS port if the plugin «https» is on (nil: plain HTTP).
    func httpsPort() async -> Int? {
        guard let (raw, response) = try? await URLSession.shared.data(
                from: URL(string: "http://127.0.0.1:\(port)/https/info")!),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let info = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else { return nil }
        return info["port"] as? Int
    }

    enum Pairing: Equatable { case code(String), off, unreachable }

    /// A pairing code; .off if the plugin «pairing» is off (devices need none); .unreachable if
    /// the server doesn't answer (yet).
    func pairingCode() async -> Pairing {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/pairing")!)
        request.httpMethod = "POST"
        guard let (raw, response) = try? await URLSession.shared.data(for: request),
              let status = (response as? HTTPURLResponse)?.statusCode else { return .unreachable }
        if status == 404 { return .off }
        guard status == 200, let answer = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
              let code = answer["code"] as? String else { return .unreachable }
        return .code(code)
    }

    /// Waits until the server answers (at most `seconds`); whether it does.
    func ready(within seconds: Double = 120) async -> Bool {
        let until = Date().addingTimeInterval(seconds)
        while Date() < until {
            var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/status")!)
            request.timeoutInterval = 1
            if (try? await URLSession.shared.data(for: request)) != nil { return true }
            try? await Task.sleep(nanoseconds: 1_000_000_000)
        }
        return false
    }
}

// Shared by the watch, the iPhone/iPad and the Mac apps (apps/shared). Talking to the Mac: its address (anyassistant.local by default; its IP if the watch can't find
// it), pairing with the code, and one sentence at a time. Over HTTPS when the Mac has the plugin
// «https»: the watch keeps the Mac's own certificate authority (fetched when pairing) and trusts
// only it; otherwise HTTP, on the local network.

import Foundation
#if !os(watchOS)
import Network
#endif

@MainActor
final class Mac: NSObject, ObservableObject, URLSessionDelegate {
    @Published var paired = UserDefaults.standard.bool(forKey: "paired")
    @Published var host = UserDefaults.standard.string(forKey: "host") ?? "anyassistant.local" {
        didSet { UserDefaults.standard.set(host, forKey: "host") }
    }
    @Published var port = UserDefaults.standard.integer(forKey: "port") == 0 ? 8080 : UserDefaults.standard.integer(forKey: "port") {
        didSet { UserDefaults.standard.set(port, forKey: "port") }
    }

    /// How it introduces itself («AnyAssistant Watch», «AnyAssistant iPhone»…): the Mac's
    /// devices tell what kind it is from this.
    let agent: String

    init(agent: String) {
        self.agent = agent
        super.init()
    }

    /// This device's id for the Mac (its name and room are in the Mac app's Devices).
    let device: String = {
        if let id = UserDefaults.standard.string(forKey: "device") { return id }
        let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        UserDefaults.standard.set(id, forKey: "device")
        return id
    }()

    /// The Mac's IP on your network (learnt when pairing): tried when its name isn't found
    /// (through the iPhone, «.local» names often aren't).
    private var address: String? {
        get { UserDefaults.standard.string(forKey: "address") }
        set {
            UserDefaults.standard.set(newValue, forKey: "address")
            NotificationCenter.default.post(name: Mac.handoffChanged, object: nil)
        }
    }
    /// Which server it is paired with (its /status «server», in its Bonjour announcement «id»):
    /// looking for it by Bonjour takes that one only, never another server on the same network.
    private var server: String? {
        get { UserDefaults.standard.string(forKey: "server") }
        set { UserDefaults.standard.set(newValue, forKey: "server") }
    }
    private var authority: Data? = UserDefaults.standard.data(forKey: "authority")  // the Mac's CA (DER)
    private var httpsPort: Int? {
        get { UserDefaults.standard.object(forKey: "httpsPort") as? Int }
        set { UserDefaults.standard.set(newValue, forKey: "httpsPort") }
    }

    lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 90  // an answer may take a while
        configuration.httpCookieStorage = .shared  // the pairing's cookie
        configuration.httpAdditionalHeaders = ["User-Agent": agent]
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()

    var base: URL { base(host) }

    func base(_ name: String) -> URL {
        if let httpsPort, authority != nil {
            return URL(string: httpsPort == 443 ? "https://\(name)" : "https://\(name):\(httpsPort)")!
        }
        return URL(string: "http://\(name):\(port)")!
    }

    /// Its name, then its IP: the first that answers soon (nil: none does).
    func reachable(_ url: (String) -> URL) async -> (String, Int)? {
        // This device's own server (the Mac app's): only there; by the network's address it would be
        // refused as another device while it restarts.
        let own = host == "127.0.0.1" || host == "localhost"
        for name in (own ? [host] : [host, address].compactMap({ $0 })) where !name.isEmpty {
            var request = URLRequest(url: url(name).appendingPathComponent("status"))
            request.timeoutInterval = 8
            if let (raw, found) = try? await session.data(for: request), let status = (found as? HTTPURLResponse)?.statusCode {
                if status == 200, let said = (try? JSONSerialization.jsonObject(with: raw) as? [String: Any])?["server"] as? String {
                    if server == nil { server = said }  // the first time it answers: it is this one
                    else if said != server { continue }  // another server at that address: not ours
                }
                return (name, status)
            }
        }
        return nil
    }

    enum Failure: Error { case unreachable, wrongCode, refused(String) }

    /// Whether the server at its host asks for a code (nil: it doesn't answer).
    func needsCode() async -> Bool? {
        guard let (_, status) = await reachable({ URL(string: "http://\($0):\(self.port)")! }) else { return nil }
        return status == 403
    }

    /// Pairs with the code (if the Mac asks for one) and learns its HTTPS authority.
    func pair(code: String) async throws {
        guard let (name, status) = await reachable({ URL(string: "http://\($0):\(self.port)")! }) else {
            throw Failure.unreachable
        }
        let plain = URL(string: "http://\(name):\(port)")!
        if status == 403 {  // pairing is on: the code
            var request = URLRequest(url: plain.appendingPathComponent("pair"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["code": code])
            let (_, answer) = try await session.data(for: request)
            guard (answer as? HTTPURLResponse)?.statusCode == 200 else { throw Failure.wrongCode }
        }
        // HTTPS, if the Mac has it: its authority, to trust it (and nothing else) from now on.
        if let (raw, answer) = try? await session.data(from: plain.appendingPathComponent("https/info")),
           (answer as? HTTPURLResponse)?.statusCode == 200,
           let info = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
           let (der, got) = try? await session.data(from: plain.appendingPathComponent("https/ca.crt")),
           (got as? HTTPURLResponse)?.statusCode == 200 {
            authority = der
            UserDefaults.standard.set(der, forKey: "authority")
            httpsPort = info["port"] as? Int ?? 443
            copyCookies(from: plain, to: name)  // the pairing's cookie, for the HTTPS address too
        } else {  // this server has no HTTPS (now): what another one (or this one before) had goes
            authority = nil
            UserDefaults.standard.removeObject(forKey: "authority")
            httpsPort = nil
        }
        // Its IP, for when its name isn't found (the certificate is for it too).
        if let (raw, _) = try? await session.data(from: plain.appendingPathComponent("https/info")),
           let info = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
           let found = (info["addresses"] as? [String])?.first(where: { $0 != "127.0.0.1" && !$0.contains(":") }) {
            address = found
            copyCookies(from: plain, to: found)
        } else if name != host {
            address = name
        }
        repairing = false
        paired = true
        UserDefaults.standard.set(true, forKey: "paired")
        NotificationCenter.default.post(name: Mac.handoffChanged, object: nil)
    }

    /// Where it answers now (its name, else its IP), or nil. Neither answering (the Mac's IP changed,
    /// and its name isn't found from here): its address now, from its Bonjour announcement.
    func url() async -> URL? {
        if let (name, _) = await reachable({ self.base($0) }) { exact = false; return base(name) }
        if exact || host == "127.0.0.1" || host == "localhost" { return nil }  // moved by hand, or its own: there or nowhere
        guard let found = await discover(), found != address else { return nil }
        for known in [host, address].compactMap({ $0 }) {  // the pairing's cookie, for the new address
            copyCookies(from: URL(string: "http://\(known):\(port)")!, to: found)
        }
        address = found
        guard let (name, _) = await reachable({ self.base($0) }) else { return nil }
        return base(name)
    }

    /// The Mac's address now, from its Bonjour announcement («_anyassistant._tcp», its «address»):
    /// only the server it is paired with (its «id»), never another one on the same network.
    func discover(seconds: Double = 3) async -> String? {
        #if os(watchOS)
        return nil  // the watch can't browse: its name, or the IP it knows
        #else
        guard let wanted = server else { return nil }  // not known yet: none is surely ours
        final class Once: @unchecked Sendable {
            var done = false
        }
        let once = Once()
        let found: (address: String, port: Int?)? = await withCheckedContinuation { continuation in
            let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_anyassistant._tcp", domain: nil), using: .tcp)
            let finish: @Sendable ((address: String, port: Int?)?) -> Void = { found in
                guard !once.done else { return }
                once.done = true
                browser.cancel()
                continuation.resume(returning: found)
            }
            browser.browseResultsChangedHandler = { results, _ in
                for result in results {
                    guard case .bonjour(let record) = result.metadata, record["id"] == wanted,
                          let address = record["address"], !address.isEmpty else { continue }  // only ours
                    return finish((address, record["port"].flatMap(Int.init)))
                }
            }
            browser.start(queue: .main)
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { finish(nil) }
        }
        guard let found else { return nil }
        if Self.isIP(host) { host = found.address }  // the settings show it where it is now
        if let port = found.port { self.port = port }
        return found.address
        #endif
    }

    /// The pairing's cookies, for a web view or a WebSocket to the same address.
    func cookies(for url: URL) -> [HTTPCookie] {
        HTTPCookieStorage.shared.cookies(for: url) ?? []
    }

    /// Whether a server's certificate is the Mac's own (its authority, kept when pairing).
    nonisolated static func trusts(_ trust: SecTrust) -> Bool {
        guard let der = UserDefaults.standard.data(forKey: "authority"),
              let anchor = SecCertificateCreateWithData(nil, der as CFData) else { return false }
        SecTrustSetAnchorCertificates(trust, [anchor] as CFArray)
        SecTrustSetAnchorCertificatesOnly(trust, true)
        return SecTrustEvaluateWithError(trust, nil)
    }

    /// The url with ?device=<its id>.
    func with(_ url: URL, device: String) -> URL {
        var parts = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "device", value: device)]
        return parts.url!
    }

    /// What the QR or the link from «Conectar otro dispositivo» on the server says: where it is and
    /// its code, so nothing is typed. anyassistant://connect?host=…&port=…&code=…&server=…&name=…
    /// (the app's own link, on the QR's page), or the QR itself: http://<ip>:<port>/connect?code=….
    struct Invitation: Equatable {
        let host: String
        let port: Int
        let code: String?  // none: that server asks for no code
        let name: String?  // the assistant's («Eva»)

        init?(_ url: URL) {
            guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
            var query: [String: String] = [:]
            for item in parts.queryItems ?? [] where query[item.name] == nil { query[item.name] = item.value }
            if parts.scheme == "anyassistant" {
                guard parts.host == "connect", let host = query["host"], !host.isEmpty else { return nil }
                self.host = host
                port = Int(query["port"] ?? "") ?? 8080
            } else if parts.scheme == "http" || parts.scheme == "https", parts.path == "/connect", let host = parts.host, !host.isEmpty {
                self.host = host
                port = parts.port ?? (parts.scheme == "https" ? 443 : 80)
            } else {
                return nil
            }
            code = query["code"].flatMap { $0.isEmpty ? nil : $0 }
            name = query["name"].flatMap { $0.isEmpty ? nil : $0 }
        }
    }

    /// An invitation arrived (the app opened by its link, or the QR scanned): the pairing screen
    /// pairs with it. Paired already, with a way back if it fails.
    @Published var invited: Invitation?

    func invite(_ invitation: Invitation) {
        invited = invitation
        if paired { pairAgain() }
    }

    /// Pairs where the invitation says, with its code if there is one.
    func pair(_ invitation: Invitation) async throws {
        host = invitation.host
        port = invitation.port
        moved()
        defer { invited = nil }
        try await pair(code: invitation.code ?? "")
    }

    /// «Pair again» chosen here: the code screen, with a way back. What it had stays until a new
    /// pairing works (not even saved: reopening the app, it is still paired).
    @Published var repairing = false

    func pairAgain() {
        repairing = true
        paired = false
    }

    func cancelPairing() {
        repairing = false
        paired = true
    }

    func unpair() {
        repairing = false
        paired = false
        UserDefaults.standard.set(false, forKey: "paired")
        NotificationCenter.default.post(name: Mac.handoffChanged, object: nil)
    }

    /// Forgets the Mac it was paired with: its authority, its port and its IP too.
    /// Moved by hand (another host or port, in the settings or pairing): the IP it had was the
    /// old server's, and until it answers at the new place nothing else stands in for it.
    func moved() {
        address = nil
        server = nil  // learnt again where it answers now
        exact = true
    }

    /// Whether a host is an IPv4 address (Bonjour updates it), not a name.
    nonisolated static func isIP(_ host: String) -> Bool {
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        return parts.count == 4 && parts.allSatisfy { UInt8($0) != nil }
    }
    private var exact = false

    func forget() {
        unpair()
        authority = nil
        UserDefaults.standard.removeObject(forKey: "authority")
        httpsPort = nil
        address = nil
    }

    private func copyCookies(from url: URL, to name: String) {
        for cookie in HTTPCookieStorage.shared.cookies(for: url) ?? [] {
            var properties = cookie.properties ?? [:]
            properties[.secure] = nil
            properties[.domain] = name
            if let copy = HTTPCookie(properties: properties) { HTTPCookieStorage.shared.setCookie(copy) }
        }
    }

    // MARK: The watch's pairing, from the iPhone

    /// What the watch needs changed here (paired, the IP): the iPhone sends it again (WatchBridge).
    nonisolated static let handoffChanged = Notification.Name("macHandoff")

    /// What the watch needs to talk to this server as this iPhone does: where (its IP: the watch
    /// resolves no «.local» names and has no Bonjour), its HTTPS authority, the pairing's cookies.
    /// Read from what is saved, so it can be asked before any window (the app woken by the watch).
    nonisolated static func handoff() -> [String: Any] {
        let saved = UserDefaults.standard
        guard saved.bool(forKey: "paired") else { return ["paired": false] }
        let host = saved.string(forKey: "host") ?? "anyassistant.local"
        let address = saved.string(forKey: "address")
        var found: [String: Any] = ["paired": true, "host": isIP(host) ? host : address ?? host,
                                    "port": saved.integer(forKey: "port") == 0 ? 8080 : saved.integer(forKey: "port")]
        if let server = saved.string(forKey: "server") { found["server"] = server }
        if let authority = saved.data(forKey: "authority"), let https = saved.object(forKey: "httpsPort") as? Int {
            found["authority"] = authority
            found["httpsPort"] = https
        }
        var cookies: [String: String] = [:]
        for name in [host, address].compactMap({ $0 }) {
            for cookie in HTTPCookieStorage.shared.cookies(for: URL(string: "http://\(name)")!) ?? [] {
                cookies[cookie.name] = cookie.value
            }
        }
        found["cookies"] = cookies
        return found
    }

    /// The watch: paired as its iPhone is (what handoff gave), or not paired if the iPhone isn't.
    func adopt(_ handoff: [String: Any]) {
        guard handoff["paired"] as? Bool == true, let ip = handoff["host"] as? String else {
            if paired { unpair() }
            return
        }
        host = ip
        address = ip
        port = handoff["port"] as? Int ?? 8080
        server = handoff["server"] as? String
        authority = handoff["authority"] as? Data
        UserDefaults.standard.set(authority, forKey: "authority")
        httpsPort = authority != nil ? handoff["httpsPort"] as? Int : nil
        for (name, value) in handoff["cookies"] as? [String: String] ?? [:] {
            let properties: [HTTPCookiePropertyKey: Any] = [.domain: ip, .path: "/", .name: name, .value: value,
                                                            .expires: Date().addingTimeInterval(10 * 365 * 86400)]
            if let cookie = HTTPCookie(properties: properties) { HTTPCookieStorage.shared.setCookie(cookie) }
        }
        exact = true  // where the iPhone says: no looking elsewhere
        if !paired {
            paired = true
            UserDefaults.standard.set(true, forKey: "paired")
        }
    }

    struct Answer { let heard: String; let answer: String; let audio: Data }

    /// One sentence (a WAV) → what it heard, its answer and its voice.
    func talk(_ wav: Data) async throws -> Answer {
        guard let base = await url() else { throw Failure.unreachable }
        var request = URLRequest(url: with(base.appendingPathComponent("talk"), device: device))
        request.httpMethod = "POST"
        request.setValue("audio/wav", forHTTPHeaderField: "Content-Type")
        request.httpBody = wav
        guard let (raw, response) = try? await session.data(for: request) else { throw Failure.unreachable }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let found = (try? JSONSerialization.jsonObject(with: raw) as? [String: Any]) ?? [:]
        if status == 403 { unpair(); throw Failure.wrongCode }
        guard status == 200 else { throw Failure.refused(found["error"] as? String ?? "\(status)") }
        return Answer(heard: found["heard"] as? String ?? "", answer: found["answer"] as? String ?? "",
                      audio: Data(base64Encoded: found["audio"] as? String ?? "") ?? Data())
    }

    // Only the Mac's own authority is trusted for its HTTPS address.
    nonisolated func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                                completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              UserDefaults.standard.data(forKey: "authority") != nil else {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        if Mac.trusts(trust) {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }
}

#if !os(watchOS)
/// The servers announcing themselves on this network (Bonjour «_anyassistant._tcp»), as they come
/// and go: for the first pairing step.
@MainActor
final class ServerBrowser: ObservableObject {
    struct Found: Identifiable, Equatable {
        let id: String  // its announcement's name
        let assistant: String  // «Eva»
        let computer: String  // «MacBook-Air-de-Suvi»
        let address: String
        let port: Int
        let pairing: Bool  // it asks for a code
        var server: String? = nil  // which server it is (its id: the TXT's «id»)
    }

    @Published private(set) var servers: [Found] = []
    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_anyassistant._tcp", domain: nil), using: .tcp)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let found: [Found] = results.compactMap { result in
                guard case .service(let name, _, _, _) = result.endpoint, case .bonjour(let record) = result.metadata,
                      let address = record["address"], !address.isEmpty else { return nil }
                return Found(id: name, assistant: record["name"] ?? "AnyAssistant",
                             computer: record["computer"] ?? name.replacingOccurrences(of: "AnyAssistant on ", with: ""),
                             address: address, port: Int(record["port"] ?? "") ?? 8080, pairing: record["pairing"] != "0",
                             server: record["id"])
            }
            Task { @MainActor in self?.servers = found.sorted { $0.computer < $1.computer } }
        }
        browser.start(queue: .main)
        self.browser = browser
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }
}
#endif

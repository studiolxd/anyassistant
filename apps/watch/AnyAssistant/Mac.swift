// Talking to the Mac: its address (anyassistant.local by default; its IP if the watch can't find
// it), pairing with the code, and one sentence at a time. Over HTTPS when the Mac has the plugin
// «https»: the watch keeps the Mac's own certificate authority (fetched when pairing) and trusts
// only it; otherwise HTTP, on the local network.

import Foundation

@MainActor
final class Mac: NSObject, ObservableObject, URLSessionDelegate {
    @Published var paired = UserDefaults.standard.bool(forKey: "paired")
    @Published var host = UserDefaults.standard.string(forKey: "host") ?? "anyassistant.local" {
        didSet { UserDefaults.standard.set(host, forKey: "host") }
    }
    @Published var port = UserDefaults.standard.integer(forKey: "port") == 0 ? 8080 : UserDefaults.standard.integer(forKey: "port") {
        didSet { UserDefaults.standard.set(port, forKey: "port") }
    }

    /// This watch's id for the Mac (its name and room are in the Mac app's Devices).
    let device: String = {
        if let id = UserDefaults.standard.string(forKey: "device") { return id }
        let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        UserDefaults.standard.set(id, forKey: "device")
        return id
    }()

    private var authority: Data? = UserDefaults.standard.data(forKey: "authority")  // the Mac's CA (DER)
    private var httpsPort: Int? {
        get { UserDefaults.standard.object(forKey: "httpsPort") as? Int }
        set { UserDefaults.standard.set(newValue, forKey: "httpsPort") }
    }

    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 90  // an answer may take a while
        configuration.httpCookieStorage = .shared  // the pairing's cookie
        configuration.httpAdditionalHeaders = ["User-Agent": "AnyAssistant Watch"]
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()

    var base: URL {
        if let httpsPort, authority != nil {
            return URL(string: httpsPort == 443 ? "https://\(host)" : "https://\(host):\(httpsPort)")!
        }
        return URL(string: "http://\(host):\(port)")!
    }

    enum Failure: Error { case unreachable, wrongCode, refused(String) }

    /// Pairs with the code (if the Mac asks for one) and learns its HTTPS authority.
    func pair(code: String) async throws {
        let plain = URL(string: "http://\(host):\(port)")!
        guard let (_, found) = try? await session.data(from: plain.appending(path: "status")),
              let status = (found as? HTTPURLResponse)?.statusCode else { throw Failure.unreachable }
        if status == 403 {  // pairing is on: the code
            var request = URLRequest(url: plain.appending(path: "pair"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["code": code])
            let (_, answer) = try await session.data(for: request)
            guard (answer as? HTTPURLResponse)?.statusCode == 200 else { throw Failure.wrongCode }
        }
        // HTTPS, if the Mac has it: its authority, to trust it (and nothing else) from now on.
        if let (raw, answer) = try? await session.data(from: plain.appending(path: "https/info")),
           (answer as? HTTPURLResponse)?.statusCode == 200,
           let info = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
           let (der, got) = try? await session.data(from: plain.appending(path: "https/ca.crt")),
           (got as? HTTPURLResponse)?.statusCode == 200 {
            authority = der
            UserDefaults.standard.set(der, forKey: "authority")
            httpsPort = info["port"] as? Int ?? 443
            copyCookies(from: plain)  // the pairing's cookie, for the HTTPS address too
        }
        paired = true
        UserDefaults.standard.set(true, forKey: "paired")
    }

    func unpair() {
        paired = false
        UserDefaults.standard.set(false, forKey: "paired")
    }

    private func copyCookies(from url: URL) {
        for cookie in HTTPCookieStorage.shared.cookies(for: url) ?? [] {
            var properties = cookie.properties ?? [:]
            properties[.secure] = nil
            properties[.domain] = host
            if let copy = HTTPCookie(properties: properties) { HTTPCookieStorage.shared.setCookie(copy) }
        }
    }

    struct Answer { let heard: String; let answer: String; let audio: Data }

    /// One sentence (a WAV) → what it heard, its answer and its voice.
    func talk(_ wav: Data) async throws -> Answer {
        var request = URLRequest(url: base.appending(path: "talk").appending(queryItems: [.init(name: "device", value: device)]))
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
              let der = UserDefaults.standard.data(forKey: "authority"),
              let anchor = SecCertificateCreateWithData(nil, der as CFData) else {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        SecTrustSetAnchorCertificates(trust, [anchor] as CFArray)
        SecTrustSetAnchorCertificatesOnly(trust, true)
        if SecTrustEvaluateWithError(trust, nil) {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }
}

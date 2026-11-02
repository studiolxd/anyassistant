// Every theme but Eyes: the server's page for the apps (/?app&theme=<name>: plugins/page/web, the
// same page a browser shows, so a theme from the community looks the same here) in a web view, fed
// by the app. The app keeps the microphone, the audio, the camera, the notifications and the
// connection (Link): the page opens none of them. It gets what the server says (forward), the
// voices' levels and the app's own problems, and gives back its taps, holding the face (the
// settings), and where its camera's window is (the app's own camera goes there). The pairing's
// cookie goes with it; over HTTPS only the server's own authority is trusted (Mac.trusts). While
// the page can't be had, ThemeView draws Eyes.

import SwiftUI
import WebKit

@MainActor
final class WebFace: NSObject, ObservableObject {
    let face: FaceModel
    let levels: Levels
    /// The server, as the app reaches it, and its pairing's cookies (Link, with each /config).
    private(set) var base: URL?
    private var cookies: [HTTPCookie] = []
    /// The page didn't load, or never said it was ready: Eyes, until the next /config.
    @Published private(set) var failed = false
    /// Where the page has the camera's window, while it shows it.
    @Published private(set) var cameraWindow: CGRect?
    fileprivate var tap: () -> Void = {}
    fileprivate var settings: (() -> Void)?

    private weak var view: WKWebView?
    private var ready = false
    private var timer: Timer?
    private var sentVoice: CGFloat = -1
    private var sentSpeech: CGFloat = -1
    private var sentProblem: String?? = .none  // .none: not sent yet

    init(face: FaceModel, levels: Levels) {
        self.face = face
        self.levels = levels
    }

    /// Whether a theme is drawn here (not Eyes, and the page can be had).
    func shows(_ theme: String) -> Bool { theme != "eyes" && base != nil && !failed }

    /// The server's address and cookies, with each /config: the page is tried again.
    func configured(base: URL, cookies: [HTTPCookie]) {
        self.base = base
        self.cookies = cookies
        if failed { failed = false }
    }

    // MARK: The view

    fileprivate func makeView(theme: String) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()  // only the cookie it is given
        configuration.userContentController.add(Handler(self), name: "anyassistant")
        #if os(iOS)
        configuration.allowsInlineMediaPlayback = true
        #endif
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self
        #if os(iOS)
        view.isOpaque = false  // the theme's background, not a white flash
        view.backgroundColor = .clear
        view.scrollView.backgroundColor = .clear
        view.scrollView.isScrollEnabled = false  // the page doesn't move; its words scroll inside
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.allowsLinkPreview = false
        #else
        view.setValue(false, forKey: "drawsBackground")
        #endif
        self.view = view
        ready = false
        cameraWindow = nil
        load(theme, in: view)
        return view
    }

    private func load(_ theme: String, in view: WKWebView) {
        guard let base, var parts = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return }
        parts.path = "/"
        parts.queryItems = [URLQueryItem(name: "app", value: nil), URLQueryItem(name: "theme", value: theme)]
        guard let url = parts.url else { return }
        let store = view.configuration.websiteDataStore.httpCookieStore
        let group = DispatchGroup()
        for cookie in cookies {
            group.enter()
            store.setCookie(cookie) { group.leave() }
        }
        group.notify(queue: .main) { [weak view] in
            view?.load(URLRequest(url: url))
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self, weak view] in
            guard let self, let view, self.view === view, !self.ready else { return }
            self.failed = true  // loaded, but the page never said it was ready
        }
    }

    // MARK: To the page

    /// A message from the server, as it came (the page draws it as a browser would).
    func forward(_ message: [String: Any]) {
        send(message)
    }

    private func send(_ message: [String: Any]) {
        guard ready, let view, let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }
        view.evaluateJavaScript("AnyAssistant.receive(\(json))", completionHandler: nil)
    }

    /// The page is ready: what is on the face already, then the levels and the problems as they change.
    private func began() {
        ready = true
        for caption in face.captions {
            var message: [String: Any] = ["type": "text", "text": caption.text,
                                          "author": caption.assistant ? "assistant" : "user"]
            if let id = caption.answer { message["id"] = id }
            send(message)
        }
        if let said = face.said {
            var message: [String: Any] = ["type": "speaking", "id": said.id, "start": said.start]
            if let end = said.end { message["end"] = end }
            send(message)
        }
        send(["type": "timers", "items": face.items.map { ["kind": $0.kind, "at": $0.at, "label": $0.label] }])
        send(["type": "alarm", "label": face.alarmLabel])
        sendState()
        if face.cameraShown { send(["type": "camera", "on": true]) }
        sentProblem = .none
        sentVoice = -1
        sentSpeech = -1
        tick()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    private func sendState() {
        var message: [String: Any] = ["type": "state", "state": face.state]
        if !face.wake.isEmpty { message["wake_phrase"] = face.wake }
        if !face.pausedWhy.isEmpty { message["why"] = face.pausedWhy }
        if !face.pausedApp.isEmpty { message["app"] = face.pausedApp }
        send(message)
    }

    /// The voices' levels (your voice, its own), and the app's problem when it changes (with the
    /// state: «connecting» is the app's own too).
    private func tick() {
        guard ready, view != nil else {
            timer?.invalidate()
            timer = nil
            return
        }
        let voice = levels.voice, speech = levels.speech
        if abs(voice - sentVoice) > 0.01 || abs(speech - sentSpeech) > 0.01 {
            sentVoice = voice
            sentSpeech = speech
            send(["type": "levels", "voice": Double(voice), "speech": Double(speech)])
        }
        if sentProblem != .some(face.problem) {
            sentProblem = .some(face.problem)
            sendState()
            send(["type": "problem", "text": face.problem ?? NSNull()])
        }
    }

    // MARK: From the page

    fileprivate func received(_ body: Any) {
        guard let message = body as? [String: Any], let type = message["type"] as? String else { return }
        switch type {
        case "ready": began()
        case "tap": tap()
        case "settings": settings?()
        case "camera":
            let number = { (key: String) in (message[key] as? NSNumber).map { CGFloat($0.doubleValue) } }
            if message["on"] as? Bool == true, let x = number("x"), let y = number("y"),
               let width = number("width"), let height = number("height"), width > 0, height > 0 {
                cameraWindow = CGRect(x: x, y: y, width: width, height: height)
            } else {
                cameraWindow = nil
            }
        default: break
        }
    }

    /// The page's messages, without keeping the WebFace alive (the web view's configuration keeps its handlers).
    private final class Handler: NSObject, WKScriptMessageHandler {
        weak var owner: WebFace?

        init(_ owner: WebFace) { self.owner = owner }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            let body = message.body
            Task { @MainActor in self.owner?.received(body) }
        }
    }
}

extension WebFace: WKNavigationDelegate {
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if let response = navigationResponse.response as? HTTPURLResponse, navigationResponse.isForMainFrame,
           response.statusCode != 200 {
            decisionHandler(.cancel)
            failed = true
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        stopped(webView, error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        stopped(webView, error)
    }

    private func stopped(_ webView: WKWebView, _ error: Error) {
        guard webView === view, (error as NSError).code != NSURLErrorCancelled else { return }
        failed = true
    }

    /// The system ended the page (memory): again.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        guard webView === view else { return }
        ready = false
        webView.reload()
    }

    /// Over HTTPS, only the server's own authority (learnt when pairing), as the app's connection.
    func webView(_ webView: WKWebView, didReceive challenge: URLAuthenticationChallenge,
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

/// The theme's page, and the app's camera where the page has its window («muestra la cámara»).
struct WebTheme: View {
    @ObservedObject var web: WebFace
    let camera: Camera
    let theme: String
    let tap: () -> Void
    let settings: (() -> Void)?

    var body: some View {
        ZStack(alignment: .topLeading) {
            ThemePage(web: web, theme: theme, tap: tap, settings: settings)
            if let window = web.cameraWindow {
                // Inside the window's frame (the theme's border stays).
                CameraPreview(camera: camera)
                    .frame(width: max(window.width - 4, 1), height: max(window.height - 4, 1))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .offset(x: window.minX + 2, y: window.minY + 2)
                    .allowsHitTesting(false)
                    .transition(.opacity)
            }
        }
    }
}

#if os(iOS)
private struct ThemePage: UIViewRepresentable {
    let web: WebFace
    let theme: String
    let tap: () -> Void
    let settings: (() -> Void)?

    func makeUIView(context: Context) -> WKWebView {
        web.tap = tap
        web.settings = settings
        return web.makeView(theme: theme)
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        web.tap = tap
        web.settings = settings
    }
}
#else
private struct ThemePage: NSViewRepresentable {
    let web: WebFace
    let theme: String
    let tap: () -> Void
    let settings: (() -> Void)?

    func makeNSView(context: Context) -> WKWebView {
        web.tap = tap
        web.settings = settings
        return web.makeView(theme: theme)
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        web.tap = tap
        web.settings = settings
    }
}
#endif

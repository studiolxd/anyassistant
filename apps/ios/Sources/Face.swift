// The face: the Mac's page (its skins, the captions, the timers) in a web view. It doesn't use
// the microphone itself: the app passes it the messages (window.fromApp) and it passes back
// its own (taps, its skin) through «anyassistant».

import SwiftUI
import WebKit

struct Face: UIViewRepresentable {
    let link: Link

    func makeCoordinator() -> Pinning { Pinning(link: link) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.userContentController.add(Relay(link: link), name: "anyassistant")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isOpaque = false
        view.backgroundColor = .black
        view.scrollView.isScrollEnabled = false
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.navigationDelegate = context.coordinator
        if #available(iOS 16.4, *) { view.isInspectable = true }  // Safari's Develop menu, while trying it
        link.web = view
        link.loadPage()
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}
}

/// The page's messages, to the app (a separate object: the web view keeps its handlers).
final class Relay: NSObject, WKScriptMessageHandler {
    weak var link: Link?

    init(link: Link) { self.link = link }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        Task { @MainActor in self.link?.fromPage(body) }
    }
}

/// Only the Mac's own authority is trusted for its HTTPS address; a page that fails is loaded again.
final class Pinning: NSObject, WKNavigationDelegate {
    weak var link: Link?

    init(link: Link) { self.link = link }

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

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        Task { @MainActor in self.link?.pageFailed() }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        Task { @MainActor in self.link?.pageFailed() }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        Task { @MainActor in self.link?.pageFailed() }
    }
}

// The themes' page (every state of each theme, to see them: the plugin «themes»), in a window of the
// app, as Eva's and the settings. No toolbar: it reloads by itself when a theme's files change, and
// «Open in the browser» (for whoever edits one: its developer tools) is in the View menu.

import SwiftUI
import WebKit

struct ThemesWindow: View {
    @ObservedObject var server = Server.shared

    static var page: URL { URL(string: "http://127.0.0.1:\(Server.shared.port)/themes")! }

    var body: some View {
        WebPage(url: ThemesWindow.page, reloads: 0)
    }
}

/// A web page of the server's, in the window.
struct WebPage: NSViewRepresentable {
    let url: URL
    let reloads: Int

    final class Coordinator { var reloads = 0 }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.setValue(false, forKey: "drawsBackground")  // no white flash before the dark page
        view.load(URLRequest(url: url))
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        if reloads != context.coordinator.reloads {
            context.coordinator.reloads = reloads
            view.reload()
        }
    }
}

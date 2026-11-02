// The themes' page (every state of each theme, to see them: the plugin «themes»), in a window of the
// app, as Eva's and the settings; «Open in the browser» for whoever edits one (its developer tools).

import SwiftUI
import WebKit

struct ThemesWindow: View {
    @ObservedObject var server = Server.shared
    @State private var reloads = 0

    var page: URL { URL(string: "http://127.0.0.1:\(server.port)/themes")! }

    var body: some View {
        WebPage(url: page, reloads: reloads)
            .toolbar {
                ToolbarItemGroup {
                    Button { reloads += 1 } label: { Label(T("Reload"), systemImage: "arrow.clockwise") }
                        .help(T("Reload"))
                    Button { NSWorkspace.shared.open(page) } label: {
                        Label(T("Open in the browser"), systemImage: "safari")
                    }
                    .help(T("Open in the browser"))
                }
            }
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

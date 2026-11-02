// The themes' page (every state of each theme, to see them: the plugin «themes»), in a window of the
// app, as Eva's and the settings. No toolbar: it reloads by itself when a theme's files change, and
// «Open in the browser» (for whoever edits one: its developer tools) is in the View menu.
// An update from the community (Updates.swift) opens it at its «From the community» tab.

import SwiftUI
import WebKit

struct ThemesWindow: View {
    @ObservedObject var server = Server.shared
    @State private var url = ThemesWindow.first()
    @State private var visits = 0

    static var page: URL { URL(string: "http://127.0.0.1:\(Server.shared.port)/themes")! }
    static var communityPage: URL { URL(string: page.absoluteString + "#community")! }

    /// Asked to open at «From the community» before the window is there.
    @MainActor static var wantsCommunity = false

    @MainActor static func first() -> URL {
        defer { wantsCommunity = false }
        return wantsCommunity ? communityPage : page
    }

    /// Opens the window at its «From the community» tab (open or not yet).
    @MainActor static func showCommunity() {
        wantsCommunity = true
        NotificationCenter.default.post(name: .themesCommunity, object: nil)
        Delegate.show("themes")
    }

    var body: some View {
        WebPage(url: url, reloads: 0, visits: visits)
            .onReceive(NotificationCenter.default.publisher(for: .themesCommunity)) { _ in
                ThemesWindow.wantsCommunity = false
                url = ThemesWindow.communityPage
                visits += 1
            }
    }
}

extension Notification.Name {
    static let themesCommunity = Notification.Name("AnyAssistantThemesCommunity")
}

/// A web page of the server's, in the window.
struct WebPage: NSViewRepresentable {
    let url: URL
    let reloads: Int
    var visits = 0  // one more: it goes to url again (its #part, the page shows that)

    final class Coordinator { var reloads = 0; var visits = 0 }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.setValue(false, forKey: "drawsBackground")  // no white flash before the dark page
        context.coordinator.visits = visits
        view.load(URLRequest(url: url))
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        if reloads != context.coordinator.reloads {
            context.coordinator.reloads = reloads
            view.reload()
        }
        if visits != context.coordinator.visits {
            context.coordinator.visits = visits
            view.load(URLRequest(url: url))
        }
    }
}

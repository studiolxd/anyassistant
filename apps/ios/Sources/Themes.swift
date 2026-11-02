// The face: the theme Eyes, drawn natively (plugins/page/themes/eyes: the same look, sizes in «v» =
// 1% of the screen's shorter side, as the CSS's vmin); every other theme, the server's page in a
// web view (WebTheme.swift), fed by the app. Eyes too while the server's page can't be had.

import AVFoundation
import SwiftUI

struct ThemeView: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let camera: Camera
    @ObservedObject var web: WebFace
    /// A tap (it stops talking, or wakes up), and holding the face (its settings; nil: none).
    var tap: () -> Void = {}
    var settings: (() -> Void)? = nil

    @State private var faceEnd: CGFloat = 0  // where the theme's face and words end (FaceEnd)

    var body: some View {
        ZStack {
            // The background to the screen's edges; the face, its words, the clock and the camera
            // inside the safe area (not under the Dynamic Island, the home bar or a window's title).
            face.background.ignoresSafeArea()
            if web.shows(face.theme) {
                // To the screen's edges, as Safari full screen: the page keeps its content inside the
                // safe area (env(safe-area-inset-*)), and what a theme draws beyond it (Orb's ring)
                // isn't cut at the safe area's edge.
                WebTheme(web: web, camera: camera, theme: face.theme, tap: tap, settings: settings)
                    .id(face.theme)  // another theme: another page
                    .ignoresSafeArea()
            } else {
                GeometryReader { geometry in
                    content(geometry.size)
                }
                .contentShape(Rectangle())
                .onTapGesture(perform: tap)
                .onLongPressGesture(minimumDuration: 0.8) { settings?() }
            }
        }
    }

    @ViewBuilder func content(_ size: CGSize) -> some View {
        let v = min(size.width, size.height) / 100
        ZStack(alignment: .top) {
                EyesTheme(face: face, levels: levels, v: v, size: size)
                // «Muestra la cámara»: centred below what the face says, in the space left; the
                // face doesn't move.
                if face.cameraShown {
                    let top = (faceEnd > 0 ? faceEnd : size.height * 0.6) + 2 * v
                    CameraBox(camera: camera, area: CGSize(width: size.width, height: max(size.height - top - 3 * v, size.height * 0.2)))
                        .offset(y: min(top, size.height * 0.8 - 3 * v))
                        .transition(.opacity)
                }
                Windows(face: face, v: v, size: size)
            }
            .coordinateSpace(name: "theme")
            .onPreferenceChange(FaceEnd.self) { faceEnd = $0 }
    }
}

let grey = Color(white: 0.53)  // #888

// MARK: - Shared pieces

struct StatusLine: View {
    @ObservedObject var face: FaceModel

    var body: some View {
        Text(face.status).font(.system(size: 22)).foregroundColor(grey)
            .multilineTextAlignment(.center)
    }
}

struct TimerLines: View {
    @ObservedObject var face: FaceModel
    let size: CGFloat

    var body: some View {
        if face.shows("show_timers") {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let now = context.date.timeIntervalSince1970
                VStack(spacing: 4) {
                    ForEach(face.items.filter { $0.at > now - 1 }) { item in
                        HStack(spacing: size * 0.35) {
                            Image(systemName: Self.icon(item.kind))
                            Text(face.line(item, now: context.date)).monospacedDigit()
                        }
                    }
                }
                .font(.system(size: size))
                .foregroundColor(.white)
            }
        }
    }

    static func icon(_ kind: String) -> String {
        kind == "alarm" ? "alarm" : kind == "reminder" ? "bell" : "timer"
    }
}

struct CaptionLines: View {
    @ObservedObject var face: FaceModel
    let accent: Color
    var minHeight: CGFloat = 0

    var body: some View {
        let last = face.captions.last
        WordsArea(aim: last.map { face.aim($0.id, answer: $0.answer, text: $0.text) } ?? Aim(key: "", y: 0),
                  fresh: last?.id ?? "", minHeight: minHeight) {
            VStack(spacing: 5) {
                ForEach(face.captions) { caption in
                    let isLast = caption.id == last?.id
                    Text(caption.text)
                        .font(.system(size: isLast ? 24 : 17.6))
                        .foregroundColor(caption.assistant ? accent : .white)
                        .opacity(isLast ? 1 : 0.6)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .id(caption.id)
                }
            }
            .frame(maxWidth: .infinity)
        }
    }
}

/// A WordsArea's words, measured in its scroll: width, their top (0, or less when scrolled); height, theirs.
struct WordsMetrics: PreferenceKey {
    static let defaultValue = CGSize.zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()  // views that don't measure give the default: they don't count
        if next != .zero { value = next }
    }
}

/// The words (the captions, what you said, the answer) in their own area, as the page's: it scrolls
/// without a bar (a finger, the trackpad, the wheel) and follows `aim` (FaceModel.aim: the end of
/// what you said, the sentence the voice is saying); scrolled by hand, it stops following until
/// back at the end or new words arrive (`fresh` changes). A fade at the edge where there is more.
/// Its height: as tall as the words, from `minHeight` up to the space its column leaves it.
struct WordsArea<Content: View>: View {
    let aim: Aim
    let fresh: String
    var minHeight: CGFloat = 0
    @ViewBuilder let content: () -> Content

    @State private var space = UUID().uuidString  // its scroll's own coordinate space
    @State private var offset: CGFloat = 0  // the words' top in the area: 0, or less when scrolled
    @State private var words: CGFloat = 0  // the words' height
    @State private var following = true
    @State private var auto = Date.distantPast  // until when the scrolling is its own

    @State private var shown: CGFloat = 0  // its height as laid out (down to the bottom)

    /// As tall as the words, at most what its column leaves it (SwiftUI's layout gives it the space
    /// down to the bottom: no measuring where it starts).
    private var view: CGFloat { shown }

    var body: some View {
        let view = self.view
        ScrollViewReader { proxy in
            ScrollView(.vertical, showsIndicators: false) {
                content()
                    .background(GeometryReader { g in
                        Color.clear.preference(key: WordsMetrics.self,
                                               value: CGSize(width: g.frame(in: .named(space)).minY, height: g.size.height))
                    })
            }
            .coordinateSpace(name: space)
            .frame(minHeight: minHeight, maxHeight: max(words, minHeight))
            .onPreferenceChange(WordsMetrics.self) { m in
                let moved = abs(m.width - offset) > 1
                offset = m.width
                let grew = m.height != words
                words = m.height
                if moved && Date() > auto { following = false }  // by hand
                if !following && -offset >= words - view - 2 {  // back at the end: following again
                    following = true
                    go(proxy)
                } else if grew {
                    go(proxy)
                }
            }
            .onChange(of: aim) { _ in go(proxy) }
            .onChange(of: fresh) { _ in following = true; go(proxy) }
            .onAppear { go(proxy) }
        }
        .frame(minHeight: minHeight, maxHeight: max(words, minHeight))
        .mask(VStack(spacing: 0) {
            LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom)
                .frame(height: offset < -1 ? 28 : 0)
            Color.black
            LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom)
                .frame(height: words + offset > view + 1 ? 28 : 0)
        })
        .background(GeometryReader { g in
            Color.clear
                .onAppear { shown = g.size.height }
                .onChange(of: g.size.height) { shown = $0 }
        })
    }

    private func go(_ proxy: ScrollViewProxy) {
        guard following, !aim.key.isEmpty else { return }
        auto = Date().addingTimeInterval(0.7)
        withAnimation(.easeInOut(duration: 0.45)) {
            proxy.scrollTo(aim.key, anchor: UnitPoint(x: 0.5, y: aim.y))
        }
    }
}

/// The time and the date, as the theme lays them out.
struct Clock<Content: View>: View {
    @ObservedObject var face: FaceModel
    @ViewBuilder var content: (_ time: String?, _ day: String?) -> Content

    var body: some View {
        TimelineView(.periodic(from: .now, by: 5)) { context in
            content(face.shows("show_time") ? face.time(context.date) : nil,
                    face.shows("show_date") ? face.day(context.date) : nil)
        }
    }
}

/// Where the face and its words end (in ThemeView's space): the camera goes below.
struct FaceEnd: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

extension View {
    /// Marks the end of the face and its words (on its column).
    func endsTheFace() -> some View {
        background(GeometryReader { geometry in
            Color.clear.preference(key: FaceEnd.self, value: geometry.frame(in: .named("theme")).maxY)
        })
    }
}

/// The camera live («muestra la cámara», mirrored), centred in the space below the face.
struct CameraBox: View {
    let camera: Camera
    let area: CGSize

    var body: some View {
        let height = min(area.height * 0.88, area.width * 0.9 * 3 / 4), width = height * 4 / 3
        CameraPreview(camera: camera)
            .frame(width: width, height: height)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color(hex: "#5bc6e8")!, lineWidth: 2))
            .frame(width: area.width, height: area.height)
    }
}

/// The photo it looks at (with a scanning sweep while it thinks about it), over the face: a
/// moment, and what it is looking at.
struct Windows: View {
    @ObservedObject var face: FaceModel
    let v: CGFloat
    let size: CGSize

    var body: some View {
        // 80 × 60 (vmin), at most 45 % of the height: in a wide window it stays above the captions.
        let height = min(60 * v, size.height * 0.45), width = height * 4 / 3
        ZStack {
            if let photo = face.photo {
                let green = Color(hex: "#3fe0a8")!
                ZStack {
                    Image(platform: photo).resizable().scaledToFill()
                        .saturation(0.6).brightness(-0.1)
                        .frame(width: width, height: height).clipped()
                    if face.scanning {
                        TimelineView(.animation) { context in
                            let y = (swing(context.date.timeIntervalSinceReferenceDate, period: 1.4) - 0.5) * height
                            LinearGradient(stops: [.init(color: green.opacity(0), location: 0),
                                                   .init(color: green.opacity(0.08), location: 0.44),
                                                   .init(color: Color(red: 0.63, green: 1, blue: 0.86).opacity(0.75), location: 0.495),
                                                   .init(color: .white.opacity(0.95), location: 0.5),
                                                   .init(color: green.opacity(0), location: 0.506)],
                                           startPoint: .top, endPoint: .bottom)
                                .offset(y: y)
                        }
                    }
                }
                .frame(width: width, height: height)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(green, lineWidth: 2))
                .shadow(color: green.opacity(0.35), radius: 4 * v)
                .opacity(face.photoFading ? 0 : 1)
                .animation(.easeInOut(duration: 1.2), value: face.photoFading)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .top)
        .offset(y: size.height * 0.08)
        .allowsHitTesting(false)
    }
}

#if os(iOS)
struct CameraPreview: UIViewRepresentable {
    let camera: Camera

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.preview.session = camera.session
        view.preview.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ view: PreviewView, context: Context) { view.orient() }
}
#else
struct CameraPreview: NSViewRepresentable {
    let camera: Camera

    func makeNSView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.preview.session = camera.session
        view.preview.videoGravity = .resizeAspectFill
        return view
    }

    func updateNSView(_ view: PreviewView, context: Context) {}
}
#endif

// MARK: - Eyes

/// Eyes: its face (shared/Eyes.swift), and below it what it says, its timers and words; asleep, the clock.
struct EyesTheme: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let v: CGFloat
    let size: CGSize

    var body: some View {
        let landscape = size.width > size.height
        let look = face.look
        let accent = face.color("accent", Color(hex: "#34aff7")!)
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                EyesFace(look: look, accent: accent,
                         voice: levels.voice, speech: levels.speech, v: v)
                    .scaleEffect(landscape ? 0.85 : 1)
                    .padding(.vertical, landscape ? -2 * v : 0)
                StatusLine(face: face).padding(.top, 27)
                TimerLines(face: face, size: (landscape ? 4.5 : 5) * v)
                    .padding(.top, (landscape ? 1.5 : 3) * v)
                if look != "asleep" {
                    // From 112 up to the space left down to the bottom: the eyes above don't move.
                    CaptionLines(face: face, accent: accent, minHeight: landscape ? 0 : 112)
                        .frame(width: size.width * (landscape ? 0.7 : 0.9))
                        .padding(.top, 10)
                        .layoutPriority(1)  // the space left goes to the words, not shared
                }
            }
            .padding(.top, size.height * (landscape ? 0.10 : 0.28))
            .endsTheFace()
            .padding(.bottom, 2 * v)  // the captions' area ends here (WordsArea, flexible)
            if look == "asleep" {
                Clock(face: face) { time, day in
                    HStack(alignment: .top) {
                        Text(day ?? "")
                        Spacer()
                        Text(time ?? "")
                    }
                    .font(.system(size: 5 * v))
                    .foregroundColor(grey)
                    .padding(.horizontal, 4 * v)
                    .padding(.top, 3 * v)
                }
            }
        }
        .frame(width: size.width, height: size.height, alignment: .top)
    }
}

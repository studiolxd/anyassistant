// The four themes, drawn natively: Eyes, Orb, Bedside and Minimal (plugins/page/themes: the same
// looks, sizes in «v» = 1% of the screen's shorter side, as the CSS's vmin). A theme the app
// doesn't have yet is drawn as Eyes.

import AVFoundation
import SwiftUI

struct ThemeView: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let camera: Camera

    @State private var faceEnd: CGFloat = 0  // where the theme's face and words end (FaceEnd)

    var body: some View {
        ZStack {
            // The background to the screen's edges; the face, its words, the clock and the camera
            // inside the safe area (not under the Dynamic Island, the home bar or a window's title).
            face.background.ignoresSafeArea()
            GeometryReader { geometry in
                content(geometry.size)
            }
        }
    }

    @ViewBuilder func content(_ size: CGSize) -> some View {
        let v = min(size.width, size.height) / 100
        ZStack(alignment: .top) {
                switch face.theme {
                case "orb": OrbTheme(face: face, levels: levels, v: v, size: size)
                case "bedside": BedsideTheme(face: face, levels: levels, v: v, size: size)
                case "minimal": MinimalTheme(face: face, levels: levels, v: v, size: size)
                default: EyesTheme(face: face, levels: levels, v: v, size: size)
                }
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

// MARK: - Motion

/// A looping track of keyframes (fraction 0…1, value): held where two keys are equal, eased between.
func track(_ t: Double, period: Double, _ keys: [(Double, CGPoint)]) -> CGPoint {
    let p = t.truncatingRemainder(dividingBy: period) / period
    for i in 0..<(keys.count - 1) where p >= keys[i].0 && p <= keys[i + 1].0 {
        let (a, from) = keys[i], (b, to) = keys[i + 1]
        let f = b > a ? (p - a) / (b - a) : 0
        let e = f < 0.5 ? 2 * f * f : 1 - pow(-2 * f + 2, 2) / 2
        return CGPoint(x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e)
    }
    return keys.last?.1 ?? .zero
}

/// 0 → 1 → 0, eased, over a period (CSS «alternate»).
func swing(_ t: Double, period: Double) -> Double {
    let p = t.truncatingRemainder(dividingBy: 2 * period) / period
    let f = p <= 1 ? p : 2 - p
    return f < 0.5 ? 2 * f * f : 1 - pow(-2 * f + 2, 2) / 2
}

/// 0 → 1 → 0 smoothly, once a period.
func beat(_ t: Double, period: Double, delay: Double = 0) -> Double {
    0.5 - 0.5 * cos(2 * .pi * (t - delay) / period)
}

let grey = Color(white: 0.53)  // #888

// MARK: - Shared pieces

struct StatusLine: View {
    @ObservedObject var face: FaceModel
    var size: CGFloat = 22
    var color: Color = grey
    var weight: Font.Weight = .regular
    var alignment: TextAlignment = .center

    var body: some View {
        Text(face.status).font(.system(size: size, weight: weight)).foregroundColor(color)
            .multilineTextAlignment(alignment)
    }
}

struct TimerLines: View {
    @ObservedObject var face: FaceModel
    let size: CGFloat
    var color: Color = .white
    var icons = true
    var alignment: HorizontalAlignment = .center
    var spacing: CGFloat = 4

    var body: some View {
        if face.shows("show_timers") {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let now = context.date.timeIntervalSince1970
                VStack(alignment: alignment, spacing: spacing) {
                    ForEach(face.items.filter { $0.at > now - 1 }) { item in
                        HStack(spacing: size * 0.35) {
                            if icons { Image(systemName: Self.icon(item.kind)) }
                            Text(face.line(item, now: context.date)).monospacedDigit()
                        }
                    }
                }
                .font(.system(size: size))
                .foregroundColor(color)
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
    var older: Color = .white
    var olderOpacity = 0.6
    var height: CGFloat? = nil  // as WordsArea's
    var bottom: CGFloat? = nil
    var minHeight: CGFloat = 0

    var body: some View {
        let last = face.captions.last
        WordsArea(aim: last.map { face.aim($0.id, answer: $0.answer, text: $0.text) } ?? Aim(key: "", y: 0),
                  fresh: last?.id ?? "", height: height, bottom: bottom, minHeight: minHeight) {
            VStack(spacing: 5) {
                ForEach(face.captions) { caption in
                    let isLast = caption.id == last?.id
                    Text(caption.text)
                        .font(.system(size: isLast ? 24 : 17.6))
                        .foregroundColor(caption.assistant ? accent : isLast ? .white : older)
                        .opacity(isLast ? 1 : olderOpacity)
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
    static var defaultValue = CGSize.zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) { value = nextValue() }
}

/// The words (the captions, what you said, the answer) in their own area, as the page's: it scrolls
/// without a bar (a finger, the trackpad, the wheel) and follows `aim` (FaceModel.aim: the end of
/// what you said, the sentence the voice is saying); scrolled by hand, it stops following until
/// back at the end or new words arrive (`fresh` changes). A fade at the edge where there is more.
/// Its height: `height`, fixed (a centred column: so the face doesn't move); else as tall as the
/// words, from `minHeight` up to `most` and to `bottom` (in ThemeView's space: down to there).
struct WordsArea<Content: View>: View {
    let aim: Aim
    let fresh: String
    var height: CGFloat? = nil
    var most: CGFloat? = nil
    var bottom: CGFloat? = nil
    var minHeight: CGFloat = 0
    @ViewBuilder let content: () -> Content

    @State private var space = UUID().uuidString  // its scroll's own coordinate space
    @State private var top: CGFloat = 0  // where the area starts, in ThemeView's space
    @State private var offset: CGFloat = 0  // the words' top in the area: 0, or less when scrolled
    @State private var words: CGFloat = 0  // the words' height
    @State private var following = true
    @State private var auto = Date.distantPast  // until when the scrolling is its own

    private var view: CGFloat {
        if let height { return height }
        var most = self.most ?? .infinity
        if let bottom { most = min(most, bottom - top) }
        return max(minHeight, min(words, max(most, minHeight)))
    }

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
            .frame(height: view)
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
        .frame(height: view)
        .mask(VStack(spacing: 0) {
            LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom)
                .frame(height: offset < -1 ? 28 : 0)
            Color.black
            LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom)
                .frame(height: words + offset > view + 1 ? 28 : 0)
        })
        .background(GeometryReader { g in
            Color.clear
                .onAppear { top = g.frame(in: .named("theme")).minY }
                .onChange(of: g.frame(in: .named("theme")).minY) { top = $0 }
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

/// The time and the date, as each theme lays them out.
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

/// Where a theme's face and words end (in ThemeView's space): the camera goes below.
struct FaceEnd: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

extension View {
    /// Marks the end of the theme's face and words (each theme, on its column).
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

/// Two blue eyes that change shape to say how it feels: ovals, happy arcs (^ ^), closed (‿ ‿),
/// or cut by a lid (sad); floating, looking around, scanning, thinking.
struct EyesTheme: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let v: CGFloat
    let size: CGSize
    @State private var blink = false

    var body: some View {
        let landscape = size.width > size.height
        let look = face.look
        let accent = face.color("accent", Color(hex: "#34aff7")!)
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                faceBlock(look, accent)
                    .scaleEffect(landscape ? 0.85 : 1)
                    .padding(.vertical, landscape ? -2 * v : 0)
                StatusLine(face: face).padding(.top, 27)
                TimerLines(face: face, size: (landscape ? 4.5 : 5) * v)
                    .padding(.top, (landscape ? 1.5 : 3) * v)
                if look != "asleep" {
                    // From 112 up to the space left down to the bottom: the eyes above don't move.
                    CaptionLines(face: face, accent: accent, bottom: size.height - 2 * v, minHeight: landscape ? 0 : 112)
                        .frame(width: size.width * (landscape ? 0.7 : 0.9))
                        .padding(.top, 10)
                }
            }
            .padding(.top, size.height * (landscape ? 0.10 : 0.28))
            .endsTheFace()
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
        .task { await blinking() }
    }

    private func faceBlock(_ look: String, _ accent: Color) -> some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            ZStack(alignment: .bottom) {
                VStack(spacing: 0) {
                    eyes(look, accent, t)
                        .frame(height: 32 * v)
                    mouth(t, accent)
                        .frame(height: 10 * v)
                        .padding(.top, 3 * v)
                        .opacity(look == "speaking" ? 1 : 0)
                }
                dots(t, accent)
                    .frame(height: 10 * v)
                    .opacity(look == "thinking" ? 1 : 0)
            }
            .offset(y: look == "asleep" ? 0 : -2 * v * swing(t, period: 3.2))  // floating
        }
    }

    private func eyes(_ look: String, _ accent: Color, _ t: Double) -> some View {
        var move = CGPoint.zero
        var scale = 1.0
        switch look {
        case "awake":
            move = track(t, period: 9, [(0, .zero), (0.22, .zero), (0.25, CGPoint(x: -7, y: 1.5)), (0.45, CGPoint(x: -7, y: 1.5)),
                                        (0.48, CGPoint(x: 6, y: -3)), (0.60, CGPoint(x: 6, y: -3)), (0.63, CGPoint(x: 1, y: 3)),
                                        (0.80, CGPoint(x: 1, y: 3)), (0.83, CGPoint(x: 7, y: 1)), (0.97, CGPoint(x: 7, y: 1)), (1, .zero)])
        case "thinking":
            move = track(t, period: 4, [(0, CGPoint(x: -6, y: -4)), (0.3, CGPoint(x: -6, y: -4)), (0.5, CGPoint(x: 6, y: -4)),
                                        (0.8, CGPoint(x: 6, y: -4)), (1, CGPoint(x: -6, y: -4))])
        case "looking":
            move = track(t, period: 2.4, [(0, CGPoint(x: -9, y: 0)), (0.15, CGPoint(x: -9, y: 0)), (0.5, CGPoint(x: 9, y: 0)),
                                          (0.65, CGPoint(x: 9, y: 0)), (1, CGPoint(x: -9, y: 0))])
        case "hearing":
            scale = 1 + Double(levels.voice) * 0.25
        case "alarm":
            scale = 1 + 0.1 * beat(t, period: 0.6)
        case "error":
            move = CGPoint(x: 0, y: 3)
        default:
            break
        }
        return HStack(spacing: 10 * v) {
            eye(look, left: true, accent)
            eye(look, left: false, accent)
        }
        .scaleEffect(scale)
        .offset(x: move.x * v, y: move.y * v)
        .animation(.easeOut(duration: 0.3), value: look)
    }

    /// One eye: its size, and what covers part of it (a crescent: ‿ or ^; a lid: sad).
    private func eye(_ look: String, left: Bool, _ accent: Color) -> some View {
        var (width, height): (CGFloat, CGFloat) = (26, 17)
        var cover: CGFloat?  // where the background-coloured oval moves: up, a crescent below (‿); down, above (^)
        var lid: Double?
        switch look {
        case "asleep": (width, height, cover) = (26, 11, -3.5)
        case "hearing": (width, height) = (28, 20)
        case "looking": (width, height) = (27, 22)
        case "speaking": (width, height, cover) = (26, 13, 4)
        case "question": if left { (width, height) = (28, 23) } else { (width, height, cover) = (26, 13, 4) }
        case "alarm": (width, height) = (28, 23)
        case "error": lid = left ? -16 : 16
        default: break
        }
        let w = width * v, h = height * v
        return ZStack {
            Ellipse().fill(accent).frame(width: w, height: h)
            if let cover {
                Ellipse().fill(face.background).frame(width: w * 1.01, height: h).offset(y: cover * v)
            }
            if let lid {
                // As the page's: turned on its own centre, 62 % above the eye's (not around the
                // eye's, which swung it sideways).
                Rectangle().fill(face.background).frame(width: w * 1.8, height: h)
                    .rotationEffect(.degrees(lid)).offset(y: -0.62 * h)
            }
        }
        .frame(width: w, height: h)
        .clipShape(Ellipse())  // the lid and the cover only take from this eye, never its neighbour
        .scaleEffect(x: 1, y: blink ? 0.1 : 1)
        .rotationEffect(.degrees(left ? -7 : 7))
        .animation(.easeOut(duration: 0.2), value: look)
        .animation(.easeInOut(duration: 0.07), value: blink)
    }

    private func mouth(_ t: Double, _ accent: Color) -> some View {
        let speech = Double(levels.speech)
        let step = t * 60
        return HStack(spacing: 1.8 * v) {
            ForEach(0..<5) { i in
                let bar = 0.15 + min(speech * 1.6, 1) * (0.55 + 0.45 * sin(step / 3 + Double(i) * 1.7))
                RoundedRectangle(cornerRadius: 1.2 * v).fill(accent)
                    .frame(width: 2.4 * v, height: 9 * v)
                    .scaleEffect(x: 1, y: bar)
            }
        }
    }

    private func dots(_ t: Double, _ accent: Color) -> some View {
        HStack(spacing: 2.4 * v) {
            ForEach(0..<3) { i in
                let p = (t - Double(i) * 0.2).truncatingRemainder(dividingBy: 1.2) / 1.2
                let lit = p < 0 ? 0.2 : p < 0.4 ? 0.2 + 0.8 * p / 0.4 : p < 0.8 ? 1 - 0.8 * (p - 0.4) / 0.4 : 0.2
                Circle().fill(accent).frame(width: 2.6 * v, height: 2.6 * v).opacity(lit)
            }
        }
    }

    private func blinking() async {
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: UInt64((2.5 + Double.random(in: 0...4.5)) * 1e9))
            blink = true
            try? await Task.sleep(nanoseconds: 140_000_000)
            blink = false
        }
    }
}

// MARK: - Orb

/// A flat sphere that breathes, beats with your voice and sends out waves when it speaks.
struct OrbTheme: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let v: CGFloat
    let size: CGSize

    var tone: Color {
        switch face.look {
        case "asleep": return grey
        case "hearing": return Color(hex: "#7ff0c2")!
        case "thinking": return Color(hex: "#e0b54a")!
        case "looking": return Color(hex: "#cfd8dc")!
        case "speaking": return Color(hex: "#5bc6e8")!
        case "question": return Color(hex: "#a98cf0")!
        case "alarm": return Color(hex: "#ff7a45")!
        case "error": return Color(hex: "#e05555")!
        default: return face.color("accent", Color(hex: "#3ddc97")!)
        }
    }

    var body: some View {
        let landscape = size.width > size.height
        let look = face.look
        VStack(spacing: 0) {
            if look == "asleep" {
                Clock(face: face) { time, day in
                    VStack(spacing: 0) {
                        if let time { Text(time).font(.system(size: 24 * v, weight: .ultraLight)) }
                        if let day { Text(day).font(.system(size: 5 * v)).padding(.top, v).padding(.bottom, 4 * v) }
                    }
                    .foregroundColor(Color(white: 0.4))
                }
            }
            orb(look, side: (landscape ? 28 : 40) * v)
                .padding((landscape ? 2 : 3) * v)
            StatusLine(face: face).padding(.top, 27)
            TimerLines(face: face, size: (landscape ? 4.5 : 5) * v, color: Color(white: 0.73), icons: false)
                .padding(.top, (landscape ? 1.5 : 3) * v)
            if look != "asleep" {
                // A fixed height (the column is centred: so the sphere doesn't move); longer, it scrolls.
                CaptionLines(face: face, accent: tone, older: Color(white: 0.4), olderOpacity: 1,
                             height: landscape ? size.height * 0.2 : max(112, size.height * 0.2))
                    .frame(width: size.width * (landscape ? 0.7 : 0.9))
                    .padding(.top, 10)
            }
        }
        .endsTheFace()
        .frame(width: size.width, height: size.height)
        .animation(.easeInOut(duration: 0.4), value: look)
    }

    private func orb(_ look: String, side: CGFloat) -> some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let pulse: CGFloat = look == "speaking" ? 1 + levels.speech * 0.2
                : (look == "hearing" || look == "awake") ? 1 + levels.voice * 0.18 : 1
            ZStack {
                if look == "speaking" {
                    ForEach(0..<2) { i in
                        let p = (t + Double(i) * 0.8).truncatingRemainder(dividingBy: 1.6) / 1.6
                        Circle().stroke(tone, lineWidth: 0.6 * v)
                            .scaleEffect(0.9 + 0.8 * (1 - pow(1 - p, 2)))
                            .opacity(0.7 * (1 - p))
                    }
                }
                if look == "thinking" || look == "looking" {
                    Circle().trim(from: 0, to: 0.5).stroke(tone, style: StrokeStyle(lineWidth: 0.8 * v, lineCap: .butt))
                        .rotationEffect(.degrees(-135 + 360 * (t.truncatingRemainder(dividingBy: 1.1) / 1.1)))
                        .padding(-3.4 * v)
                }
                Circle().fill(tone)
                    .opacity(look == "asleep" ? 0.35 + 0.45 * beat(t, period: 5)
                             : look == "alarm" ? 1 - 0.4 * beat(t, period: 0.6) : 1)
                    .scaleEffect(look == "alarm" ? 1 - 0.15 * beat(t, period: 0.6) : 1)
            }
            .frame(width: side, height: side)
            .scaleEffect(look == "asleep" ? 0.55 : pulse)
        }
        .frame(width: side, height: side)
    }
}

// MARK: - Bedside

/// For the bedside table: only a dim time while asleep; awake, a grey ember and its answer.
struct BedsideTheme: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let v: CGFloat
    let size: CGSize

    var body: some View {
        let look = face.look
        let asleep = look == "asleep"
        let glow = face.color("glow", Color(hex: "#9ca3af")!)
        VStack(spacing: 0) {
            Clock(face: face) { time, day in
                VStack(spacing: 0) {
                    if let time {
                        Text(time).font(.system(size: (asleep ? 26 : 8) * v, weight: .ultraLight)).opacity(asleep ? 0.35 : 0.3)
                    }
                    if asleep, let day { Text(day).font(.system(size: 4 * v)).opacity(0.25) }
                }
            }
            TimelineView(.animation(minimumInterval: 1 / 30)) { context in
                let t = context.date.timeIntervalSinceReferenceDate
                let opacity = asleep ? 0 : look == "thinking" ? 0.6 - 0.35 * beat(t, period: 1.4)
                    : look == "alarm" ? 1 - 0.75 * beat(t, period: 0.7) : 0.6
                Circle().fill(look == "error" ? Color(hex: "#7f1d1d")! : glow)
                    .frame(width: 10 * v, height: 10 * v)
                    .scaleEffect(1 + levels.voice * 0.4 + levels.speech * 0.4)
                    .opacity(opacity)
            }
            .frame(width: 10 * v, height: 10 * v)
            .padding(.top, 6 * v).padding(.bottom, 3 * v)
            StatusLine(face: face, size: 4 * v, color: glow).opacity(asleep ? 0.2 : 0.5)
            TimerLines(face: face, size: 5 * v, color: glow, icons: false, spacing: 0).opacity(0.6).padding(.top, 3 * v)
            if !asleep, face.shows("show_answer") {
                // Four lines, always (the column is centred: so the ember doesn't move); longer, it scrolls.
                WordsArea(aim: face.aim("answer", answer: face.answerId, text: face.answer), fresh: face.answerId,
                          height: 25 * v) {
                    Text(face.answer).font(.system(size: 5 * v)).foregroundColor(glow).opacity(0.7)
                        .multilineTextAlignment(.center).frame(maxWidth: .infinity)
                        .fixedSize(horizontal: false, vertical: true).id("answer")
                }
                .frame(width: size.width * 0.8).padding(.top, 16)
            }
        }
        .endsTheFace()
        .foregroundColor(glow)
        .frame(width: size.width, height: size.height)
    }
}

// MARK: - Minimal

/// High contrast and large text: a light that changes with each state, and words.
struct MinimalTheme: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let v: CGFloat
    let size: CGSize

    var light: Color {
        switch face.look {
        case "asleep": return Color(white: 0.27)
        case "hearing": return Color(hex: "#00e676")!
        case "thinking", "looking": return Color(hex: "#ffd600")!
        case "speaking": return Color(hex: "#40c4ff")!
        case "question": return Color(hex: "#e040fb")!
        case "alarm": return Color(hex: "#ff6d00")!
        case "error": return Color(hex: "#ff1744")!
        default: return .white
        }
    }

    var body: some View {
        let landscape = size.width > size.height
        let look = face.look
        let asleep = look == "asleep"
        let ink = face.color("text", .white)
        let top = size.height * (landscape ? 0.34 : 0.40)
        ZStack(alignment: .topLeading) {
            if asleep {
                Clock(face: face) { time, day in
                    VStack(alignment: .leading, spacing: 2 * v) {
                        if let time { Text(time).font(.system(size: (landscape ? 15 : 22) * v, weight: .bold)) }
                        if let day { Text(day).font(.system(size: (landscape ? 5 : 6) * v)) }
                    }
                }
                .foregroundColor(ink)
                .frame(width: size.width - 12 * v, height: top - (landscape ? 2 : 4) * v, alignment: .bottomLeading)
                .padding(.leading, 6 * v)
            }
            VStack(alignment: .leading, spacing: 0) {
                TimelineView(.animation(minimumInterval: 1 / 30)) { context in
                    let t = context.date.timeIntervalSinceReferenceDate
                    let p = t.truncatingRemainder(dividingBy: 1.6) / 1.6
                    ZStack {
                        if !["asleep", "awake", "error"].contains(look) {
                            Circle().fill(light).scaleEffect(1 + p).opacity(0.6 * (1 - p))
                        }
                        Circle().fill(light)
                    }
                    .frame(width: 12 * v, height: 12 * v)
                    .scaleEffect(0.8 + levels.voice * 0.5 + levels.speech * 0.5)
                }
                .frame(width: 12 * v, height: 14 * v, alignment: .top)
                StatusLine(face: face, size: 9 * v, color: ink, weight: .bold, alignment: .leading)
                    .padding(.vertical, (landscape ? 2 : 4) * v)
                TimerLines(face: face, size: (landscape ? 5.5 : 7) * v, color: ink, icons: false, alignment: .leading, spacing: v)
                    .padding(.top, (landscape ? 1 : 3) * v)
                if !asleep {
                    // What you said: two lines at most (its end); the answer, the space down to the bottom.
                    if face.shows("show_heard"), !face.heard.isEmpty {
                        WordsArea(aim: Aim(key: "heard", y: 1), fresh: "\(face.heardCount)", most: 15 * v) {
                            Text(face.heard).font(.system(size: 6 * v)).opacity(0.75)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .fixedSize(horizontal: false, vertical: true).id("heard")
                        }
                        .padding(.bottom, 2 * v)
                    }
                    if face.shows("show_answer"), !face.answer.isEmpty {
                        WordsArea(aim: face.aim("answer", answer: face.answerId, text: face.answer), fresh: face.answerId,
                                  bottom: size.height - 4 * v) {
                            Text(face.answer).font(.system(size: 7 * v))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .fixedSize(horizontal: false, vertical: true).id("answer")
                        }
                    }
                }
            }
            .foregroundColor(ink)
            .padding(.top, top)
            .endsTheFace()
            .padding(.horizontal, 6 * v)
            .frame(width: size.width, alignment: .leading)
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        .animation(.easeInOut(duration: 0.3), value: look)
    }
}

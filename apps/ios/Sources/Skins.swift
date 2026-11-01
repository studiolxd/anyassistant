// The four skins, drawn natively: Eyes, Orb, Bedside and Minimal (plugins/page/skins: the same
// looks, sizes in «v» = 1% of the screen's shorter side, as the CSS's vmin). A skin the app
// doesn't have yet is drawn as Eyes.

import AVFoundation
import SwiftUI

struct SkinView: View {
    @ObservedObject var face: FaceModel
    @ObservedObject var levels: Levels
    let camera: Camera

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let v = min(size.width, size.height) / 100
            ZStack {
                face.background.ignoresSafeArea()
                switch face.skin {
                case "orb": OrbSkin(face: face, levels: levels, v: v, size: size)
                case "bedside": BedsideSkin(face: face, levels: levels, v: v, size: size)
                case "minimal": MinimalSkin(face: face, levels: levels, v: v, size: size)
                default: EyesSkin(face: face, levels: levels, v: v, size: size)
                }
                Windows(face: face, camera: camera, v: v, size: size)
            }
        }
        .ignoresSafeArea()
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

    var body: some View {
        VStack(spacing: 5) {
            ForEach(face.captions) { caption in
                let last = caption.id == face.captions.last?.id
                Text(caption.text)
                    .font(.system(size: last ? 24 : 17.6))
                    .foregroundColor(caption.assistant ? accent : last ? .white : older)
                    .opacity(last ? 1 : olderOpacity)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// The time and the date, as each skin lays them out.
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

/// The camera («muestra la cámara»: live, mirrored) and the photo it looks at (with a
/// scanning sweep while it thinks about it), over the face.
struct Windows: View {
    @ObservedObject var face: FaceModel
    let camera: Camera
    let v: CGFloat
    let size: CGSize

    var body: some View {
        let width = 80 * v, height = 60 * v
        ZStack {
            if face.cameraShown {
                CameraPreview(camera: camera)
                    .frame(width: width, height: height)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color(hex: "#5bc6e8")!, lineWidth: 2))
            }
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
struct EyesSkin: View {
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
                    CaptionLines(face: face, accent: accent)
                        .frame(width: size.width * (landscape ? 0.7 : 0.9))
                        .frame(minHeight: landscape ? 0 : 112, alignment: .top)
                        .padding(.top, 10)
                }
            }
            .padding(.top, size.height * (landscape ? 0.10 : 0.28))
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
            Ellipse().fill(accent)
            if let cover {
                Ellipse().fill(face.background).frame(width: w * 1.01, height: h).offset(y: cover * v)
            }
            if let lid {
                Rectangle().fill(face.background).frame(width: w * 1.8, height: h)
                    .offset(y: -0.62 * h).rotationEffect(.degrees(lid))
            }
        }
        .frame(width: w, height: h)
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
struct OrbSkin: View {
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
                CaptionLines(face: face, accent: tone, older: Color(white: 0.4), olderOpacity: 1)
                    .frame(width: size.width * (landscape ? 0.7 : 0.9))
                    .frame(minHeight: landscape ? 0 : 112, alignment: .top)
                    .padding(.top, 10)
            }
        }
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
struct BedsideSkin: View {
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
                Text(face.answer).font(.system(size: 5 * v)).foregroundColor(glow).opacity(0.7)
                    .multilineTextAlignment(.center).frame(width: size.width * 0.8).padding(.top, 16)
            }
        }
        .foregroundColor(glow)
        .frame(width: size.width, height: size.height)
    }
}

// MARK: - Minimal

/// High contrast and large text: a light that changes with each state, and words.
struct MinimalSkin: View {
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
                    if face.shows("show_heard"), !face.heard.isEmpty {
                        Text(face.heard).font(.system(size: 6 * v)).opacity(0.75).padding(.bottom, 2 * v)
                    }
                    if face.shows("show_answer"), !face.answer.isEmpty {
                        Text(face.answer).font(.system(size: 7 * v))
                    }
                }
            }
            .foregroundColor(ink)
            .padding(.top, top)
            .padding(.horizontal, 6 * v)
            .frame(width: size.width, alignment: .leading)
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
        .animation(.easeInOut(duration: 0.3), value: look)
    }
}

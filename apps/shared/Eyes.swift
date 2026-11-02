// The theme Eyes' face (plugins/page/themes/eyes: the same look, sizes in «v» = 1% of the screen's
// shorter side, as the CSS's vmin): two eyes that change shape to say how it feels, the mouth while
// it speaks, the dots while it thinks. The iPhone, iPad and Mac draw it with its words, timers and
// clock around it (ios/Sources/Themes.swift: EyesTheme); the Apple Watch, alone (apps/watch).

import SwiftUI

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

// MARK: - The face

/// Two eyes that change shape to say how it feels: ovals, happy arcs (^ ^), closed (‿ ‿), or cut
/// by a lid (sad); floating, looking around, scanning, thinking. Below them, the mouth (speaking)
/// or the dots (thinking). Its size: 62 v wide, 45 v high.
struct EyesFace: View {
    /// The state as the themes draw it: awake, asleep, hearing, thinking, speaking, looking,
    /// question, alarm, error.
    let look: String
    let accent: Color
    let background: Color
    /// The voice heard and the voice said, 0…1 (the eyes grow with one, the mouth moves with the other).
    let voice: CGFloat
    let speech: CGFloat
    let v: CGFloat
    @State private var blink = false

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            ZStack(alignment: .bottom) {
                VStack(spacing: 0) {
                    eyes(t)
                        .frame(height: 32 * v)
                    mouth(t)
                        .frame(height: 10 * v)
                        .padding(.top, 3 * v)
                        .opacity(look == "speaking" ? 1 : 0)
                }
                dots(t)
                    .frame(height: 10 * v)
                    .opacity(look == "thinking" ? 1 : 0)
            }
            .offset(y: look == "asleep" ? 0 : -2 * v * swing(t, period: 3.2))  // floating
        }
        .task { await blinking() }
    }

    private func eyes(_ t: Double) -> some View {
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
            scale = 1 + Double(voice) * 0.25
        case "alarm":
            scale = 1 + 0.1 * beat(t, period: 0.6)
        case "error":
            move = CGPoint(x: 0, y: 3)
        default:
            break
        }
        return HStack(spacing: 10 * v) {
            eye(left: true)
            eye(left: false)
        }
        .scaleEffect(scale)
        .offset(x: move.x * v, y: move.y * v)
        .animation(.easeOut(duration: 0.3), value: look)
    }

    /// One eye: its size, and what covers part of it (a crescent: ‿ or ^; a lid: sad).
    private func eye(left: Bool) -> some View {
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
                Ellipse().fill(background).frame(width: w * 1.01, height: h).offset(y: cover * v)
            }
            if let lid {
                // As the page's: turned on its own centre, 62 % above the eye's (not around the
                // eye's, which swung it sideways).
                Rectangle().fill(background).frame(width: w * 1.8, height: h)
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

    private func mouth(_ t: Double) -> some View {
        let said = Double(speech)
        let step = t * 60
        return HStack(spacing: 1.8 * v) {
            ForEach(0..<5) { i in
                let bar = 0.15 + min(said * 1.6, 1) * (0.55 + 0.45 * sin(step / 3 + Double(i) * 1.7))
                RoundedRectangle(cornerRadius: 1.2 * v).fill(accent)
                    .frame(width: 2.4 * v, height: 9 * v)
                    .scaleEffect(x: 1, y: bar)
            }
        }
    }

    private func dots(_ t: Double) -> some View {
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

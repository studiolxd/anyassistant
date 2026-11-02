// A timer's countdown while it runs, as the Clock's: on the Lock Screen (the eyes, what it is, the
// time left large and its bar) and in the Dynamic Island (the eyes and the time; open, its bar
// too). The phone's own timers (AlarmKit: Alarms.swift) show it; when it rings, the system's
// alert takes over. iOS 26 or later.

import ActivityKit
import AlarmKit
import SwiftUI
import WidgetKit

@main
struct LiveTimers: WidgetBundle {
    var body: some Widget {
        LiveTimer()
    }
}

private let blue = Color(red: 0x34 / 255, green: 0xaf / 255, blue: 0xf7 / 255)

struct LiveTimer: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AlarmAttributes<Ringing>.self) { context in
            LockScreen(title: context.attributes.metadata?.title ?? "", mode: context.state.mode)
                .activityBackgroundTint(.black.opacity(0.75))
                .activitySystemActionForegroundColor(blue)
        } dynamicIsland: { context in
            let title = context.attributes.metadata?.title ?? ""
            let mode = context.state.mode
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 6) {
                        Mark(size: 26)
                        Text(title).font(.headline).lineLimit(1)
                    }
                    .padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Left(mode: mode).font(.system(.title2, design: .rounded).weight(.semibold)).foregroundStyle(blue)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    Bar(mode: mode).padding(.horizontal, 4)
                }
            } compactLeading: {
                Mark(size: 22)
            } compactTrailing: {
                Left(mode: mode).font(.system(.body, design: .rounded).weight(.semibold)).foregroundStyle(blue)
                    .frame(maxWidth: 56)
            } minimal: {
                Image(systemName: "timer").foregroundStyle(blue)
            }
            .keylineTint(blue)
        }
    }
}

/// The time left: counting down (iOS redraws it), still while paused, 0:00 when it rings.
struct Left: View {
    let mode: AlarmPresentationState.Mode

    var body: some View {
        switch mode {
        case .countdown(let countdown):
            Text(timerInterval: Date()...countdown.fireDate, countsDown: true).monospacedDigit()
                .multilineTextAlignment(.trailing)
        case .paused(let paused):
            Text(Duration.seconds(paused.totalCountdownDuration - paused.previouslyElapsedDuration),
                 format: .time(pattern: .minuteSecond)).monospacedDigit()
        default:
            Text("0:00").monospacedDigit()
        }
    }
}

/// How much is left, as a bar.
struct Bar: View {
    let mode: AlarmPresentationState.Mode

    var body: some View {
        switch mode {
        case .countdown(let countdown):
            ProgressView(timerInterval: countdown.fireDate.addingTimeInterval(-countdown.totalCountdownDuration)...countdown.fireDate,
                         countsDown: true) { EmptyView() } currentValueLabel: { EmptyView() }
                .tint(blue)
        case .paused(let paused):
            ProgressView(value: max(0, paused.totalCountdownDuration - paused.previouslyElapsedDuration),
                         total: max(1, paused.totalCountdownDuration))
                .tint(blue)
        default:
            ProgressView(value: 0).tint(blue)
        }
    }
}

/// On the Lock Screen: the eyes and what it is; the time left large; its bar.
struct LockScreen: View {
    let title: String
    let mode: AlarmPresentationState.Mode

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center) {
                Mark(size: 34)
                Text(title).font(.headline).foregroundStyle(.white).lineLimit(1)
                Spacer(minLength: 8)
                Left(mode: mode).font(.system(size: 36, weight: .semibold, design: .rounded)).foregroundStyle(blue)
            }
            Bar(mode: mode)
        }
        .padding(16)
    }
}

/// The eyes, still: two ovals tilted −7° and +7°, as the icon.
struct Mark: View {
    let size: CGFloat

    var body: some View {
        HStack(spacing: size * 0.16) {
            Ellipse().frame(width: size * 0.42, height: size * 0.28).rotationEffect(.degrees(-7))
            Ellipse().frame(width: size * 0.42, height: size * 0.28).rotationEffect(.degrees(7))
        }
        .foregroundStyle(blue)
        .frame(width: size, height: size * 0.4)
    }
}

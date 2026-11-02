// The complication: what is next (a timer, an alarm or a reminder) on the watch face, and the eyes
// when nothing is. Round, wide, a line or a corner, as each face has room for. A timer counts down
// by itself (watchOS redraws it); when one rings, the next one shows (its timeline has an entry at
// each). Touching it opens AnyAssistant, listening. What it shows: Upcoming (the App Group).

import SwiftUI
import WidgetKit

struct Entry: TimelineEntry {
    let date: Date
    let next: Upcoming?
}

struct Provider: TimelineProvider {
    /// While the face is chosen: a timer, as an example.
    private var example: Upcoming {
        Upcoming(kind: "timer", at: Date().addingTimeInterval(504), label: "", set: Date().addingTimeInterval(-96))
    }

    func placeholder(in context: Context) -> Entry {
        Entry(date: Date(), next: example)
    }

    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
        completion(Entry(date: Date(), next: context.isPreview ? example : Upcoming.all().first))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
        let now = Date()
        let coming = Upcoming.all(after: now)
        // Now the first; when it rings, the one after it; and so on.
        var entries = [Entry(date: now, next: coming.first)]
        for (i, item) in coming.enumerated() {
            entries.append(Entry(date: item.at, next: i + 1 < coming.count ? coming[i + 1] : nil))
        }
        completion(Timeline(entries: entries, policy: .after(coming.last?.at ?? now.addingTimeInterval(3600))))
    }
}

@main
struct NextComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "next", provider: Provider()) { entry in
            NextView(next: entry.next)
                .containerBackground(for: .widget) { Color.clear }
        }
        .configurationDisplayName("AnyAssistant")
        .description(Text("What is next: a timer, an alarm or a reminder."))
        .supportedFamilies([.accessoryRectangular, .accessoryCircular, .accessoryCorner, .accessoryInline])
    }
}

// MARK: - Each size

private let blue = Color(red: 0x34 / 255, green: 0xaf / 255, blue: 0xf7 / 255)

struct NextView: View {
    @Environment(\.widgetFamily) private var family
    let next: Upcoming?

    var body: some View {
        switch family {
        case .accessoryRectangular: Rectangular(next: next)
        case .accessoryCorner: Corner(next: next)
        case .accessoryInline: Inline(next: next)
        default: Circular(next: next)
        }
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
        .widgetAccentable()
    }
}

/// When it rings, said short: «7:30», «mañana 7:30», «lun 7:30».
func when(_ date: Date) -> String {
    let calendar = Calendar.current
    let time = date.formatted(date: .omitted, time: .shortened)
    if calendar.isDateInToday(date) { return time }
    if calendar.isDateInTomorrow(date) { return NSLocalizedString("tomorrow", comment: "") + " " + time }
    return date.formatted(.dateTime.weekday(.abbreviated)) + " " + time
}

/// The big one: the eyes and what it is; below, how long is left (and its bar) or when.
struct Rectangular: View {
    let next: Upcoming?

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 5) {
                Mark(size: 18)
                Text(next?.title ?? "AnyAssistant").font(.headline).foregroundStyle(blue)
                    .widgetAccentable().lineLimit(1)
            }
            if let next, next.kind == "timer", let set = next.set {
                Text(timerInterval: Date()...next.at, countsDown: true)
                    .font(.system(.title2, design: .rounded).weight(.semibold)).monospacedDigit()
                ProgressView(timerInterval: set...next.at, countsDown: true) { EmptyView() } currentValueLabel: { EmptyView() }
                    .tint(blue)
            } else if let next {
                // The icon small beside it: as big as the hour, it left no room for it («20:…»).
                HStack(spacing: 4) {
                    Image(systemName: next.icon).font(.body).foregroundStyle(blue).widgetAccentable()
                    Text(when(next.at)).font(.system(.title3, design: .rounded).weight(.semibold))
                        .lineLimit(1).minimumScaleFactor(0.6)
                }
            } else {
                Text("Tap to talk").font(.body).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Round: a timer's ring with the time left; an alarm's or a reminder's hour; or the eyes.
struct Circular: View {
    let next: Upcoming?

    var body: some View {
        if let next, next.kind == "timer", let set = next.set {
            ProgressView(timerInterval: set...next.at, countsDown: true) {
                Image(systemName: "timer")
            } currentValueLabel: {
                Text(timerInterval: Date()...next.at, countsDown: true).monospacedDigit()
            }
            .progressViewStyle(.circular)
            .tint(blue)
        } else if let next {
            ZStack {
                AccessoryWidgetBackground()
                VStack(spacing: 0) {
                    Image(systemName: next.icon).font(.system(size: 13)).foregroundStyle(blue).widgetAccentable()
                    Text(next.at.formatted(date: .omitted, time: .shortened)).font(.system(size: 13, weight: .semibold))
                        .minimumScaleFactor(0.6)
                }
            }
        } else {
            ZStack {
                AccessoryWidgetBackground()
                Mark(size: 34)
            }
        }
    }
}

/// A line above the time: «⏱ Pasta 8:21», «⏰ Alarma · mañana 7:30».
struct Inline: View {
    let next: Upcoming?

    var body: some View {
        if let next, next.kind == "timer" {
            Text(Image(systemName: "timer")) + Text(" \(next.title) ") + Text(timerInterval: Date()...next.at, countsDown: true)
        } else if let next {
            Text(Image(systemName: next.icon)) + Text(" \(next.title) · \(when(next.at))")
        } else {
            Text("AnyAssistant")
        }
    }
}

/// A corner of the round faces: the icon, and the time curved along the edge.
struct Corner: View {
    let next: Upcoming?

    var body: some View {
        if let next {
            Image(systemName: next.icon).font(.title2).foregroundStyle(blue).widgetAccentable()
                .widgetLabel {
                    if next.kind == "timer" {
                        Text(timerInterval: Date()...next.at, countsDown: true)
                    } else {
                        Text(when(next.at))
                    }
                }
        } else {
            Mark(size: 30)
        }
    }
}

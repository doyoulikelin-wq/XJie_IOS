import SwiftUI

/// Markdown 渲染文本视图 — 使用 iOS 15+ AttributedString
struct MarkdownTextView: View {
    let text: String

    var body: some View {
        AccessibleMarkdownText(text: text)
            .font(.subheadline)
            .foregroundColor(.appText)
            .multilineTextAlignment(.leading)
    }
}

struct AccessibleMarkdownText: View {
    let text: String

    @ViewBuilder
    var body: some View {
        let rendering = AccessibleMarkdownRenderer.render(text)
        if let rendered = rendering.attributed {
            Text(rendered)
                .accessibilityRepresentation {
                    if rendering.accessibilitySegments.contains(where: { $0.link != nil }) {
                        AccessibleMarkdownAccessibilityRepresentation(
                            segments: rendering.accessibilitySegments
                        )
                    } else {
                        Text(verbatim: rendering.accessibilityText)
                    }
                }
        } else {
            Text(verbatim: text)
                .accessibilityRepresentation {
                    Text(verbatim: text)
                }
        }
    }
}

struct AccessibleMarkdownAccessibilitySegment: Equatable, Identifiable {
    let id: Int
    var text: String
    let link: URL?
}

private struct AccessibleMarkdownAccessibilityRepresentation: View {
    let segments: [AccessibleMarkdownAccessibilitySegment]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(segments) { segment in
                if let link = segment.link {
                    Link(destination: link) {
                        Text(verbatim: segment.text)
                    }
                    .accessibilityAddTraits(.isLink)
                } else {
                    Text(verbatim: segment.text)
                }
            }
        }
    }
}

struct AccessibleMarkdownRendering {
    let attributed: AttributedString?
    let accessibilityText: String
    let accessibilitySegments: [AccessibleMarkdownAccessibilitySegment]
}

enum AccessibleMarkdownRenderer {
    private static let autolinkCandidatePattern =
        #"(?i)(?:://|www\.|mailto:|@)"#

    static func render(_ content: String) -> AccessibleMarkdownRendering {
        let plain = AccessibleMarkdownRendering(
            attributed: nil,
            accessibilityText: content,
            accessibilitySegments: [
                AccessibleMarkdownAccessibilitySegment(id: 0, text: content, link: nil)
            ]
        )
        guard containsPotentialMarkdown(content),
              let rendered = try? AttributedString(
                markdown: content,
                options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
              )
        else {
            return plain
        }

        let accessibilityText = String(rendered.characters)
        let hasPresentationAttributes = rendered.runs.contains { run in
            run.inlinePresentationIntent != nil || run.presentationIntent != nil || run.link != nil
        }
        guard accessibilityText != content || hasPresentationAttributes else {
            return plain
        }
        return AccessibleMarkdownRendering(
            attributed: rendered,
            accessibilityText: accessibilityText,
            accessibilitySegments: accessibilitySegments(from: rendered)
        )
    }

    private static func accessibilitySegments(
        from rendered: AttributedString
    ) -> [AccessibleMarkdownAccessibilitySegment] {
        var segments: [AccessibleMarkdownAccessibilitySegment] = []
        for run in rendered.runs {
            let text = String(rendered[run.range].characters)
            guard !text.isEmpty else { continue }
            if let lastIndex = segments.indices.last,
               segments[lastIndex].link == run.link {
                segments[lastIndex].text += text
            } else {
                segments.append(
                    AccessibleMarkdownAccessibilitySegment(
                        id: segments.count,
                        text: text,
                        link: run.link
                    )
                )
            }
        }
        return segments
    }

    private static func containsPotentialMarkdown(_ content: String) -> Bool {
        if ["*", "_", "~", "`", "[", "<", "\\", "&"].contains(where: content.contains) {
            return true
        }
        if content.unicodeScalars.contains(where: { $0.value == 0x0D || $0.value == 0 }) {
            return true
        }
        return content.range(of: autolinkCandidatePattern, options: .regularExpression) != nil
    }
}

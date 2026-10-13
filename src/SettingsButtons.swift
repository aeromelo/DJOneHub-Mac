import SwiftUI

struct SettingsActionButtonStyle: ButtonStyle {
    var destructive = false
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        let color = destructive
            ? Color(red: 0.80, green: 0.16, blue: 0.20)
            : Color(red: 0.12, green: 0.54, blue: 0.28)
        return configuration.label
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .foregroundStyle(isEnabled ? Color.white : Color.secondary)
            .background {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(isEnabled ? color.opacity(configuration.isPressed ? 0.78 : 1)
                                    : Color.primary.opacity(0.12))
            }
            .contentShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}

import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool danger: false
    property bool quiet: false
    property bool small: false
    property string glyph: ""
    implicitHeight: small ? 34 : 44
    implicitWidth: Math.max(small ? 72 : 102, textLabel.implicitWidth + (glyph.length ? 52 : 32))
    hoverEnabled: true
    padding: 0
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    background: Rectangle {
        id: background
        radius: control.small ? 10 : 13
        color: !control.enabled ? "#29303B" :
               control.down ? (control.primary ? "#C4CBD4" :
                               control.danger ? "#6A343D" : "#475361") :
               control.primary ? (control.hovered ? "#FFFFFF" : "#E4E9F0") :
               control.danger ? (control.hovered ? "#593036" : "#44252C") :
               control.quiet ? (control.hovered ? "#4A515C" : "#303740") :
               (control.hovered ? "#44505E" : "#313B48")
        opacity: control.enabled ? 1 : 0.52
        Behavior on color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
    }
    contentItem: Item {
        Row {
            spacing: 7
            anchors.centerIn: parent
            Text {
                visible: control.glyph.length > 0
                text: control.glyph
                color: !control.enabled ? "#AAB5C2" :
                       control.primary ? "#18202B" : "#E2E9F2"
                font.pixelSize: control.small ? 13 : 16
                font.family: "Segoe UI Symbol"
            }
            Text {
                id: textLabel
                text: control.text
                font.family: "Segoe UI"
                font.pixelSize: control.small ? 12 : 14
                font.weight: control.primary ? Font.DemiBold : Font.Medium
                color: !control.enabled ? "#AAB5C2" :
                       control.primary ? "#111820" : "#F0F4FA"
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}

import QtQuick
import QtQuick.Controls

TextField {
    id: field
    implicitHeight: 44
    font.family: "Segoe UI"
    font.pixelSize: 13
    color: "#EAF0F7"
    placeholderTextColor: "#8492A4"
    selectionColor: "#7088A0"
    selectedTextColor: "#FFFFFF"
    leftPadding: 14
    rightPadding: 14
    verticalAlignment: TextInput.AlignVCenter
    background: Rectangle {
        radius: 12
        color: field.activeFocus ? "#333D4A" : "#222B37"
        border.width: field.activeFocus ? 1 : 0
        border.color: "#7E96B1"
        Behavior on color { ColorAnimation { duration: 160 } }
    }
}

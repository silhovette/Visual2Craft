import QtQuick
import QtQuick.Controls

ComboBox {
    id: combo
    implicitHeight: 44
    hoverEnabled: true
    font.family: "Segoe UI"
    font.pixelSize: 13
    leftPadding: 13
    rightPadding: 13
    HoverHandler { cursorShape: combo.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    background: Rectangle {
        color: combo.hovered || combo.popup.visible ? "#344050" : "#232C38"
        radius: 12
        Behavior on color { ColorAnimation { duration: 150 } }
    }
    contentItem: Text {
        leftPadding: 13
        rightPadding: 13
        text: combo.displayLabel(combo.displayText || "Select…")
        color: combo.enabled ? "#E6EDF7" : "#8994A3"
        font: combo.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    delegate: ItemDelegate {
        width: combo.width - 12
        height: 38
        text: combo.displayLabel(modelData)
        font: combo.font
        highlighted: combo.highlightedIndex === index
        contentItem: Text {
            text: parent.text
            color: "#E5ECF5"
            font: combo.font
            leftPadding: 13
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: parent.highlighted || parent.hovered ? "#415063" : "transparent"
        }
    }

    function displayLabel(value) {
        var label = String(value === undefined || value === null ? "" : value)
        var separator = label.indexOf("·")
        return separator >= 0 ? label.slice(0, separator).trim() : label
    }

    popup: Popup {
        y: combo.height + 6
        width: combo.width
        implicitHeight: Math.min(listView.contentHeight + 12, 270)
        padding: 6
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: 13
            color: "#252E3A"
            border.width: 1
            border.color: "#425065"
        }
        contentItem: ListView {
            id: listView
            clip: true
            model: combo.delegateModel
            currentIndex: combo.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }
    }
}

import QtQuick
import QtQuick3D

Item {
    id: root
    property var studio
    property var blockGeometry
    property color panelColor: "#101923"

    Rectangle {
        anchors.fill: parent
        radius: 17
        color: root.panelColor
        border.color: "#40536375"
        border.width: 1
        clip: true
    }

    View3D {
        id: view
        anchors.fill: parent
        anchors.margins: 1
        renderMode: View3D.Offscreen
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#101923"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        Node {
            id: orbit
            eulerRotation: Qt.vector3d(-28, 42, 0)
            PerspectiveCamera {
                id: camera
                position: Qt.vector3d(0, 0, root.studio && root.studio.blockCount > 0
                                      ? Math.max(12, Math.min(150, root.blockGeometry.radiusValue * 2.8)) : 18)
                clipNear: 0.1
                clipFar: 300
            }
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-42, -32, 0)
            brightness: 1.2
            color: "#F4E8D2"
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(35, 145, 0)
            brightness: 0.42
            color: "#9FC8F4"
        }
        Model {
            id: blockModel
            geometry: root.blockGeometry
            visible: root.studio && root.studio.blockCount > 0
            castsShadows: true
            receivesShadows: true
            materials: DefaultMaterial {
                lighting: DefaultMaterial.FragmentLighting
                vertexColorsEnabled: true
                diffuseColor: "#FFFFFF"
                specularAmount: 0.12
                blendMode: DefaultMaterial.SourceOver
            }
        }
        Model {
            source: "#Cube"
            scale: Qt.vector3d(root.studio && root.studio.blockCount > 0
                               ? Math.max(22, root.blockGeometry.radiusValue * 2.2) : 22,
                               0.035,
                               root.studio && root.studio.blockCount > 0
                               ? Math.max(22, root.blockGeometry.radiusValue * 2.2) : 22)
            position: Qt.vector3d(0, root.blockGeometry.floorY - 0.03, 0)
            materials: DefaultMaterial {
                diffuseColor: "#1D2A36"
                lighting: DefaultMaterial.FragmentLighting
            }
        }
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.top: parent.top
        anchors.topMargin: 14
        text: root.studio ? root.studio.sceneStatus : "Live Reconstruction"
        color: "#C9D7E5"
        font.pixelSize: 11
        elide: Text.ElideRight
        width: Math.max(100, parent.width - 210)
    }
    Text {
        anchors.centerIn: parent
        visible: root.studio && root.studio.blockCount === 0
        text: root.studio ? root.studio.sceneStatus : "Waiting for a validated scene…"
        color: "#8EA5BA"
        font.pixelSize: 13
        horizontalAlignment: Text.AlignHCenter
        width: parent.width - 48
        wrapMode: Text.Wrap
    }
    MouseArea {
        anchors.fill: parent
        anchors.topMargin: 42
        anchors.bottomMargin: 28
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        property real lastX: 0
        property real lastY: 0
        onPressed: { lastX = mouse.x; lastY = mouse.y }
        onPositionChanged: {
            var dx = mouse.x - lastX
            var dy = mouse.y - lastY
            lastX = mouse.x; lastY = mouse.y
            if (pressedButtons & Qt.MiddleButton) {
                orbit.position.x += dx * 0.025
                orbit.position.y -= dy * 0.025
            } else if (pressedButtons & Qt.LeftButton) {
                orbit.eulerRotation.y -= dx * 0.45
                orbit.eulerRotation.x = Math.max(-88, Math.min(8, orbit.eulerRotation.x - dy * 0.35))
            }
        }
        onWheel: {
            camera.position.z = Math.max(6, Math.min(180, camera.position.z - wheel.angleDelta.y / 120 * 2))
            wheel.accepted = true
        }
    }
    SequentialAnimation {
        id: buildPulse
        NumberAnimation { target: blockModel; property: "opacity"; from: 0.55; to: 1.0; duration: 280; easing.type: Easing.OutCubic }
    }
    Connections {
        target: root.studio
        function onSceneChanged() { buildPulse.restart() }
    }
}

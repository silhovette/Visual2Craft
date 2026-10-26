import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "components"

ApplicationWindow {
    id: window
    width: 1480
    height: 895
    minimumWidth: 1060
    minimumHeight: 690
    // The Python launcher shows the window only after the QML scene exists.
    // This prevents the native window from exposing its default white frame.
    visible: false
    title: "Visual2Craft"
    color: "#000000"
    font.family: "Segoe UI"

    property string provider: "chatgpt"
    property string previewMode: "source"
    property color white: "#F1F5FA"
    property color muted: "#A2B0C1"
    property bool splashActive: true
    property var splashLogoAlternatives: [
        "../assets/visual2craft-logo (10).png",
        "../assets/visual2craft-logo (1).png",
        "../assets/visual2craft-logo (3).png",
        "../assets/visual2craft-logo (4).png",
        "../assets/visual2craft-logo (5).png",
        "../assets/visual2craft-logo (6).png",
        "../assets/visual2craft-logo (7).png",
        "../assets/visual2craft-logo (8).png",
        "../assets/visual2craft-logo (9).png"
    ]
    property string splashLogoSource: chooseSplashLogo()

    function chooseSplashLogo() {
        // Keep the unnumbered logo rare (1%); the other nine share the remaining 99%.
        if (Math.random() < 0.01) return "../assets/visual2craft-logo.png"
        return splashLogoAlternatives[Math.floor(Math.random() * splashLogoAlternatives.length)]
    }

    function skipSplash() {
        if (!splashActive) return
        splashAnimation.stop()
        splashLogo.opacity = 0
        splashLogo.scale = 1
        splashOverlay.opacity = 0
        splashOverlay.visible = false
        splashActive = false
    }

    Image {
        id: scenery
        anchors.fill: parent
        source: "../assets/scenery_2560.jpg"
        fillMode: Image.PreserveAspectCrop
        smooth: true
        asynchronous: true
        cache: true
    }
    Rectangle { anchors.fill: parent; color: "#85070C15" }

    // Keep the finished studio underneath the splash while its first frame settles.
    // The local logo is loaded synchronously so the fade never starts on an empty frame.
    Rectangle {
        id: splashOverlay
        z: 2000
        anchors.fill: parent
        color: "#000000"
        opacity: 1
        visible: opacity > 0

        Image {
            id: splashLogo
            anchors.centerIn: parent
            width: Math.min(parent.width * 0.68, 760)
            height: Math.min(parent.height * 0.24, 210)
            source: window.splashLogoSource
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            opacity: 0
            scale: 0.965
        }

        MouseArea {
            anchors.fill: parent
            enabled: window.splashActive
            hoverEnabled: false
            onClicked: mouse.accepted = true
        }

        SequentialAnimation {
            id: splashAnimation
            running: true

            PauseAnimation { duration: 180 }
            ParallelAnimation {
                NumberAnimation {
                    target: splashLogo
                    property: "opacity"
                    to: 1
                    duration: 620
                    easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    target: splashLogo
                    property: "scale"
                    to: 1
                    duration: 760
                    easing.type: Easing.OutCubic
                }
            }
            // Hold the fully visible logo before the shared fade-out begins.
            PauseAnimation { duration: 1120 }
            ParallelAnimation {
                NumberAnimation {
                    target: splashLogo
                    property: "opacity"
                    to: 0
                    duration: 560
                    easing.type: Easing.InOutCubic
                }
                NumberAnimation {
                    target: splashOverlay
                    property: "opacity"
                    to: 0
                    duration: 720
                    easing.type: Easing.InOutCubic
                }
            }
            ScriptAction {
                script: {
                    window.splashActive = false
                    splashOverlay.visible = false
                }
            }
        }
    }

    RowLayout {
        id: mainLayout
        anchors.fill: parent
        anchors.margins: window.width < 1200 ? 18 : 28
        spacing: 18

        // The complete settings form stays together in the large left panel.
        StudioCard {
            id: settingsCard
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: window.width * 0.53
            Layout.minimumWidth: 430

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: window.width < 1200 ? 18 : 24
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Settings"
                        color: window.white
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#2EFFFFFF" }

                ScrollView {
                    id: settingsScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical.policy: ScrollBar.AlwaysOff

                    ColumnLayout {
                        id: form
                        width: settingsScroll.availableWidth
                        spacing: 10

                        FieldLabel { text: "AI CONNECTION"; font.letterSpacing: 1.2 }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            StudioButton {
                                Layout.fillWidth: true
                                text: "ChatGPT Plan"
                                primary: window.provider === "chatgpt"
                                small: true
                                enabled: !studio.busy
                                onClicked: window.provider = "chatgpt"
                            }
                            StudioButton {
                                Layout.fillWidth: true
                                text: "API key"
                                primary: window.provider === "api"
                                small: true
                                enabled: !studio.busy
                                onClicked: window.provider = "api"
                            }
                        }

                        ColumnLayout {
                            visible: window.provider === "chatgpt"
                            Layout.fillWidth: true
                            spacing: 9
                            FieldLabel { text: "Saved ChatGPT account" }
                            StudioCombo {
                                id: accountCombo
                                Layout.fillWidth: true
                                model: studio.accounts
                                currentIndex: studio.accountIndex
                                enabled: !studio.busy && studio.accounts.length > 0
                                onActivated: function(index) { studio.chooseAccount(index) }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 7
                                StudioButton {
                                    Layout.fillWidth: true
                                    text: studio.accounts.length ? "Reauthorize" : "Sign in"
                                    small: true
                                    enabled: !studio.busy
                                    onClicked: studio.signIn()
                                }
                                StudioButton {
                                    text: "Add account"
                                    small: true
                                    enabled: !studio.busy
                                    onClicked: studio.addAccount()
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 7
                                StudioButton {
                                    Layout.fillWidth: true
                                    text: "Refresh models"
                                    small: true
                                    enabled: !studio.busy && studio.accounts.length > 0
                                    onClicked: studio.refreshModels()
                                }
                                StudioButton {
                                    text: "Remove"
                                    danger: true
                                    small: true
                                    enabled: !studio.busy && studio.accounts.length > 0
                                    onClicked: studio.removeAccount()
                                }
                            }
                            FieldLabel { text: "Model" }
                            StudioCombo {
                                id: modelCombo
                                Layout.fillWidth: true
                                model: studio.models
                                currentIndex: studio.modelIndex
                                enabled: !studio.busy && studio.models.length > 0
                                onActivated: function(index) { studio.chooseModel(index) }
                            }
                        }

                        ColumnLayout {
                            visible: window.provider === "api"
                            Layout.fillWidth: true
                            spacing: 9
                            FieldLabel { text: "API key" }
                            StudioField {
                                id: apiKeyField
                                Layout.fillWidth: true
                                placeholderText: "sk-…"
                                echoMode: TextInput.Password
                                enabled: !studio.busy
                            }
                            FieldLabel { text: "Model" }
                            StudioField {
                                id: apiModelField
                                Layout.fillWidth: true
                                text: "gpt-5.5"
                                enabled: !studio.busy
                            }
                        }

                        Item { Layout.preferredHeight: 4 }
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#2AFFFFFF" }
                        Item { Layout.preferredHeight: 3 }

                        FieldLabel { text: "SAMPLE FRAMES"; font.letterSpacing: 1.2 }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            StudioField {
                                id: frameField
                                Layout.fillWidth: true
                                text: String(studio.defaultFrames)
                                validator: IntValidator { bottom: 2; top: 1200 }
                                inputMethodHints: Qt.ImhDigitsOnly
                                enabled: !studio.busy
                            }
                            Text {
                                text: "2 – 1200"
                                color: "#92A6BC"
                                font.pixelSize: 12
                            }
                        }
                        Item { Layout.preferredHeight: 5 }
                        FieldLabel { text: "OUTPUT DATA PACK"; font.letterSpacing: 1.2 }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 7
                            StudioField {
                                id: outputField
                                Layout.fillWidth: true
                                text: studio.outputPath
                                selectByMouse: true
                                onEditingFinished: studio.updateOutput(text)
                                enabled: !studio.busy
                            }
                            StudioButton {
                                text: "…"
                                small: true
                                enabled: !studio.busy
                                onClicked: studio.browseOutput()
                            }
                        }
                        Row {
                            Layout.fillWidth: true
                            StudioButton {
                                text: "Plan usage"
                                small: true
                                quiet: true
                                onClicked: studio.openUsage()
                            }
                        }

                        Item { Layout.preferredHeight: 4 }
                    }
                }
            }
        }

        // The right column follows the requested preview -> progress -> commands -> generate flow.
        ColumnLayout {
            id: rightColumn
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: window.width * 0.47
            Layout.minimumWidth: 360
            spacing: 14

            StudioCard {
                id: previewCard
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 235
                Layout.preferredHeight: 360

                Item {
                    anchors.fill: parent
                    anchors.margins: window.width < 1200 ? 10 : 14

                    Rectangle {
                        id: videoWell
                        anchors.fill: parent
                        radius: 17
                        color: "#7F080E17"
                        border.color: "#31536375"
                        border.width: 1
                        clip: true
                        z: 0

                        Item {
                            id: sourcePreview
                            anchors.fill: parent
                            opacity: window.previewMode === "source" ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 240; easing.type: Easing.InOutCubic } }

                            MediaPlayer {
                                id: player
                                source: studio.videoUrl
                                videoOutput: screen
                                audioOutput: AudioOutput { muted: true }
                                onSourceChanged: {
                                    if (studio.hasVideo) play()
                                    else stop()
                                }
                            }
                            VideoOutput {
                                id: screen
                                anchors.fill: parent
                                anchors.margins: 2
                                visible: studio.hasVideo
                                fillMode: VideoOutput.PreserveAspectCrop
                            }

                            Column {
                                visible: !studio.hasVideo
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 30, 400)
                                spacing: 10
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "Drop in a building tutorial"
                                    color: "#F0F4F9"
                                    font.pixelSize: 17
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "MP4  ·  MOV  ·  MKV  ·  AVI  ·  WEBM"
                                    color: "#A2B4C8"
                                    font.pixelSize: 11
                                }
                                StudioButton {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "Browse video"
                                    primary: true
                                    small: true
                                    enabled: studio.canBrowseVideo
                                    onClicked: studio.browseVideo()
                                }
                            }

                            DropArea {
                                anchors.fill: parent
                                onDropped: function(drop) {
                                    if (drop.hasUrls && drop.urls.length > 0 && studio.canBrowseVideo) {
                                        studio.importVideoUrl(drop.urls[0].toString())
                                        drop.acceptProposedAction()
                                    }
                                }
                            }
                        }

                        // Qt Quick 3D is the heaviest part of the scene. Keep the
                        // component unloaded until it is requested, then retain it
                        // so switching preview modes does not recreate the scene.
                        Loader {
                            id: livePreviewLoader
                            anchors.fill: parent
                            // Capture context properties on the Loader so the
                            // inline component does not resolve them against
                            // its own scope when it is created lazily.
                            property var studioBridge: studio
                            property var geometryObject: blockGeometry
                            active: window.previewMode === "live" || item !== null
                            opacity: window.previewMode === "live" ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 240; easing.type: Easing.InOutCubic } }
                            sourceComponent: LiveReconstruction {
                                anchors.fill: parent
                                studio: livePreviewLoader.studioBridge
                                blockGeometry: livePreviewLoader.geometryObject
                            }
                        }

                        Row {
                            id: previewModeSwitch
                            anchors.top: parent.top
                            anchors.right: parent.right
                            anchors.topMargin: 11
                            anchors.rightMargin: 13
                            spacing: 4
                            z: 5
                            Repeater {
                                model: ["Source Video", "Live Reconstruction"]
                                delegate: Rectangle {
                                    required property string modelData
                                    width: modelData === "Source Video" ? 82 : 112
                                    height: 25
                                    radius: 8
                                    color: window.previewMode === (modelData === "Source Video" ? "source" : "live") ? "#526B82" : "#B0101723"
                                    border.width: 1
                                    border.color: "#506477"
                                    Text { anchors.centerIn: parent; text: modelData; color: "#E3ECF5"; font.pixelSize: 10 }
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: window.previewMode = modelData === "Source Video" ? "source" : "live"
                                    }
                                }
                            }
                        }

                    }

                    Rectangle {
                        id: pathShade
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: progressStrip.top
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        anchors.bottomMargin: 7
                        height: 38
                        radius: 10
                        color: "#C4101723"
                        z: 1
                        visible: window.previewMode === "source"
                    }
                    RowLayout {
                        id: pathControls
                        anchors.left: pathShade.left
                        anchors.right: pathShade.right
                        anchors.verticalCenter: pathShade.verticalCenter
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 7
                        z: 2
                        visible: window.previewMode === "source"
                        Text {
                            Layout.fillWidth: true
                            text: studio.hasVideo ? studio.videoPath : "No source selected yet"
                            color: "#D4DFEA"
                            font.pixelSize: 10
                            elide: Text.ElideMiddle
                        }
                        StudioButton {
                            visible: studio.hasVideo
                            text: player.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                            glyph: player.playbackState === MediaPlayer.PlayingState ? "Ⅱ" : "▶"
                            small: true
                            enabled: studio.hasVideo
                            onClicked: player.playbackState === MediaPlayer.PlayingState ? player.pause() : player.play()
                        }
                        StudioButton {
                            visible: studio.hasVideo
                            text: "Change"
                            small: true
                            enabled: studio.canBrowseVideo
                            onClicked: studio.browseVideo()
                        }
                        StudioButton {
                            visible: studio.hasVideo
                            text: "Clear"
                            small: true
                            danger: true
                            enabled: !studio.busy
                            onClicked: { player.stop(); studio.clearVideo() }
                        }
                    }

                    Rectangle {
                        id: progressStrip
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        height: 27
                        radius: 8
                        color: "#D00E1722"
                        border.width: 1
                        border.color: "#263A4A5D"
                        z: 1
                        visible: window.previewMode === "source"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 7
                            Text {
                                text: formatTime(player.position)
                                color: "#E0E8F2"
                                font.pixelSize: 10
                            }
                            Slider {
                                id: previewSeek
                                Layout.fillWidth: true
                                Layout.minimumHeight: 20
                                Layout.preferredHeight: 20
                                from: 0
                                to: 1
                                value: player.duration > 0 ? player.position / player.duration : 0
                                enabled: player.duration > 0
                                live: true
                                onMoved: player.setPosition(value * player.duration)
                                background: Rectangle {
                                    x: previewSeek.leftPadding
                                    y: previewSeek.topPadding + previewSeek.availableHeight / 2 - height / 2
                                    width: previewSeek.availableWidth
                                    height: 3
                                    color: previewSeek.enabled ? "#4A586A" : "#303A47"
                                    radius: 2
                                    Rectangle {
                                        width: previewSeek.visualPosition * parent.width
                                        height: parent.height
                                        radius: 2
                                        color: previewSeek.enabled ? "#E4ECF5" : "#566273"
                                    }
                                }
                                handle: Rectangle {
                                    x: previewSeek.leftPadding + previewSeek.visualPosition * (previewSeek.availableWidth - width)
                                    y: previewSeek.topPadding + previewSeek.availableHeight / 2 - height / 2
                                    width: 9; height: 9; radius: 5
                                    color: previewSeek.enabled ? "#F3F6FB" : "#647184"
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    acceptedButtons: Qt.LeftButton
                                    cursorShape: previewSeek.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onPressed: function(mouse) { seekTo(mouse.x, width) }
                                    onPositionChanged: if (pressed) seekTo(mouse.x, width)
                                }
                            }
                            Text {
                                text: formatTime(player.duration)
                                color: "#E0E8F2"
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }

            Row {
                id: lowerArea
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 300
                spacing: 14

                StudioCard {
                id: commandsCard
                width: Math.max(0, (lowerArea.width - lowerArea.spacing) / 2)
                height: lowerArea.height
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 9
                    Text {
                        text: "In-game commands"
                        color: window.white
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                    }
                    GridLayout {
                        columns: 1
                        rowSpacing: 8
                        columnSpacing: 9
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Repeater {
                            model: ["/reload", "/function vidbuild:check", "/function vidbuild:build", "/function vidbuild:undo"]
                            delegate: Rectangle {
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.minimumHeight: 34
                                radius: 10
                                color: copyArea.containsMouse ? "#3D4A59" : "#242F3B"
                                Behavior on color { ColorAnimation { duration: 150 } }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 9
                                    Text {
                                        text: modelData
                                        Layout.fillWidth: true
                                        font.pixelSize: 12
                                        font.family: "Consolas"
                                        color: "#C3D2E3"
                                        elide: Text.ElideRight
                                    }
                                    Item {
                                        Layout.preferredWidth: 18
                                        Layout.preferredHeight: 18
                                        Rectangle {
                                            x: 5
                                            y: 2
                                            width: 11
                                            height: 11
                                            radius: 3
                                            color: "transparent"
                                            border.width: 1.5
                                            border.color: "#E0E8F2"
                                        }
                                        Rectangle {
                                            x: 2
                                            y: 5
                                            width: 11
                                            height: 11
                                            radius: 3
                                            color: "transparent"
                                            border.width: 1.5
                                            border.color: "#E0E8F2"
                                        }
                                    }
                                }
                                MouseArea {
                                    id: copyArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: studio.copy(modelData)
                                }
                            }
                        }
                    }
                }
            }

                StudioCard {
                id: generationCard
                width: Math.max(0, (lowerArea.width - lowerArea.spacing) / 2)
                height: lowerArea.height
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 9
                    FieldLabel { text: "BUILDING HINTS   ·   OPTIONAL"; font.letterSpacing: 1.2 }
                    TextArea {
                        id: hintsField
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: 0
                        Layout.maximumWidth: parent.width
                        Layout.preferredHeight: 76
                        font.family: "Segoe UI"
                        font.pixelSize: 12
                        color: "#E8EEF6"
                        placeholderText: "Optional geometry, material or scale hints…"
                        placeholderTextColor: "#8594A6"
                        enabled: !studio.busy
                        wrapMode: TextEdit.Wrap
                        leftPadding: 13
                        rightPadding: 13
                        topPadding: 10
                        background: Rectangle {
                            radius: 11
                            color: hintsField.activeFocus ? "#354150" : "#232D39"
                            border.width: hintsField.activeFocus ? 1 : 0
                            border.color: "#7C96B3"
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#2AFFFFFF" }
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: studio.stage
                            color: studio.stage === "FAILED" ? "#F1B1B9" : "#B9CADA"
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                            font.letterSpacing: 0.9
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: studio.generating ? formatTime(studio.elapsed * 1000) + " elapsed" : ""
                            color: "#ACBBCB"
                            font.pixelSize: 11
                        }
                    }
                    Rectangle {
                        id: activeLine
                        Layout.fillWidth: true
                        Layout.preferredHeight: 3
                        radius: 2
                        color: "#435165"
                        clip: true
                        Rectangle {
                            id: movingLine
                            visible: studio.generating
                            width: Math.max(75, parent.width * 0.25)
                            height: parent.height
                            radius: 2
                            color: "#E7EDF4"
                            x: 0
                            NumberAnimation on x {
                                from: -120
                                to: activeLine.width
                                duration: 1600
                                loops: Animation.Infinite
                                running: studio.generating
                                easing.type: Easing.InOutSine
                            }
                        }
                        Rectangle {
                            visible: studio.stage === "COMPLETE" && !studio.generating
                            anchors.fill: parent
                            radius: 2
                            color: "#D5E4F1"
                        }
                    }
                    StudioButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 47
                        danger: studio.generating
                        text: studio.generating ? "Cancel generation" : "Generate Data Pack"
                        glyph: studio.generating ? "×" : "→"
                        enabled: studio.generating || (!studio.busy && studio.hasVideo)
                        onClicked: {
                            if (studio.generating) studio.cancelGeneration()
                            else {
                                studio.generate(window.provider, modelCombo.currentIndex,
                                    apiModelField.text, apiKeyField.text,
                                    Number(frameField.text), hintsField.text, outputField.text)
                                if (studio.generating) window.previewMode = "live"
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: studio.resultPath.length > 0
                        StudioButton {
                            text: "Open output folder"
                            glyph: "↗"
                            Layout.fillWidth: true
                            small: true
                            onClicked: studio.openOutputFolder()
                        }
                        StudioButton {
                            text: "Copy path"
                            small: true
                            onClicked: studio.copy(studio.resultPath)
                        }
                    }
                }
            }
            }
        }
    }

    Rectangle {
        id: toastBox
        z: 999
        width: Math.max(180, toastLabel.implicitWidth + 40)
        height: 45
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        radius: 13
        color: "#E42D3B4B"
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 185; easing.type: Easing.OutCubic } }
        Text {
            id: toastLabel
            anchors.centerIn: parent
            text: ""
            color: "#F0F5FB"
            font.pixelSize: 13
        }
    }
    Timer {
        id: toastTimer
        interval: 2300
        repeat: false
        onTriggered: toastBox.opacity = 0
    }
    Connections {
        target: studio
        function onToast(message) {
            toastLabel.text = message
            toastBox.opacity = 1
            toastTimer.restart()
        }
    }
    function formatTime(msecs) {
        if (!msecs || msecs < 0 || isNaN(msecs)) return "00:00"
        var seconds = Math.floor(msecs / 1000)
        var minutes = Math.floor(seconds / 60)
        var secs = seconds % 60
        return String(minutes).padStart(2, '0') + ':' + String(secs).padStart(2, '0')
    }
    function seekTo(x, width) {
        if (!player.duration || width <= 0) return
        var normalized = Math.max(0, Math.min(1, x / width))
        previewSeek.value = normalized
        player.setPosition(Math.round(normalized * player.duration))
    }
    Shortcut { sequence: "Ctrl+O"; onActivated: studio.browseVideo() }
    Shortcut { sequence: "Ctrl+S"; onActivated: studio.browseOutput() }
    Shortcut {
        sequence: "Space"
        context: Qt.ApplicationShortcut
        enabled: window.splashActive
        onActivated: window.skipSplash()
    }
}

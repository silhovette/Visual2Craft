import QtQuick

Rectangle {
    radius: 22
    color: "#CF111923"
    border.width: 1
    border.color: "#2AFFFFFF"
    // Static translucent surfaces are rendered once in the Qt Quick scenegraph;
    // no per-frame bitmap screenshots, CPU blur or Tk canvas re-paints.
}

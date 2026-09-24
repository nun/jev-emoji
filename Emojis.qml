import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui

Item {
  id: root

  property var shell: null
  property var manifest: null

  property bool opened: false
  property string filterText: ""
  property int selectedIndex: 0
  property bool cursorActive: false
  property string statusText: "Type what you want to say"
  property int searchGen: 0
  property int inflightGen: -1
  property string inflightText: ""
  property bool searchStopping: false
  // A search scores the whole catalog. Wait out a typing burst so Jev is
  // asked once for the finished words, not once per key.
  readonly property int searchDebounceMs: 800
  property bool needsKey: false
  property string setupStatus: ""
  property string pendingToken: ""

  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Color.menu.scrim
  property color selectedBackground: Color.menu.selectedBackground
  property color selectedText: Color.menu.selectedText
  readonly property int cornerRadius: Style.cornerRadius
  property string fontFamily: Style.font.menuFamily
  property int contentMargin: Style.spacing.panelPadding
  property int headerHeight: Math.max(Style.space(34), Style.font.title + Style.spacing.controlPaddingY * 2)
  property int contentSpacing: Style.spacing.md
  property int cardWidth: Math.min(root.needsKey ? Style.space(560) : Style.space(440), panel.width - Style.gapsOut * 2)
  property int cardHeight: Math.min(root.needsKey ? Style.space(280) : Style.space(540), panel.height - Style.gapsOut * 2)

  property int cellWidth: Math.max(Style.space(44), Style.font.display + Style.spacing.md)
  property int cellHeight: Math.max(Style.space(44), Style.font.display + Style.spacing.md)
  property int columns: Math.floor((cardWidth - contentMargin * 2) / cellWidth)

  function open(payloadJson) {
    root.opened = true
    root.filterText = ""
    root.selectedIndex = 0
    root.cursorActive = false
    root.statusText = "Type what you want to say"
    root.searchGen++
    root.inflightText = ""
    root.searchStopping = searchProc.running
    searchTimer.stop()
    if (searchProc.running)
      searchProc.running = false
    displayModel.clear()
    tokenField.text = ""
    root.checkKey()
  }

  function checkKey() {
    if (keyProc.running)
      return
    keyProc.command = ["python3", root.scriptPath(), "--has-key"]
    keyProc.running = true
  }

  function onKeyChecked(stdout) {
    var payload = root.parseLine(stdout)
    root.needsKey = !(payload && payload.ok === true && payload.hasKey === true)
    root.setupStatus = root.needsKey ? "Paste your TypeSafe API key." : ""
    Qt.callLater(function() {
      if (root.needsKey) tokenField.forceActiveFocus()
      else keyCatcher.forceActiveFocus()
    })
  }

  function saveToken() {
    var token = tokenField.text.trim()
    if (!token) {
      root.setupStatus = "Paste your API key first."
      tokenField.forceActiveFocus()
      return
    }
    if (saveProc.running)
      return
    root.pendingToken = token
    root.setupStatus = "Saving…"
    saveProc.command = ["python3", root.scriptPath(), "--save-key"]
    saveProc.running = true
  }

  function onTokenSaved(stdout) {
    var payload = root.parseLine(stdout)
    root.pendingToken = ""
    if (!payload || payload.ok !== true) {
      root.setupStatus = payload && payload.error ? String(payload.error) : "Could not save the key."
      tokenField.forceActiveFocus()
      return
    }
    tokenField.text = ""
    root.needsKey = false
    root.setupStatus = ""
    root.statusText = "Key saved. Type what you want to say."
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function parseLine(stdout) {
    var line = String(stdout || "").trim()
    var parts = line.split("\n")
    line = parts.length ? parts[parts.length - 1] : ""
    try {
      return JSON.parse(line)
    } catch (e) {
      return null
    }
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    root.searchGen++
    root.inflightText = ""
    searchTimer.stop()
    root.searchStopping = searchProc.running
    if (searchProc.running)
      searchProc.running = false
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "jev.emoji")
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  function scriptPath() {
    var path = Qt.resolvedUrl("search.py").toString()
    if (path.indexOf("file://") === 0)
      path = decodeURIComponent(path.slice(7))
    return path
  }

  function setFilter(nextFilter) {
    root.filterText = nextFilter
    root.selectedIndex = 0
    root.cursorActive = false
    displayModel.clear()
    var text = nextFilter.trim()
    if (text.length < 2) {
      root.searchGen++
      root.statusText = text ? "Type a bit more" : "Type what you want to say"
      searchTimer.stop()
      root.searchStopping = searchProc.running
      if (searchProc.running)
        searchProc.running = false
      return
    }
    root.statusText = "Searching…"
    searchTimer.restart()
  }

  function runSearch() {
    if (!root.opened || root.searchStopping || searchProc.running)
      return
    var text = root.filterText.trim()
    if (text.length < 2)
      return
    root.inflightGen = root.searchGen
    root.inflightText = text
    searchProc.command = ["python3", root.scriptPath(), text]
    searchProc.running = true
  }

  function onSearchFinished(exitCode, stdout, stderr) {
    root.searchStopping = false
    if (!root.opened)
      return
    var text = root.filterText.trim()
    // Typing moved on, or this process was cancelled. Keep the result only
    // when it is still the text in the box. Otherwise one later search covers
    // whatever the user paused on.
    if (root.inflightGen !== root.searchGen || root.inflightText !== text) {
      if (!searchTimer.running)
        root.runSearch()
      return
    }
    searchTimer.stop()
    var line = String(stdout || "").trim()
    var parts = line.split("\n")
    line = parts.length ? parts[parts.length - 1] : ""
    var payload = null
    try {
      payload = JSON.parse(line)
    } catch (e) {
      payload = null
    }
    if (!payload || payload.ok !== true) {
      var message = payload && payload.error ? String(payload.error) : ""
      if (!message)
        message = String(stderr || "").trim() || "Search failed."
      if (message.indexOf("API key") >= 0) {
        root.needsKey = true
        root.setupStatus = message
        displayModel.clear()
        Qt.callLater(function() { tokenField.forceActiveFocus() })
        return
      }
      root.statusText = message
      displayModel.clear()
      root.cursorActive = false
      return
    }
    root.showResults(payload.results || [])
  }

  function showResults(rows) {
    displayModel.clear()
    var list = Array.isArray(rows) ? rows : []
    for (var i = 0; i < list.length; i++) {
      var row = list[i]
      if (!row || !row.e)
        continue
      displayModel.append({
        emoji: String(row.e),
        keywords: String(row.k || ""),
        probability: Number(row.p) || 0
      })
    }
    if (displayModel.count === 0) {
      root.statusText = "No emojis fit this search"
      root.selectedIndex = 0
      root.cursorActive = false
      return
    }
    root.statusText = displayModel.count + (displayModel.count === 1 ? " match" : " matches")
    root.selectedIndex = 0
    root.cursorActive = true
    Qt.callLater(function() {
      if (displayModel.count > 0)
        resultGrid.positionViewAtIndex(0, GridView.Contain)
    })
  }

  function select(delta) {
    if (displayModel.count === 0) return
    if (!cursorActive) {
      cursorActive = true
      selectedIndex = delta < 0 ? displayModel.count - 1 : 0
    } else {
      selectedIndex = (selectedIndex + delta + displayModel.count) % displayModel.count
    }
    resultGrid.positionViewAtIndex(selectedIndex, GridView.Contain)
  }

  function selectRow(delta) {
    if (displayModel.count === 0) return
    if (!cursorActive) {
      cursorActive = true
      selectedIndex = delta < 0 ? displayModel.count - 1 : 0
      resultGrid.positionViewAtIndex(selectedIndex, GridView.Contain)
      return
    }
    var newIndex = selectedIndex + delta * columns
    if (newIndex < 0) newIndex = 0
    if (newIndex >= displayModel.count) newIndex = displayModel.count - 1
    selectedIndex = newIndex
    resultGrid.positionViewAtIndex(selectedIndex, GridView.Contain)
  }

  function selectPage(delta) {
    if (displayModel.count === 0) return
    if (!cursorActive) {
      cursorActive = true
      selectedIndex = delta < 0 ? displayModel.count - 1 : 0
      resultGrid.positionViewAtIndex(selectedIndex, GridView.Contain)
      return
    }
    var visibleRows = Math.max(1, Math.floor(resultGrid.height / cellHeight))
    var newIndex = selectedIndex + delta * columns * visibleRows
    if (newIndex < 0) newIndex = 0
    if (newIndex >= displayModel.count) newIndex = displayModel.count - 1
    selectedIndex = newIndex
    resultGrid.positionViewAtIndex(selectedIndex, GridView.Contain)
  }

  function activateIndex(index) {
    if (index < 0 || index >= displayModel.count) return
    var row = displayModel.get(index)
    root.applySelected(row.emoji)
  }

  function applySelected(emoji) {
    if (!emoji) return
    root.dismiss()
    Quickshell.execDetached(["omarchy-menu-emoji-insert", emoji])
  }

  function selectedDetail() {
    if (!root.cursorActive || displayModel.count === 0)
      return ""
    var row = displayModel.get(root.selectedIndex)
    if (!row) return ""
    var words = String(row.keywords || "").split(" ")
    var name = words.slice(0, 4).join(" ")
    var percent = Math.round(Number(row.probability) * 100)
    return row.emoji + "  " + name + "  ·  " + percent + "%"
  }

  ListModel { id: displayModel }

  Timer {
    id: searchTimer
    interval: root.searchDebounceMs
    repeat: false
    onTriggered: root.runSearch()
  }

  Process {
    id: keyProc
    stdout: StdioCollector {
      id: keyOut
      waitForEnd: true
    }
    onExited: root.onKeyChecked(keyOut.text)
  }

  Process {
    id: saveProc
    stdinEnabled: true
    stdout: StdioCollector {
      id: saveOut
      waitForEnd: true
    }
    onStarted: saveProc.write(root.pendingToken + "\n")
    onExited: root.onTokenSaved(saveOut.text)
  }

  Process {
    id: searchProc
    stdout: StdioCollector {
      id: searchOut
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: searchErr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      root.onSearchFinished(exitCode, searchOut.text, searchErr.text)
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-jev-emoji"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      color: root.background
      borderSpec: root.borderSpec
      padding: root.contentMargin

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: !root.needsKey

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (root.needsKey)
            return
          if (event.key === Qt.Key_Escape) {
            if (root.filterText) root.setFilter("")
            else root.dismiss()
            event.accepted = true
          } else if (Util.editsFilter(event, root.filterText)) {
            root.setFilter(Util.editedFilter(event, root.filterText))
            event.accepted = true
          } else if (event.key === Qt.Key_Left) {
            root.select(-1)
            event.accepted = true
          } else if (event.key === Qt.Key_Right) {
            root.select(1)
            event.accepted = true
          } else if (event.key === Qt.Key_Up) {
            root.selectRow(-1)
            event.accepted = true
          } else if (event.key === Qt.Key_Down) {
            root.selectRow(1)
            event.accepted = true
          } else if (event.key === Qt.Key_PageUp) {
            root.selectPage(-1)
            event.accepted = true
          } else if (event.key === Qt.Key_PageDown) {
            root.selectPage(1)
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            if (root.cursorActive) root.activateIndex(root.selectedIndex)
            else if (displayModel.count > 0) root.cursorActive = true
            event.accepted = true
          } else if (event.text && event.text.length === 1 && event.text.charCodeAt(0) >= 32 && event.text.charCodeAt(0) !== 127) {
            root.setFilter(root.filterText + event.text)
            event.accepted = true
          }
        }
      }

      Column {
        visible: root.needsKey
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: root.contentSpacing

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: "API key"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
        }

        Text {
          width: parent.width
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: "Jev emoji needs a TypeSafe key. Paste it here. Press Enter to save."
          color: root.foreground
          opacity: 0.8
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }

        TextField {
          id: tokenField
          width: parent.width
          placeholderText: "Paste API key"
          foreground: root.foreground
          font.family: root.fontFamily
          onAccepted: root.saveToken()
          Keys.onEscapePressed: function(event) {
            root.dismiss()
            event.accepted = true
          }
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: root.setupStatus
          color: root.foreground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
      }

      Column {
        visible: !root.needsKey
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: root.contentSpacing

        Rectangle {
          width: parent.width
          height: root.headerHeight
          radius: root.cornerRadius
          color: "transparent"

          Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.filterText || "Search emojis…"
            color: root.foreground
            opacity: root.filterText ? 1 : 0.58
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            elide: Text.ElideRight
          }
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: root.selectedDetail() || root.statusText
          color: root.foreground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Item {
          width: parent.width
          height: parent.height - root.headerHeight - root.contentSpacing * 2 - Style.font.body

          GridView {
            id: resultGrid
            anchors.fill: parent
            model: displayModel
            clip: true
            cellWidth: root.cellWidth
            cellHeight: root.cellHeight
            boundsBehavior: Flickable.StopAtBounds

            delegate: Rectangle {
              required property int index
              required property string emoji

              readonly property bool hasCursor: root.cursorActive && index === root.selectedIndex

              width: root.cellWidth
              height: root.cellHeight
              radius: root.cornerRadius
              color: hasCursor ? root.selectedBackground : "transparent"

              Text {
                textFormat: Text.PlainText
                text: parent.emoji
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
                anchors.centerIn: parent
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
              }

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onContainsMouseChanged: if (containsMouse) {
                  root.cursorActive = true
                  root.selectedIndex = index
                }
                onClicked: {
                  root.cursorActive = true
                  root.selectedIndex = index
                  root.activateIndex(index)
                }
              }
            }
          }
        }
      }
    }
  }
}

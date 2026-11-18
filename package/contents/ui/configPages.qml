import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    property alias cfg_page1: page1.text
    property alias cfg_page2: page2.text
    property alias cfg_page3: page3.text
    property alias cfg_page4: page4.text
    property alias cfg_page5: page5.text
    property alias cfg_page6: page6.text
    property alias cfg_taskTargetPage: taskTarget.text

    Kirigami.FormLayout {
        QQC2.Label {
            Kirigami.FormData.isSection: true
            text: i18n("Pinned pages appear as buttons in the Pages section. Leave a slot empty to hide it.")
            wrapMode: Text.Wrap
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
        }

        QQC2.TextField { id: page1; Kirigami.FormData.label: i18n("Page 1:"); Layout.fillWidth: true }
        QQC2.TextField { id: page2; Kirigami.FormData.label: i18n("Page 2:"); Layout.fillWidth: true }
        QQC2.TextField { id: page3; Kirigami.FormData.label: i18n("Page 3:"); Layout.fillWidth: true }
        QQC2.TextField { id: page4; Kirigami.FormData.label: i18n("Page 4:"); Layout.fillWidth: true }
        QQC2.TextField { id: page5; Kirigami.FormData.label: i18n("Page 5:"); Layout.fillWidth: true }
        QQC2.TextField { id: page6; Kirigami.FormData.label: i18n("Page 6:"); Layout.fillWidth: true }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }

        QQC2.TextField {
            id: taskTarget
            Kirigami.FormData.label: i18n("New tasks go to:")
            Layout.fillWidth: true
            placeholderText: i18n("Today's journal")
        }
    }
}

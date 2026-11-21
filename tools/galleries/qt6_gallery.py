"""CIG reference gallery - Qt 6 widgets (Qt for Python / PySide6, the official Qt binding from PyPI).
Run with the interpreter that has PySide6:  <venv>\\Scripts\\python.exe qt6_gallery.py"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QRadioButton, QSlider, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QWidget)


def named(w, name, obj):
    w.setAccessibleName(name)
    w.setObjectName(obj)
    return w


def main():
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("CIG Qt6 Gallery")
    g = QGridLayout(win)
    g.addWidget(named(QPushButton("Press me"), "Press me", "PressButton"), 0, 0)
    g.addWidget(named(QCheckBox("A checkbox"), "A checkbox", "TheCheck"), 1, 0)
    r1 = named(QRadioButton("Radio one"), "Radio one", "RadioOne")
    r1.setChecked(True)
    g.addWidget(r1, 2, 0)
    g.addWidget(named(QRadioButton("Radio two"), "Radio two", "RadioTwo"), 2, 1)
    g.addWidget(QLabel("Text field:"), 3, 0)
    g.addWidget(named(QLineEdit(), "Text field", "TheText"), 3, 1)
    pw = named(QLineEdit(), "Password field", "ThePassword")
    pw.setEchoMode(QLineEdit.Password)
    g.addWidget(pw, 4, 1)
    combo = named(QComboBox(), "Choice", "TheChoice")
    combo.addItems(["Alpha", "Beta", "Gamma"])
    g.addWidget(combo, 5, 0)
    lst = named(QListWidget(), "List", "TheList")
    lst.addItems(["One", "Two", "Three"])
    lst.setMaximumHeight(70)
    g.addWidget(lst, 6, 0)
    sl = named(QSlider(Qt.Horizontal), "Slider", "TheSlider")
    sl.setRange(0, 10)
    g.addWidget(sl, 7, 0)
    sp = named(QSpinBox(), "Number", "TheNumber")
    sp.setRange(0, 100)
    g.addWidget(sp, 7, 1)
    tree = named(QTreeWidget(), "Tree", "TheTree")
    tree.setHeaderHidden(True)
    root = QTreeWidgetItem(["Root"])
    root.addChildren([QTreeWidgetItem(["Child A"]), QTreeWidgetItem(["Child B"])])
    tree.addTopLevelItem(root)
    tree.setMaximumHeight(90)
    g.addWidget(tree, 8, 0)
    tabs = named(QTabWidget(), "Tabs", "TheTabs")
    tabs.addTab(QWidget(), "First tab")
    tabs.addTab(QWidget(), "Second tab")
    g.addWidget(tabs, 8, 1)
    win.resize(520, 520)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

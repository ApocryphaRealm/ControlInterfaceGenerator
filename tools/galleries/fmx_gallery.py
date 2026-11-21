"""CIG reference gallery - Delphi FireMonkey (FMX), through Embarcadero's official DelphiFMX4Python package
(delphifmx on PyPI, BSD). Real FMX controls, the same set as the other galleries.
Run with the interpreter that has delphifmx:  <venv>\\Scripts\\python.exe fmx_gallery.py"""
from delphifmx import (Application, Button, CheckBox, ComboBox, Edit, Form, Label, ListBox, RadioButton, SpinBox,
                       Switch, TabControl, TrackBar)


class Gallery(Form):
    def __init__(self, owner):
        self.Caption = "CIG FMX Gallery"
        self.SetBounds(200, 200, 520, 640)
        y = [10]

        def place(ctrl, height=28, width=220):
            ctrl.Parent = self
            ctrl.Position.X = 10
            ctrl.Position.Y = y[0]
            ctrl.Width = width
            ctrl.Height = height
            y[0] += height + 8
            return ctrl

        b = place(Button(self))
        b.Text = "Press me"
        c = place(CheckBox(self))
        c.Text = "A checkbox"
        r1 = place(RadioButton(self))
        r1.Text = "Radio one"
        r1.IsChecked = True
        r2 = place(RadioButton(self))
        r2.Text = "Radio two"
        place(Label(self)).Text = "Text field:"
        place(Edit(self), width=300)
        place(Label(self)).Text = "Password field:"
        pw = place(Edit(self), width=300)
        pw.Password = True
        combo = place(ComboBox(self))
        for s in ("Alpha", "Beta", "Gamma"):
            combo.Items.Add(s)
        combo.ItemIndex = 0
        lb = place(ListBox(self), height=70)
        for s in ("One", "Two", "Three"):
            lb.Items.Add(s)
        tb = place(TrackBar(self))
        tb.Min = 0
        tb.Max = 10
        sp = place(SpinBox(self), width=120)
        sp.Min = 0
        sp.Max = 100
        place(Switch(self), width=60)
        place(TabControl(self), height=60)


def main():
    Application.Initialize()
    Application.Title = "CIG FMX Gallery"
    Application.MainForm = Gallery(Application)
    Application.MainForm.Show()
    Application.Run()
    Application.MainForm.Destroy()


if __name__ == "__main__":
    main()

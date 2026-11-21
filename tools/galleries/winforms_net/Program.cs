using System;
using System.Windows.Forms;

// CIG reference gallery - Windows Forms (.NET 8). One of each common control, probed by tools/probe.py --bridge dotnet.
static class Program
{
    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        var f = new Form { Text = "CIG WinForms Gallery (.NET)", Width = 540, Height = 560 };
        T Add<T>(T c, int x, int y, int w = 160) where T : Control { c.Left = x; c.Top = y; c.Width = w; f.Controls.Add(c); return c; }
        Add(new Button { Text = "Press me", Name = "PressButton" }, 10, 10);
        Add(new CheckBox { Text = "A checkbox", Name = "TheCheck" }, 10, 45);
        Add(new RadioButton { Text = "Radio one", Checked = true }, 10, 75);
        Add(new RadioButton { Text = "Radio two" }, 180, 75);
        Add(new TextBox { Name = "TheText", AccessibleName = "Text field" }, 10, 110, 300);
        Add(new TextBox { UseSystemPasswordChar = true, AccessibleName = "Password field" }, 10, 140, 300);
        var combo = Add(new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, AccessibleName = "Choice" }, 10, 170);
        combo.Items.AddRange(new object[] { "Alpha", "Beta", "Gamma" }); combo.SelectedIndex = 0;
        var lb = Add(new ListBox { AccessibleName = "List", Height = 60 }, 10, 205);
        lb.Items.AddRange(new object[] { "One", "Two", "Three" });
        Add(new TrackBar { Minimum = 0, Maximum = 10, AccessibleName = "Slider" }, 10, 275, 200);
        Add(new NumericUpDown { Minimum = 0, Maximum = 100, AccessibleName = "Number" }, 230, 275, 80);
        var tv = Add(new TreeView { AccessibleName = "Tree", Height = 110 }, 10, 330, 200);
        var root = tv.Nodes.Add("Root"); root.Nodes.Add("Child A"); root.Nodes.Add("Child B");
        var tc = Add(new TabControl { Height = 110 }, 230, 330, 260);
        tc.TabPages.Add("First tab"); tc.TabPages.Add("Second tab");
        Application.Run(f);
    }
}

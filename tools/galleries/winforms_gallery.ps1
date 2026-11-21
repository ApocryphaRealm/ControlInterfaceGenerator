# CIG reference gallery - Windows Forms (built from .NET Framework that ships with Windows; nothing downloaded).
# One of each common control, for tools/probe.py --actions. Run: powershell -STA -NoProfile -WindowStyle Hidden -File <this>
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$f = New-Object System.Windows.Forms.Form
$f.Text = 'CIG WinForms Gallery'; $f.Width = 520; $f.Height = 520; $f.StartPosition = 'CenterScreen'
function Add-At($c, $x, $y, $w = 160) { $c.Left = $x; $c.Top = $y; $c.Width = $w; $f.Controls.Add($c); $c }
$b = Add-At (New-Object System.Windows.Forms.Button) 10 10; $b.Text = 'Press me'; $b.Name = 'PressButton'
$cb = Add-At (New-Object System.Windows.Forms.CheckBox) 10 45; $cb.Text = 'A checkbox'; $cb.Name = 'TheCheck'
$r1 = Add-At (New-Object System.Windows.Forms.RadioButton) 10 75; $r1.Text = 'Radio one'; $r1.Checked = $true
$r2 = Add-At (New-Object System.Windows.Forms.RadioButton) 180 75; $r2.Text = 'Radio two'
$tb = Add-At (New-Object System.Windows.Forms.TextBox) 10 110 300; $tb.Name = 'TheText'; $tb.AccessibleName = 'Text field'
$pw = Add-At (New-Object System.Windows.Forms.TextBox) 10 140 300; $pw.UseSystemPasswordChar = $true; $pw.AccessibleName = 'Password field'
$co = Add-At (New-Object System.Windows.Forms.ComboBox) 10 170; $co.DropDownStyle = 'DropDownList'; $co.AccessibleName = 'Choice'
[void]$co.Items.AddRange(@('Alpha', 'Beta', 'Gamma')); $co.SelectedIndex = 0
$lb = Add-At (New-Object System.Windows.Forms.ListBox) 10 205 160; $lb.Height = 60; $lb.AccessibleName = 'List'
[void]$lb.Items.AddRange(@('One', 'Two', 'Three'))
$tk = Add-At (New-Object System.Windows.Forms.TrackBar) 10 275 200; $tk.Minimum = 0; $tk.Maximum = 10; $tk.AccessibleName = 'Slider'
$nu = Add-At (New-Object System.Windows.Forms.NumericUpDown) 230 275 80; $nu.Minimum = 0; $nu.Maximum = 100; $nu.AccessibleName = 'Number'
$tv = Add-At (New-Object System.Windows.Forms.TreeView) 10 330 200; $tv.Height = 120; $tv.AccessibleName = 'Tree'
$n = $tv.Nodes.Add('Root'); [void]$n.Nodes.Add('Child A'); [void]$n.Nodes.Add('Child B')
$tc = Add-At (New-Object System.Windows.Forms.TabControl) 230 330 250; $tc.Height = 120
foreach ($t in 'First tab', 'Second tab') { $p = New-Object System.Windows.Forms.TabPage; $p.Text = $t; [void]$tc.TabPages.Add($p) }
[void]$f.ShowDialog()

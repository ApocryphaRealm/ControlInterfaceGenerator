# CIG reference gallery - WPF (PresentationFramework ships with Windows' .NET Framework; nothing downloaded).
# Run: powershell -STA -NoProfile -WindowStyle Hidden -File <this>
Add-Type -AssemblyName PresentationFramework
[xml]$x = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="CIG WPF Gallery" Width="520" Height="560"
        WindowStartupLocation="CenterScreen">
  <StackPanel Margin="10">
    <Button AutomationProperties.AutomationId="PressButton" Content="Press me" Width="160" HorizontalAlignment="Left"/>
    <CheckBox AutomationProperties.AutomationId="TheCheck" Content="A checkbox" Margin="0,8,0,0"/>
    <ToggleButton AutomationProperties.AutomationId="TheToggle" Content="A toggle button" Width="160" HorizontalAlignment="Left" Margin="0,8,0,0"/>
    <RadioButton Content="Radio one" IsChecked="True" Margin="0,8,0,0"/>
    <RadioButton Content="Radio two"/>
    <TextBox AutomationProperties.AutomationId="TheText" AutomationProperties.Name="Text field" Width="300" HorizontalAlignment="Left" Margin="0,8,0,0"/>
    <PasswordBox AutomationProperties.Name="Password field" Width="300" HorizontalAlignment="Left" Margin="0,8,0,0"/>
    <ComboBox AutomationProperties.Name="Choice" Width="160" HorizontalAlignment="Left" SelectedIndex="0" Margin="0,8,0,0">
      <ComboBoxItem>Alpha</ComboBoxItem><ComboBoxItem>Beta</ComboBoxItem><ComboBoxItem>Gamma</ComboBoxItem>
    </ComboBox>
    <ListBox AutomationProperties.Name="List" Height="60" Width="160" HorizontalAlignment="Left" Margin="0,8,0,0">
      <ListBoxItem>One</ListBoxItem><ListBoxItem>Two</ListBoxItem><ListBoxItem>Three</ListBoxItem>
    </ListBox>
    <Slider AutomationProperties.Name="Slider" Minimum="0" Maximum="10" Width="200" HorizontalAlignment="Left" Margin="0,8,0,0"/>
    <Expander Header="An expander" Margin="0,8,0,0"><TextBlock Text="Inside the expander"/></Expander>
    <TreeView AutomationProperties.Name="Tree" Height="80" Margin="0,8,0,0">
      <TreeViewItem Header="Root"><TreeViewItem Header="Child A"/><TreeViewItem Header="Child B"/></TreeViewItem>
    </TreeView>
    <TabControl Height="60" Margin="0,8,0,0"><TabItem Header="First tab"/><TabItem Header="Second tab"/></TabControl>
  </StackPanel>
</Window>
'@
$w = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $x))
[void]$w.ShowDialog()

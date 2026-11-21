using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Layout;
using Avalonia.Markup.Xaml.Styling;
using Avalonia.Themes.Fluent;
using Avalonia.Automation;

// CIG reference gallery - Avalonia UI. One of each common control, named for accessibility, built in code
// (no XAML needed). Probed by tools/probe.py --actions.
class App : Application
{
    public override void Initialize() => Styles.Add(new FluentTheme());

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            desktop.MainWindow = Gallery.Build();
        base.OnFrameworkInitializationCompleted();
    }
}

static class Gallery
{
    static T Named<T>(T c, string name, string id) where T : Control
    {
        AutomationProperties.SetName(c, name);
        AutomationProperties.SetAutomationId(c, id);
        return c;
    }

    public static Window Build()
    {
        var p = new StackPanel { Margin = new Thickness(10), Spacing = 6 };
        p.Children.Add(Named(new Button { Content = "Press me" }, "Press me", "PressButton"));
        p.Children.Add(Named(new CheckBox { Content = "A checkbox" }, "A checkbox", "TheCheck"));
        p.Children.Add(Named(new ToggleSwitch { Content = "A toggle switch" }, "A toggle switch", "TheSwitch"));
        p.Children.Add(Named(new RadioButton { Content = "Radio one", GroupName = "g", IsChecked = true }, "Radio one", "RadioOne"));
        p.Children.Add(Named(new RadioButton { Content = "Radio two", GroupName = "g" }, "Radio two", "RadioTwo"));
        p.Children.Add(Named(new TextBox { Width = 300, HorizontalAlignment = HorizontalAlignment.Left }, "Text field", "TheText"));
        p.Children.Add(Named(new TextBox { Width = 300, PasswordChar = '*', HorizontalAlignment = HorizontalAlignment.Left }, "Password field", "ThePassword"));
        var combo = Named(new ComboBox { Width = 160, ItemsSource = new[] { "Alpha", "Beta", "Gamma" }, SelectedIndex = 0 }, "Choice", "TheChoice");
        p.Children.Add(combo);
        p.Children.Add(Named(new ListBox { Height = 90, Width = 160, HorizontalAlignment = HorizontalAlignment.Left, ItemsSource = new[] { "One", "Two", "Three" } }, "List", "TheList"));
        p.Children.Add(Named(new Slider { Minimum = 0, Maximum = 10, Width = 200, HorizontalAlignment = HorizontalAlignment.Left }, "Slider", "TheSlider"));
        p.Children.Add(Named(new NumericUpDown { Minimum = 0, Maximum = 100, Width = 160, HorizontalAlignment = HorizontalAlignment.Left }, "Number", "TheNumber"));
        p.Children.Add(Named(new Expander { Header = "An expander", Content = new TextBlock { Text = "Inside the expander" } }, "An expander", "TheExpander"));
        var tabs = Named(new TabControl(), "Tabs", "TheTabs");
        tabs.Items.Add(new TabItem { Header = "First tab", Content = new TextBlock { Text = "first" } });
        tabs.Items.Add(new TabItem { Header = "Second tab", Content = new TextBlock { Text = "second" } });
        p.Children.Add(tabs);
        return new Window { Title = "CIG Avalonia Gallery", Width = 520, Height = 720, Content = new ScrollViewer { Content = p } };
    }
}

static class Program
{
    [System.STAThread]
    public static void Main(string[] args) =>
        AppBuilder.Configure<App>().UsePlatformDetect().StartWithClassicDesktopLifetime(args);
}

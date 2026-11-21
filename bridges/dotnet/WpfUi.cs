// CIG .NET bridge - WPF, by reflection (no reference to PresentationFramework, so any WPF version on .NET 5+).
// Windows: Application.Current.Windows. Tree: LogicalTreeHelper.GetChildren (the app's own elements). Thread: the
// application's Dispatcher. Item controls (ComboBox, ListBox, TabControl) report their items as ListItem / TabItem
// children; a PasswordBox is a password field whose value is never read.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using static Cig.Bridge.Ui;

namespace Cig.Bridge
{
    internal static class WpfUi
    {
        static object App()
        {
            var t = Asm("PresentationFramework")?.GetType("System.Windows.Application");
            return t?.GetProperty("Current", BindingFlags.Public | BindingFlags.Static)?.GetValue(null);
        }

        public static bool HasApp() => App() != null;

        static T OnUi<T>(Func<T> f)
        {
            var disp = Get(App(), "Dispatcher");
            if (disp == null || (bool)disp.GetType().GetMethod("CheckAccess").Invoke(disp, null)) return f();
            T result = default;
            Exception err = null;
            Action a = () => { try { result = f(); } catch (Exception e) { err = e; } };
            disp.GetType().GetMethod("Invoke", new[] { typeof(Action) }).Invoke(disp, new object[] { a });
            if (err != null) throw err;
            return result;
        }

        static List<object> Windows() => (Get(App(), "Windows") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();

        static List<object> Children(object o)
        {
            var lth = Asm("PresentationFramework")?.GetType("System.Windows.LogicalTreeHelper");
            var depType = Asm("WindowsBase")?.GetType("System.Windows.DependencyObject");
            if (lth == null || depType == null || !depType.IsInstanceOfType(o)) return new List<object>();
            var m = lth.GetMethod("GetChildren", new[] { depType });
            var list = (m.Invoke(null, new[] { o }) as IEnumerable)?.Cast<object>().Where(depType.IsInstanceOfType).ToList()
                       ?? new List<object>();
            // a Frame's page (and any Content shown without being a logical child) is not in the logical tree, but it
            // is the app's own UI: follow it too (Microsoft's WPF Gallery shows every control page in a Frame)
            var content = Get(o, "Content");
            if (content != null && depType.IsInstanceOfType(content) && !list.Contains(content)) list.Add(content);
            // a control that declares its own content property ([ContentProperty("ExampleContent")] - WPF's standard
            // way, used by Microsoft's WPF Gallery's ControlExample) keeps the app's UI there: follow it too
            var cpa = o.GetType().GetCustomAttributes(true).FirstOrDefault(x => x.GetType().Name == "ContentPropertyAttribute");
            var cpName = cpa?.GetType().GetProperty("Name")?.GetValue(cpa) as string;
            if (!string.IsNullOrEmpty(cpName) && cpName != "Content")
            {
                var held = Get(o, cpName);
                if (held != null && depType.IsInstanceOfType(held) && !list.Contains(held)) list.Add(held);
            }
            return list;
        }

        static string AutoProp(object o, string method)
        {
            var ap = Asm("PresentationCore")?.GetType("System.Windows.Automation.AutomationProperties");
            try { return ap?.GetMethod(method, BindingFlags.Public | BindingFlags.Static)?.Invoke(null, new[] { o }) as string; }
            catch { return null; }
        }

        // a data item's display text: the control's DisplayMemberPath, else a usual name-like property, else ToString
        static string DataText(object owner, object item)
        {
            if (item == null) return "";
            if (item is string s) return s;
            var dmp = Get(owner, "DisplayMemberPath") as string;
            if (!string.IsNullOrEmpty(dmp) && Get(item, dmp) is object v) return v.ToString();
            foreach (var p in new[] { "Name", "Title", "Header", "DisplayName", "Text", "Label", "Content" })
                if (Get(item, p) is string str && str.Length > 0) return str;
            return ItemText(item);
        }

        static object Container(object itemsControl, int i)
        {
            var gen = Get(itemsControl, "ItemContainerGenerator");
            return gen?.GetType().GetMethod("ContainerFromIndex", new[] { typeof(int) })?.Invoke(gen, new object[] { i });
        }

        // TreeView / bound ItemsControl: each item is reported through its generated container (TreeViewItem, ...)
        static List<Dictionary<string, object>> BoundItems(object owner, string path, int depth)
        {
            var list = new List<Dictionary<string, object>>();
            var items = (Get(owner, "Items") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
            for (int i = 0; i < items.Count && i < 500; i++)
            {
                var cont = Container(owner, i);
                bool selectable = cont != null && cont.GetType().GetProperty("IsSelected") != null;
                var n = new Dictionary<string, object>
                {
                    ["control_type"] = !selectable ? "Text" : Is(cont, "TreeViewItem") ? "TreeItem" : "ListItem",
                    ["name"] = DataText(owner, items[i]), ["bridge"] = path + "/c" + i, ["framework_id"] = "WPF(bridge)",
                    // a plain ItemsControl's ContentPresenter cannot be selected (found on Microsoft's WPF Gallery)
                    ["patterns"] = selectable ? new List<string> { "SelectionItem", "Invoke" } : new List<string>(),
                };
                if (selectable) n["selected"] = (Get(cont, "IsSelected") as bool?) == true;
                if (Is(cont, "TreeViewItem") && ((Get(cont, "Items") as ICollection)?.Count ?? 0) > 0)
                {
                    ((List<string>)n["patterns"]).Add("ExpandCollapse");
                    bool open = (Get(cont, "IsExpanded") as bool?) == true;
                    n["expand_state"] = open ? "Expanded" : "Collapsed";
                    if (open && depth < 30) n["children"] = BoundItems(cont, path + "/c" + i, depth + 1);
                }
                list.Add(n);
            }
            return list;
        }

        static string Text(object o) =>
            Get(o, "Header") as string ?? Get(o, "Content") as string ?? Get(o, "Text") as string;

        public static object Tree() => OnUi(() =>
        {
            var wins = Windows();
            var nodes = new List<Dictionary<string, object>>();
            for (int i = 0; i < wins.Count; i++) nodes.Add(Node(wins[i], "w" + i, 0));
            return new { ok = true, framework = "wpf", windows = nodes };
        });

        static Dictionary<string, object> Node(object o, string path, int depth)
        {
            var n = new Dictionary<string, object> { ["bridge"] = path, ["framework_id"] = "WPF(bridge)" };
            var pats = new List<string>();
            string ct = "Group";
            string name = AutoProp(o, "GetName");
            string aid = AutoProp(o, "GetAutomationId");
            if (string.IsNullOrEmpty(aid)) aid = Get(o, "Name") as string;
            if (string.IsNullOrEmpty(name)) name = null;
            bool synth = false;

            if (Is(o, "Window")) { ct = "Window"; pats.Add("Window"); name ??= Get(o, "Title") as string; }
            else if (Is(o, "RadioButton")) { ct = "RadioButton"; pats.Add("SelectionItem"); n["selected"] = (Get(o, "IsChecked") as bool?) == true; }
            else if (Is(o, "ToggleButton")) { ct = "CheckBox"; pats.Add("Toggle"); n["toggle_state"] = (Get(o, "IsChecked") as bool?) == true ? "On" : "Off"; }
            else if (Is(o, "ButtonBase")) { ct = "Button"; pats.Add("Invoke"); }
            else if (Is(o, "PasswordBox")) { ct = "Edit"; pats.Add("Value"); n["is_password"] = true; }
            else if (Is(o, "TextBox"))
            {
                ct = "Edit"; pats.Add("Value"); n["value"] = Get(o, "Text") as string ?? "";
                n["is_read_only"] = (Get(o, "IsReadOnly") as bool?) == true;
            }
            else if (Is(o, "ComboBox")) { ct = "ComboBox"; pats.Add("Selection"); pats.Add("ExpandCollapse"); synth = true; n["value"] = ItemText(Get(o, "SelectedItem")); }
            else if (Is(o, "TabControl")) { ct = "Tab"; pats.Add("Selection"); synth = true; }
            else if (Is(o, "ListBox")) { ct = "List"; pats.Add("Selection"); synth = true; }
            else if (Is(o, "TreeViewItem"))
            {
                ct = "TreeItem"; pats.Add("SelectionItem"); pats.Add("ExpandCollapse");
                n["selected"] = (Get(o, "IsSelected") as bool?) == true;
                n["expand_state"] = (Get(o, "IsExpanded") as bool?) == true ? "Expanded" : "Collapsed";
            }
            else if (Is(o, "TreeView")) { ct = "Tree"; }
            else if (Is(o, "Expander"))
            {
                ct = "TreeItem"; pats.Add("ExpandCollapse");
                n["expand_state"] = (Get(o, "IsExpanded") as bool?) == true ? "Expanded" : "Collapsed";
            }
            else if (Is(o, "RangeBase") && !Is(o, "ScrollBar"))
            {
                ct = Is(o, "Slider") ? "Slider" : "Spinner"; pats.Add("RangeValue");
                n["range"] = new Dictionary<string, object>
                {
                    ["min"] = Convert.ToDouble(Get(o, "Minimum")), ["max"] = Convert.ToDouble(Get(o, "Maximum")),
                    ["value"] = Convert.ToDouble(Get(o, "Value")),
                };
            }
            else if (Is(o, "TextBlock") || Is(o, "Label")) { ct = "Text"; }
            name ??= Text(o);
            n["control_type"] = ct;
            if (!string.IsNullOrEmpty(name)) n["name"] = name;
            if (!string.IsNullOrEmpty(aid)) n["automation_id"] = aid;
            n["patterns"] = pats;
            if ((Get(o, "IsEnabled") as bool?) == false) n["enabled"] = false;

            var kids = new List<Dictionary<string, object>>();
            if (synth)
            {
                var items = (Get(o, "Items") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
                int sel = Convert.ToInt32(Get(o, "SelectedIndex") ?? -1);
                bool tabs = Is(o, "TabControl");
                for (int i = 0; i < items.Count; i++)
                    kids.Add(new Dictionary<string, object>
                    {
                        ["control_type"] = tabs ? "TabItem" : "ListItem", ["name"] = ItemText(items[i]),
                        ["patterns"] = new List<string> { "SelectionItem" }, ["selected"] = i == sel,
                        ["bridge"] = path + "/i" + i, ["framework_id"] = "WPF(bridge)",
                    });
                if (tabs && sel >= 0 && sel < items.Count && depth < 40)   // the open tab's own content stays reachable
                {
                    int k = 0;
                    foreach (var c in Children(items[sel])) kids.Add(Node(c, path + "/i" + sel + "/" + k++, depth + 1));
                }
            }
            else if (Is(o, "TreeView") || (Is(o, "ItemsControl") && Children(o).Count == 0
                                                && ((Get(o, "Items") as ICollection)?.Count ?? 0) > 0))
            {
                kids.AddRange(BoundItems(o, path, depth));       // data-bound: the items through their containers
            }
            else if (depth < 40)
            {
                int i = 0;
                foreach (var c in Children(o)) kids.Add(Node(c, path + "/" + i++, depth + 1));
            }
            if (kids.Count > 0) n["children"] = kids;
            return n;
        }

        static object Resolve(string path, out int item)
        {
            item = -1;
            var parts = path.Split('/');
            object o = Windows()[int.Parse(parts[0].Substring(1))];
            for (int k = 1; k < parts.Length; k++)
            {
                if (parts[k].StartsWith("c"))
                {
                    o = Container(o, int.Parse(parts[k].Substring(1)))
                        ?? throw new InvalidOperationException("the item's container is not generated (scrolled away?)");
                    continue;
                }
                if (parts[k].StartsWith("i"))
                {
                    int idx = int.Parse(parts[k].Substring(1));
                    if (k == parts.Length - 1) { item = idx; break; }
                    o = (Get(o, "Items") as IEnumerable).Cast<object>().ElementAt(idx);    // into the open tab
                    continue;
                }
                o = Children(o)[int.Parse(parts[k])];
            }
            return o;
        }

        // WPF's own routed Enter key, raised on the element inside the app (no OS input): PreviewKeyDown, then KeyDown.
        // Lists and trees that open an item on Enter or a click react to it (Microsoft's WPF Gallery navigates this way).
        static void RaiseEnter(object o)
        {
            var core = Asm("PresentationCore");
            var kb = core.GetType("System.Windows.Input.Keyboard");
            var dev = kb.GetProperty("PrimaryDevice", BindingFlags.Public | BindingFlags.Static).GetValue(null);
            var psType = core.GetType("System.Windows.PresentationSource");
            var src = psType.GetMethod("FromVisual", BindingFlags.Public | BindingFlags.Static).Invoke(null, new[] { o });
            var keyType = Asm("WindowsBase").GetType("System.Windows.Input.Key");
            var enter = Enum.Parse(keyType, "Enter");
            var kea = core.GetType("System.Windows.Input.KeyEventArgs");
            foreach (var evName in new[] { "PreviewKeyDownEvent", "KeyDownEvent" })
            {
                var args = Activator.CreateInstance(kea, dev, src, 0, enter);
                kea.GetProperty("RoutedEvent").SetValue(args, kb.GetField(evName).GetValue(null));
                o.GetType().GetMethod("RaiseEvent", new[] { core.GetType("System.Windows.RoutedEventArgs") }).Invoke(o, new[] { args });
            }
        }

        public static object Act(JsonElement args) => OnUi<object>(() =>
        {
            var o = Resolve(args.GetProperty("path").GetString(), out int item);
            switch (args.GetProperty("action").GetString())
            {
                case "invoke" when !Is(o, "ButtonBase"):
                    if (o.GetType().GetProperty("IsSelected") != null) Set(o, "IsSelected", true);
                    o.GetType().GetMethod("Focus", Type.EmptyTypes)?.Invoke(o, null);
                    RaiseEnter(o);
                    break;
                case "invoke":
                    var cmd = Get(o, "Command");
                    var param = Get(o, "CommandParameter");
                    if (cmd != null && (bool)cmd.GetType().GetMethod("CanExecute").Invoke(cmd, new[] { param }))
                        cmd.GetType().GetMethod("Execute").Invoke(cmd, new[] { param });
                    var click = Asm("PresentationFramework").GetType("System.Windows.Controls.Primitives.ButtonBase")
                        .GetField("ClickEvent", BindingFlags.Public | BindingFlags.Static).GetValue(null);
                    var rea = Asm("PresentationCore").GetType("System.Windows.RoutedEventArgs");
                    var ev = Activator.CreateInstance(rea, click);
                    o.GetType().GetMethod("RaiseEvent", new[] { rea }).Invoke(o, new[] { ev });
                    break;
                case "set_checked": Set(o, "IsChecked", args.GetProperty("checked").GetBoolean()); break;
                case "select":
                    if (item >= 0) Set(o, "SelectedIndex", item);
                    else if (Is(o, "TreeViewItem") || Is(o, "ListBoxItem")) Set(o, "IsSelected", true);
                    else Set(o, "IsChecked", true);
                    break;
                case "set_text": Set(o, "Text", args.GetProperty("text").GetString()); break;
                case "choose":
                    var want = args.GetProperty("option").GetString();
                    var items = (Get(o, "Items") as IEnumerable).Cast<object>().ToList();
                    int idx = items.FindIndex(x => ItemText(x) == want);
                    if (idx < 0) throw new InvalidOperationException($"no option '{want}'");
                    Set(o, "SelectedIndex", idx);
                    break;
                case "set_number": Set(o, "Value", args.GetProperty("value").GetDouble()); break;
                case "expand":
                    Set(o, "IsExpanded", args.TryGetProperty("expanded", out var ex) ? ex.GetBoolean() : true);
                    break;
                default: throw new InvalidOperationException("the WPF bridge has no '" + args.GetProperty("action").GetString() + "'");
            }
            return new { ok = true };
        });
    }
}

// CIG .NET bridge - reading and acting on the program's own UI objects (reflection only, no framework reference).
// Avalonia: Application.Current -> ApplicationLifetime.Windows -> the LOGICAL tree (ILogical.LogicalChildren), i.e. the
// app's own controls, not their template parts. Item controls (ComboBox, ListBox, TabControl) report their items as
// ListItem / TabItem children, which UI Automation could not see (probe 2026-11-20). Every read and write runs on
// Avalonia's UI thread through its Dispatcher. Nodes come back in CIG's fixture format so CIG's rules apply unchanged.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Cig.Bridge
{
    internal static class Ui
    {
        static Assembly Asm(string name) =>
            AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(a => a.GetName().Name == name);

        public static string Framework() => Asm("Avalonia.Base") != null ? "avalonia" : "unknown";

        // ---------------------------------------------------------------- reflection helpers
        static object Get(object o, string prop)
        {
            if (o == null) return null;
            for (var t = o.GetType(); t != null; t = t.BaseType)
            {
                var p = t.GetProperty(prop, BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
                if (p != null && p.GetIndexParameters().Length == 0) return p.GetValue(o);
            }
            return null;
        }

        static void Set(object o, string prop, object value)
        {
            var p = o.GetType().GetProperty(prop, BindingFlags.Public | BindingFlags.Instance);
            if (p == null) throw new InvalidOperationException($"{o.GetType().Name} has no {prop}");
            var target = Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;
            p.SetValue(o, value == null ? null : Convert.ChangeType(value, target));
        }

        static bool Is(object o, string typeName)
        {
            for (var t = o?.GetType(); t != null; t = t.BaseType)
                if (t.Name == typeName) return true;
            return false;
        }

        static T OnUi<T>(Func<T> f)
        {
            var dispType = Asm("Avalonia.Base")?.GetType("Avalonia.Threading.Dispatcher");
            var ui = dispType?.GetProperty("UIThread", BindingFlags.Public | BindingFlags.Static)?.GetValue(null);
            if (ui == null) return f();
            if ((bool)(dispType.GetMethod("CheckAccess")?.Invoke(ui, null) ?? false)) return f();
            T result = default;
            Exception err = null;
            Action a = () => { try { result = f(); } catch (Exception e) { err = e; } };
            var inv = dispType.GetMethods().First(m => m.Name == "Invoke" && !m.IsGenericMethod
                                                       && m.GetParameters().Length >= 1
                                                       && m.GetParameters()[0].ParameterType == typeof(Action));
            var ps = inv.GetParameters();
            var callArgs = new object[ps.Length];
            callArgs[0] = a;
            for (int i = 1; i < ps.Length; i++)
                callArgs[i] = ps[i].HasDefaultValue ? ps[i].DefaultValue
                    : (ps[i].ParameterType.IsValueType ? Activator.CreateInstance(ps[i].ParameterType) : null);
            inv.Invoke(ui, callArgs);
            if (err != null) throw err;
            return result;
        }

        static IList<object> Windows()
        {
            var appType = Asm("Avalonia.Controls")?.GetType("Avalonia.Application");
            var app = appType?.GetProperty("Current", BindingFlags.Public | BindingFlags.Static)?.GetValue(null);
            var life = Get(app, "ApplicationLifetime");
            var wins = Get(life, "Windows") as IEnumerable;
            var list = wins?.Cast<object>().ToList() ?? new List<object>();
            if (list.Count == 0 && Get(life, "MainWindow") is object mw) list.Add(mw);
            return list;
        }

        static IEnumerable<object> LogicalChildren(object o)
        {
            var ilogical = Asm("Avalonia.Base")?.GetType("Avalonia.LogicalTree.ILogical");
            var prop = ilogical?.GetProperty("LogicalChildren");
            if (prop == null || o == null || !ilogical.IsInstanceOfType(o)) return Array.Empty<object>();
            return (prop.GetValue(o) as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
        }

        static string AutomationName(object o)
        {
            var ap = Asm("Avalonia.Controls")?.GetType("Avalonia.Automation.AutomationProperties");
            var m = ap?.GetMethod("GetName", BindingFlags.Public | BindingFlags.Static);
            try { return m?.Invoke(null, new[] { o }) as string; } catch { return null; }
        }

        static string AutomationId(object o)
        {
            var ap = Asm("Avalonia.Controls")?.GetType("Avalonia.Automation.AutomationProperties");
            var m = ap?.GetMethod("GetAutomationId", BindingFlags.Public | BindingFlags.Static);
            try { return m?.Invoke(null, new[] { o }) as string; } catch { return null; }
        }

        static string ItemText(object item) =>
            item == null ? "" : (Get(item, "Content") as string ?? Get(item, "Header") as string ?? item.ToString());

        // ---------------------------------------------------------------- the tree
        public static object Tree() => OnUi(() =>
        {
            var wins = Windows();
            var nodes = new List<Dictionary<string, object>>();
            for (int i = 0; i < wins.Count; i++) nodes.Add(Node(wins[i], "w" + i, 0));
            return new { ok = true, framework = Framework(), windows = nodes };
        });

        static Dictionary<string, object> Node(object o, string path, int depth)
        {
            var n = new Dictionary<string, object> { ["bridge"] = path, ["framework_id"] = "Avalonia(bridge)" };
            string ct = "Group";
            var pats = new List<string>();
            string name = AutomationName(o);
            string aid = AutomationId(o);
            if (string.IsNullOrEmpty(aid)) aid = Get(o, "Name") as string;
            bool synthItems = false;

            if (Is(o, "Window")) { ct = "Window"; pats.Add("Window"); name ??= Get(o, "Title") as string; }
            else if (Is(o, "RadioButton")) { ct = "RadioButton"; pats.Add("SelectionItem"); n["selected"] = Get(o, "IsChecked") as bool? == true; }
            else if (Is(o, "ToggleSwitch") || Is(o, "CheckBox") || Is(o, "ToggleButton"))
            {
                ct = "CheckBox"; pats.Add("Toggle");
                n["toggle_state"] = (Get(o, "IsChecked") as bool?) == true ? "On" : "Off";
            }
            else if (Is(o, "Button")) { ct = "Button"; pats.Add("Invoke"); }
            else if (Is(o, "TextBox"))
            {
                ct = "Edit"; pats.Add("Value");
                var pc = Get(o, "PasswordChar");
                bool secret = pc is char c && c != '\0';
                if (secret) n["is_password"] = true; else n["value"] = Get(o, "Text") as string ?? "";
                n["is_read_only"] = (Get(o, "IsReadOnly") as bool?) == true;
            }
            else if (Is(o, "ComboBox"))
            {
                ct = "ComboBox"; pats.Add("Selection"); pats.Add("ExpandCollapse");
                n["value"] = ItemText(Get(o, "SelectedItem")); synthItems = true;
            }
            else if (Is(o, "ListBox")) { ct = "List"; pats.Add("Selection"); synthItems = true; }
            else if (Is(o, "TabControl")) { ct = "Tab"; pats.Add("Selection"); synthItems = true; }
            else if (Is(o, "Slider") || Is(o, "NumericUpDown"))
            {
                ct = Is(o, "Slider") ? "Slider" : "Spinner"; pats.Add("RangeValue");
                n["range"] = new Dictionary<string, object>
                {
                    ["min"] = Convert.ToDouble(Get(o, "Minimum") ?? 0.0), ["max"] = Convert.ToDouble(Get(o, "Maximum") ?? 0.0),
                    ["value"] = Convert.ToDouble(Get(o, "Value") ?? 0.0),
                };
            }
            else if (Is(o, "TextBlock")) { ct = "Text"; name ??= Get(o, "Text") as string; }
            else if (Is(o, "Expander"))
            {
                ct = "TreeItem"; pats.Add("ExpandCollapse");
                n["expand_state"] = (Get(o, "IsExpanded") as bool?) == true ? "Expanded" : "Collapsed";
                name ??= Get(o, "Header") as string;
            }
            name ??= Get(o, "Content") as string;
            n["control_type"] = ct;
            if (!string.IsNullOrEmpty(name)) n["name"] = name;
            if (!string.IsNullOrEmpty(aid)) n["automation_id"] = aid;
            n["patterns"] = pats;
            if ((Get(o, "IsEnabled") as bool?) == false) n["enabled"] = false;

            var kids = new List<Dictionary<string, object>>();
            if (synthItems)
            {
                var items = (Get(o, "Items") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
                int sel = Convert.ToInt32(Get(o, "SelectedIndex") ?? -1);
                bool tabs = Is(o, "TabControl");
                for (int i = 0; i < items.Count; i++)
                    kids.Add(new Dictionary<string, object>
                    {
                        ["control_type"] = tabs ? "TabItem" : "ListItem", ["name"] = ItemText(items[i]),
                        ["patterns"] = new List<string> { "SelectionItem" }, ["selected"] = i == sel,
                        ["bridge"] = path + "/i" + i, ["framework_id"] = "Avalonia(bridge)",
                    });
            }
            else if (depth < 40)
            {
                int i = 0;
                foreach (var c in LogicalChildren(o)) kids.Add(Node(c, path + "/" + i++, depth + 1));
            }
            if (kids.Count > 0) n["children"] = kids;
            return n;
        }

        // ---------------------------------------------------------------- acting
        static object Resolve(string path, out int itemIndex)
        {
            itemIndex = -1;
            var parts = path.Split('/');
            object o = Windows()[int.Parse(parts[0].Substring(1))];
            for (int k = 1; k < parts.Length; k++)
            {
                if (parts[k].StartsWith("i")) { itemIndex = int.Parse(parts[k].Substring(1)); break; }
                o = LogicalChildren(o).ElementAt(int.Parse(parts[k]));
            }
            return o;
        }

        public static object Act(JsonElement args) => OnUi<object>(() =>
        {
            string path = args.GetProperty("path").GetString();
            string action = args.GetProperty("action").GetString();
            var o = Resolve(path, out int item);
            switch (action)
            {
                case "invoke":
                    var cmd = Get(o, "Command");
                    var param = Get(o, "CommandParameter");
                    if (cmd != null && (bool)cmd.GetType().GetMethod("CanExecute").Invoke(cmd, new[] { param }))
                        cmd.GetType().GetMethod("Execute").Invoke(cmd, new[] { param });
                    var clickEvent = o.GetType().GetField("ClickEvent", BindingFlags.Public | BindingFlags.Static
                                                                        | BindingFlags.FlattenHierarchy)?.GetValue(null);
                    if (clickEvent != null)
                    {
                        var argsType = Asm("Avalonia.Base")?.GetType("Avalonia.Interactivity.RoutedEventArgs");
                        var ev = Activator.CreateInstance(argsType, clickEvent);
                        o.GetType().GetMethod("RaiseEvent", new[] { argsType })?.Invoke(o, new[] { ev });
                    }
                    break;
                case "set_checked":
                    Set(o, "IsChecked", args.GetProperty("checked").GetBoolean());
                    break;
                case "select":
                    if (item >= 0) Set(o, "SelectedIndex", item); else Set(o, "IsChecked", true);
                    break;
                case "set_text":
                    Set(o, "Text", args.GetProperty("text").GetString());
                    break;
                case "choose":
                    var want = args.GetProperty("option").GetString();
                    var items = (Get(o, "Items") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
                    int idx = items.FindIndex(x => ItemText(x) == want);
                    if (idx < 0) throw new InvalidOperationException($"no option '{want}'");
                    Set(o, "SelectedIndex", idx);
                    break;
                case "set_number":
                    Set(o, "Value", args.GetProperty("value").GetDouble());
                    break;
                case "expand":
                    Set(o, "IsExpanded", args.TryGetProperty("expanded", out var ex) ? ex.GetBoolean() : true);
                    break;
                default:
                    throw new InvalidOperationException($"the bridge has no '{action}'");
            }
            return new { ok = true };
        });
    }
}

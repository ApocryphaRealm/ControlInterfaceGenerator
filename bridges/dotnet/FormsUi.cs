// CIG .NET bridge - Windows Forms (.NET 5+), by reflection. Windows: Application.OpenForms. Tree: Control.Controls.
// Thread: the form's own Invoke. TreeView nodes, TabPages and list/combo items become real elements; a TextBox with a
// PasswordChar or UseSystemPasswordChar is a password field whose value is never read.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using static Cig.Bridge.Ui;

namespace Cig.Bridge
{
    internal static class FormsUi
    {
        static List<object> Forms()
        {
            var app = Asm("System.Windows.Forms")?.GetType("System.Windows.Forms.Application");
            var open = app?.GetProperty("OpenForms", BindingFlags.Public | BindingFlags.Static)?.GetValue(null) as IEnumerable;
            return open?.Cast<object>().ToList() ?? new List<object>();
        }

        public static bool HasForms() => Forms().Count > 0;

        static T OnUi<T>(Func<T> f)
        {
            var form = Forms().FirstOrDefault();
            if (form == null || !(bool)Get(form, "InvokeRequired")) return f();
            T result = default;
            Exception err = null;
            Action a = () => { try { result = f(); } catch (Exception e) { err = e; } };
            form.GetType().GetMethod("Invoke", new[] { typeof(Delegate) }).Invoke(form, new object[] { a });
            if (err != null) throw err;
            return result;
        }

        static List<object> Controls(object o) => (Get(o, "Controls") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();

        static string ItemTextOf(object owner, object item)
        {
            var m = owner.GetType().GetMethod("GetItemText", new[] { typeof(object) });
            return m != null ? m.Invoke(owner, new[] { item }) as string : ItemText(item);
        }

        public static object Tree() => OnUi(() =>
        {
            var forms = Forms();
            var nodes = new List<Dictionary<string, object>>();
            for (int i = 0; i < forms.Count; i++) nodes.Add(Node(forms[i], "w" + i, 0));
            return new { ok = true, framework = "winforms", windows = nodes };
        });

        static Dictionary<string, object> TreeNodeOf(object node, string path)
        {
            var n = new Dictionary<string, object>
            {
                ["control_type"] = "TreeItem", ["name"] = Get(node, "Text") as string ?? "",
                ["patterns"] = new List<string> { "SelectionItem" }, ["bridge"] = path,
                ["selected"] = (Get(node, "IsSelected") as bool?) == true, ["framework_id"] = "WinForms(bridge)",
            };
            var kids = (Get(node, "Nodes") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
            if (kids.Count > 0)
            {
                ((List<string>)n["patterns"]).Add("ExpandCollapse");
                n["expand_state"] = (Get(node, "IsExpanded") as bool?) == true ? "Expanded" : "Collapsed";
                n["children"] = kids.Select((k, i) => TreeNodeOf(k, path + "/t" + i)).ToList();
            }
            return n;
        }

        static Dictionary<string, object> Node(object o, string path, int depth)
        {
            var n = new Dictionary<string, object> { ["bridge"] = path, ["framework_id"] = "WinForms(bridge)" };
            var pats = new List<string>();
            string ct = "Group";
            string name = Get(o, "AccessibleName") as string;
            string aid = Get(o, "Name") as string;
            string text = Get(o, "Text") as string;
            var kids = new List<Dictionary<string, object>>();
            bool descend = true;

            if (Is(o, "Form")) { ct = "Window"; pats.Add("Window"); name ??= text; }
            else if (Is(o, "RadioButton")) { ct = "RadioButton"; pats.Add("SelectionItem"); n["selected"] = (bool)Get(o, "Checked"); name ??= text; }
            else if (Is(o, "CheckBox")) { ct = "CheckBox"; pats.Add("Toggle"); n["toggle_state"] = (bool)Get(o, "Checked") ? "On" : "Off"; name ??= text; }
            else if (Is(o, "ButtonBase")) { ct = "Button"; pats.Add("Invoke"); name ??= text; }
            else if (Is(o, "TextBoxBase"))
            {
                ct = "Edit"; pats.Add("Value");
                var pc = Get(o, "PasswordChar");
                bool secret = (Get(o, "UseSystemPasswordChar") as bool?) == true || (pc is char c && c != '\0');
                if (secret) n["is_password"] = true; else n["value"] = text ?? "";
                n["is_read_only"] = (Get(o, "ReadOnly") as bool?) == true;
                descend = false;
            }
            else if (Is(o, "ComboBox") || Is(o, "ListBox"))
            {
                bool combo = Is(o, "ComboBox");
                ct = combo ? "ComboBox" : "List";
                pats.Add("Selection"); if (combo) pats.Add("ExpandCollapse");
                var items = (Get(o, "Items") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
                int sel = Convert.ToInt32(Get(o, "SelectedIndex"));
                for (int i = 0; i < items.Count; i++)
                    kids.Add(new Dictionary<string, object>
                    {
                        ["control_type"] = "ListItem", ["name"] = ItemTextOf(o, items[i]), ["selected"] = i == sel,
                        ["patterns"] = new List<string> { "SelectionItem" }, ["bridge"] = path + "/i" + i,
                        ["framework_id"] = "WinForms(bridge)",
                    });
                if (combo) n["value"] = sel >= 0 && sel < items.Count ? ItemTextOf(o, items[sel]) : (text ?? "");
                descend = false;
            }
            else if (Is(o, "NumericUpDown") || Is(o, "TrackBar"))
            {
                ct = Is(o, "TrackBar") ? "Slider" : "Spinner"; pats.Add("RangeValue");
                n["range"] = new Dictionary<string, object>
                {
                    ["min"] = Convert.ToDouble(Get(o, "Minimum")), ["max"] = Convert.ToDouble(Get(o, "Maximum")),
                    ["value"] = Convert.ToDouble(Get(o, "Value")),
                };
                descend = false;
            }
            else if (Is(o, "TreeView"))
            {
                ct = "Tree";
                var nodes = (Get(o, "Nodes") as IEnumerable)?.Cast<object>().ToList() ?? new List<object>();
                kids.AddRange(nodes.Select((k, i) => TreeNodeOf(k, path + "/t" + i)));
                descend = false;
            }
            else if (Is(o, "TabControl"))
            {
                ct = "Tab"; pats.Add("Selection");
                var pages = Controls(o);
                int sel = Convert.ToInt32(Get(o, "SelectedIndex"));
                for (int i = 0; i < pages.Count; i++)
                    kids.Add(new Dictionary<string, object>
                    {
                        ["control_type"] = "TabItem", ["name"] = Get(pages[i], "Text") as string ?? "",
                        ["selected"] = i == sel, ["patterns"] = new List<string> { "SelectionItem" },
                        ["bridge"] = path + "/i" + i, ["framework_id"] = "WinForms(bridge)",
                    });
                if (sel >= 0 && sel < pages.Count && depth < 40)    // the open page's controls stay reachable
                {
                    int k = 0;
                    foreach (var c in Controls(pages[sel])) kids.Add(Node(c, path + "/i" + sel + "/" + k++, depth + 1));
                }
                descend = false;
            }
            else if (Is(o, "Label")) { ct = "Text"; name ??= text; }
            n["control_type"] = ct;
            if (!string.IsNullOrEmpty(name)) n["name"] = name;
            if (!string.IsNullOrEmpty(aid)) n["automation_id"] = aid;
            n["patterns"] = pats;
            if ((Get(o, "Enabled") as bool?) == false) n["enabled"] = false;
            if (descend && depth < 40)
            {
                int i = 0;
                foreach (var c in Controls(o)) kids.Add(Node(c, path + "/" + i++, depth + 1));
            }
            if (kids.Count > 0) n["children"] = kids;
            return n;
        }

        static object Resolve(string path, out int item, out object treeNode)
        {
            item = -1; treeNode = null;
            var parts = path.Split('/');
            object o = Forms()[int.Parse(parts[0].Substring(1))];
            for (int k = 1; k < parts.Length; k++)
            {
                string p = parts[k];
                if (p.StartsWith("t"))
                {
                    var coll = treeNode == null ? Get(o, "Nodes") : Get(treeNode, "Nodes");
                    treeNode = (coll as IEnumerable).Cast<object>().ElementAt(int.Parse(p.Substring(1)));
                    continue;
                }
                if (p.StartsWith("i"))
                {
                    int idx = int.Parse(p.Substring(1));
                    if (k == parts.Length - 1) { item = idx; break; }
                    o = Controls(o)[idx];                     // into the open TabPage
                    continue;
                }
                o = Controls(o)[int.Parse(p)];
            }
            return o;
        }

        public static object Act(JsonElement args) => OnUi<object>(() =>
        {
            var o = Resolve(args.GetProperty("path").GetString(), out int item, out object node);
            string action = args.GetProperty("action").GetString();
            if (node != null)
            {
                if (action == "select") Set(o, "SelectedNode", node);
                else if (action == "expand")
                {
                    bool open = !args.TryGetProperty("expanded", out var ex) || ex.GetBoolean();
                    node.GetType().GetMethod(open ? "Expand" : "Collapse", Type.EmptyTypes).Invoke(node, null);
                }
                else throw new InvalidOperationException($"the WinForms bridge has no '{action}' for a tree node");
                return new { ok = true };
            }
            switch (action)
            {
                case "invoke": o.GetType().GetMethod("PerformClick", Type.EmptyTypes).Invoke(o, null); break;
                case "set_checked": Set(o, "Checked", args.GetProperty("checked").GetBoolean()); break;
                case "select":
                    if (item >= 0) Set(o, "SelectedIndex", item); else Set(o, "Checked", true);
                    break;
                case "set_text": Set(o, "Text", args.GetProperty("text").GetString()); break;
                case "choose":
                    var want = args.GetProperty("option").GetString();
                    var items = (Get(o, "Items") as IEnumerable).Cast<object>().ToList();
                    int idx = items.FindIndex(x => ItemTextOf(o, x) == want);
                    if (idx < 0) throw new InvalidOperationException($"no option '{want}'");
                    Set(o, "SelectedIndex", idx);
                    break;
                case "set_number": Set(o, "Value", args.GetProperty("value").GetDouble()); break;
                default: throw new InvalidOperationException($"the WinForms bridge has no '{action}'");
            }
            return new { ok = true };
        });
    }
}

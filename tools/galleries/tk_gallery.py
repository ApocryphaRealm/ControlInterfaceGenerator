"""CIG reference gallery - Tk 8.6 (Python's tkinter, which ships with Python; nothing downloaded).
Classic Tk widgets and themed ttk widgets side by side. Run: py -3 tk_gallery.py"""
import tkinter as tk
from tkinter import ttk


def main():
    root = tk.Tk()
    root.title("CIG Tk Gallery")
    root.geometry("520x560")
    tk.Button(root, text="Press me").pack(anchor="w", padx=10, pady=4)
    ttk.Button(root, text="Themed press me").pack(anchor="w", padx=10, pady=4)
    tk.Checkbutton(root, text="A checkbox", variable=tk.IntVar(root)).pack(anchor="w", padx=10)
    ttk.Checkbutton(root, text="A themed checkbox", variable=tk.IntVar(root)).pack(anchor="w", padx=10)
    rv = tk.StringVar(root, "one")
    tk.Radiobutton(root, text="Radio one", variable=rv, value="one").pack(anchor="w", padx=10)
    tk.Radiobutton(root, text="Radio two", variable=rv, value="two").pack(anchor="w", padx=10)
    tk.Label(root, text="Text field:").pack(anchor="w", padx=10)
    tk.Entry(root, width=40).pack(anchor="w", padx=10)
    tk.Label(root, text="Password field:").pack(anchor="w", padx=10)
    tk.Entry(root, width=40, show="*").pack(anchor="w", padx=10)
    cb = ttk.Combobox(root, values=["Alpha", "Beta", "Gamma"], state="readonly")
    cb.current(0)
    cb.pack(anchor="w", padx=10, pady=4)
    lb = tk.Listbox(root, height=3)
    for s in ("One", "Two", "Three"):
        lb.insert("end", s)
    lb.pack(anchor="w", padx=10)
    tk.Scale(root, from_=0, to=10, orient="horizontal", label="Slider").pack(anchor="w", padx=10)
    tk.Spinbox(root, from_=0, to=100, width=6).pack(anchor="w", padx=10)
    tree = ttk.Treeview(root, height=3, show="tree")
    r = tree.insert("", "end", text="Root")
    tree.insert(r, "end", text="Child A")
    tree.insert(r, "end", text="Child B")
    tree.pack(anchor="w", padx=10, pady=4)
    nb = ttk.Notebook(root)
    nb.add(ttk.Frame(nb, height=20), text="First tab")
    nb.add(ttk.Frame(nb, height=20), text="Second tab")
    nb.pack(anchor="w", padx=10)
    root.mainloop()


if __name__ == "__main__":
    main()

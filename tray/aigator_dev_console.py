"""AI Gator Developer Console — live log viewer.

Opened from the tray menu by power users.
Tails %LOCALAPPDATA%/AIGator/logs/aigator.log in real time.
"""
import os
import threading
import time
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from pathlib import Path

LOG_FILE = Path.home() / "AppData" / "Local" / "AIGator" / "logs" / "aigator.log"

BG = "#0d1117"
FG = "#4ade80"
FG_DIM = "#64748b"
BTN_BG = "#1e293b"


def tail_log(widget: ScrolledText):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    with open(LOG_FILE, "r", errors="replace") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                widget.configure(state="normal")
                widget.insert("end", line)
                widget.see("end")
                widget.configure(state="disabled")
            else:
                time.sleep(0.4)


def open_log_file():
    os.startfile(str(LOG_FILE))


def clear_display(widget: ScrolledText):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.configure(state="disabled")


def main():
    root = tk.Tk()
    root.title("AI Gator — Developer Console")
    root.configure(bg=BG)
    root.geometry("960x520")
    root.minsize(600, 300)

    try:
        icon_path = Path(__file__).parent / "aigator_icon.png"
        if icon_path.exists():
            from PIL import Image, ImageTk
            img = ImageTk.PhotoImage(Image.open(icon_path).resize((32, 32)))
            root.iconphoto(True, img)
    except Exception:
        pass

    header = tk.Frame(root, bg=BG, pady=6)
    header.pack(fill="x", padx=10)

    tk.Label(header, text="🐊 AI Gator — Developer Console",
             bg=BG, fg=FG, font=("Segoe UI", 12, "bold")).pack(side="left")

    tk.Button(header, text="Open Log File", bg=BTN_BG, fg=FG_DIM,
              relief="flat", padx=8, command=open_log_file).pack(side="right", padx=4)

    txt = ScrolledText(root, bg=BG, fg=FG, insertbackground=FG,
                       font=("Consolas", 10), state="disabled",
                       wrap="word", relief="flat", borderwidth=0)
    txt.pack(fill="both", expand=True, padx=10, pady=(0, 6))

    tk.Button(root, text="Clear", bg=BTN_BG, fg=FG_DIM, relief="flat",
              padx=8, command=lambda: clear_display(txt)).pack(pady=(0, 8))

    threading.Thread(target=tail_log, args=(txt,), daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()

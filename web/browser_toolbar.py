"""HITL Browser Toolbar — floating control bar for browser automation.

Shows agent status and provides Take over / Hand back controls.
Runs in its own thread with tkinter. Communicates with the browser
agent via threading events (pause/resume).
"""
import threading
import logging
import tkinter as tk

_log = logging.getLogger(__name__)


class BrowserToolbar:
    """Floating toolbar for HITL browser control.

    Usage:
        toolbar = BrowserToolbar()
        toolbar.start()
        toolbar.set_status("Searching Amazon...")

        # When agent should pause (user clicks Take over):
        # toolbar.is_paused becomes True

        # When user hands back:
        # toolbar.is_paused becomes False, toolbar.annotation has user's note

        toolbar.stop()
    """

    def __init__(self):
        self._thread = None
        self._root = None
        self._running = False
        self._state = "driving"  # driving | paused | error
        self._status_text = "Starting browser..."
        self.is_paused = threading.Event()  # Clear = not paused, Set = paused
        self.annotation = ""
        self._update_pending = threading.Event()

    def start(self):
        """Start the toolbar in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self.is_paused.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop and destroy the toolbar."""
        self._running = False
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def set_status(self, text):
        """Update the status text (thread-safe)."""
        self._status_text = text
        self._request_update()

    def set_error(self, text):
        """Switch to error state (thread-safe)."""
        self._state = "error"
        self._status_text = text
        self._request_update()

    def _request_update(self):
        """Signal the tkinter thread to update UI."""
        self._update_pending.set()
        if self._root:
            try:
                self._root.event_generate("<<UpdateUI>>", when="tail")
            except Exception:
                pass

    def _run(self):
        """Main toolbar thread."""
        self._root = tk.Tk()
        self._root.title("AI Gator")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.93)

        # Position: top-center of screen
        screen_w = self._root.winfo_screenwidth()
        toolbar_w = 520
        toolbar_h = 44
        x = (screen_w - toolbar_w) // 2
        self._root.geometry(f"{toolbar_w}x{toolbar_h}+{x}+8")

        # Colors
        self._colors = {
            "driving": {"bg": "#1e3a5f", "fg": "#e2e8f0", "btn_bg": "#166534", "btn_fg": "white"},
            "paused":  {"bg": "#334155", "fg": "#e2e8f0", "btn_bg": "#166534", "btn_fg": "white"},
            "error":   {"bg": "#7f1d1d", "fg": "#fca5a5", "btn_bg": "#dc2626", "btn_fg": "white"},
        }

        # Main frame
        frame = tk.Frame(self._root, bg=self._colors["driving"]["bg"])
        frame.pack(fill="both", expand=True, padx=6, pady=4)

        # Gator icon
        self._icon_label = tk.Label(frame, text="\U0001F40A", font=("Segoe UI", 12),
                                     bg=self._colors["driving"]["bg"], fg="#4ade80")
        self._icon_label.pack(side="left", padx=(4, 6))

        # Status text
        self._status_label = tk.Label(frame, text="", font=("Segoe UI", 10),
                                       bg=self._colors["driving"]["bg"],
                                       fg=self._colors["driving"]["fg"],
                                       anchor="w")
        self._status_label.pack(side="left", fill="x", expand=True)

        # Annotation entry (hidden by default)
        self._annotation_var = tk.StringVar()
        self._annotation_entry = tk.Entry(frame, textvariable=self._annotation_var,
                                           font=("Segoe UI", 9), bg="#2d4a6f", fg="#e2e8f0",
                                           insertbackground="#e2e8f0", relief="flat", width=20)

        # Close button
        self._close_btn = tk.Button(frame, text="\u2715", font=("Segoe UI", 9),
                                     bg=self._colors["driving"]["bg"], fg="#64748b",
                                     relief="flat", padx=4, pady=0, cursor="hand2",
                                     command=self.stop)
        self._close_btn.pack(side="right", padx=(2, 2))

        # Action button
        self._action_btn = tk.Button(frame, text="Take over", font=("Segoe UI", 9, "bold"),
                                      bg="#166534", fg="white", relief="flat",
                                      padx=10, pady=2, cursor="hand2",
                                      command=self._on_action)
        self._action_btn.pack(side="right", padx=(6, 0))

        # Bind update event
        self._root.bind("<<UpdateUI>>", lambda e: self._update_ui())
        self._frame = frame

        # Initial UI
        self._update_ui()

        self._root.mainloop()
        self._running = False

    def _update_ui(self):
        """Update UI based on current state."""
        if not self._root or not self._status_label:
            return
        self._update_pending.clear()
        c = self._colors.get(self._state, self._colors["driving"])

        try:
            self._root.configure(bg=c["bg"])
            self._frame.configure(bg=c["bg"])
            self._icon_label.configure(bg=c["bg"])
            self._status_label.configure(bg=c["bg"], fg=c["fg"])

            if self._state == "driving":
                self._status_label.configure(text=f"Gator is working \u00B7 {self._status_text}")
                self._action_btn.configure(text="Take over", bg=c["btn_bg"], fg=c["btn_fg"])
                self._annotation_entry.pack_forget()
            elif self._state == "paused":
                self._status_label.configure(text="You're in control \u00B7 Gator is paused")
                self._action_btn.configure(text="Hand back \u2192", bg=c["btn_bg"], fg=c["btn_fg"])
                self._annotation_entry.pack(side="right", padx=(4, 0))
                self._annotation_var.set("")
                self._annotation_entry.focus()
            elif self._state == "error":
                self._status_label.configure(text=f"Needs help \u00B7 {self._status_text}")
                self._action_btn.configure(text="Take over", bg=c["btn_bg"], fg=c["btn_fg"])
                self._annotation_entry.pack_forget()
        except Exception:
            pass

    def _on_action(self):
        """Handle Take over / Hand back button click."""
        if self._state == "driving" or self._state == "error":
            # User takes over
            self._state = "paused"
            self.is_paused.set()  # Signal the agent to pause
            self._update_ui()
            _log.info("[toolbar] User took over")
        elif self._state == "paused":
            # User hands back
            self.annotation = self._annotation_var.get().strip()
            self._state = "driving"
            self._status_text = "Resuming..."
            self._update_ui()
            # 2-second grace period before unpausing
            self._root.after(2000, self._do_handback)

    def _do_handback(self):
        """Resume agent after grace period."""
        self.is_paused.clear()  # Unblock the agent
        _log.info("[toolbar] User handed back. Note: %s", self.annotation or "(none)")

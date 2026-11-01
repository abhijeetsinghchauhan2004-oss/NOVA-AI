import tkinter as tk
from tkinter import messagebox
import speech_recognition as sr
import threading
import datetime
import subprocess
import webbrowser
import platform

from db import (
    connect_db,
    register_user,
    login_with_pin
)


# ================= MAIN WINDOW =================

root = tk.Tk()
root.title("NOVA AI")
root.geometry("420x520")
root.configure(bg="#101827")

current_user = None
current_session_id = None

popup = None
popup_open = False
assistant_active = False
status_label = None
login_screen_open = False
app_running = True


# ================= DATABASE HISTORY =================

def save_voice_command(command_text, command_type):
    if not current_user:
        return

    connection = connect_db()
    if connection is None:
        return

    cursor = None

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO voice_commands
            (user_id, command_text, command_type)
            VALUES (%s, %s, %s)
            """,
            (
                current_user["user_id"],
                command_text,
                command_type
            )
        )
        connection.commit()
        print("Command saved:", command_text)

    except Exception as e:
        connection.rollback()
        print("History error:", e)

    finally:
        if cursor:
            cursor.close()
        connection.close()


def create_session():
    global current_session_id

    if not current_user:
        return

    connection = connect_db()
    if connection is None:
        return

    cursor = None

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO user_sessions (user_id)
            VALUES (%s)
            """,
            (current_user["user_id"],)
        )
        current_session_id = cursor.lastrowid
        connection.commit()

    except Exception as e:
        connection.rollback()
        print("Session error:", e)

    finally:
        if cursor:
            cursor.close()
        connection.close()


def close_session():
    global current_session_id

    if current_session_id is None:
        return

    connection = connect_db()
    if connection is None:
        return

    cursor = None

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE user_sessions
            SET logout_time = NOW(),
                session_status = 'Closed'
            WHERE session_id = %s
            """,
            (current_session_id,)
        )
        connection.commit()

    except Exception as e:
        connection.rollback()
        print("Logout error:", e)

    finally:
        if cursor:
            cursor.close()
        connection.close()
        current_session_id = None


# ================= UI HELPERS =================

def clear_screen():
    for widget in root.winfo_children():
        widget.destroy()


def make_button(parent, text, command):
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=("Arial", 11, "bold"),
        bg="#0284c7",
        fg="white",
        activebackground="#0369a1",
        activeforeground="white",
        relief="flat",
        cursor="hand2",
        width=25,
        pady=9
    )


def show_idle_screen():
    """Show this screen while NOVA waits for its wake word."""
    clear_screen()
    root.deiconify()

    tk.Label(
        root,
        text="NOVA AI",
        font=("Arial", 30, "bold"),
        fg="#38bdf8",
        bg="#101827"
    ).pack(pady=(95, 15))

    tk.Label(
        root,
        text='Say "Hello Nova" or "Hey Nova"',
        font=("Arial", 13),
        fg="white",
        bg="#101827"
    ).pack(pady=10)

    tk.Label(
        root,
        text="Waiting for wake word...",
        font=("Arial", 11),
        fg="#7dd3fc",
        bg="#101827"
    ).pack(pady=15)

    tk.Button(
        root,
        text="EXIT",
        command=on_app_close,
        bg="#dc2626",
        fg="white",
        relief="flat",
        width=12,
        pady=7
    ).pack(pady=45)


# ================= LOGIN SCREEN =================

def show_login():
    global login_screen_open

    clear_screen()
    root.deiconify()
    root.lift()

    tk.Label(
        root,
        text="NOVA AI",
        font=("Arial", 28, "bold"),
        fg="#38bdf8",
        bg="#101827"
    ).pack(pady=(50, 10))

    tk.Label(
        root,
        text="Wake word detected!",
        font=("Arial", 12),
        fg="#7dd3fc",
        bg="#101827"
    ).pack(pady=5)

    tk.Label(
        root,
        text="Enter your PIN to continue",
        font=("Arial", 12),
        fg="white",
        bg="#101827"
    ).pack(pady=15)

    pin_entry = tk.Entry(
        root,
        font=("Arial", 16),
        width=20,
        show="*",
        justify="center"
    )
    pin_entry.pack(ipady=8)
    pin_entry.focus_set()

    def handle_login():
        pin = pin_entry.get().strip()

        if len(pin) not in (4, 5, 6) or not pin.isdigit():
            messagebox.showwarning(
                "NOVA",
                "Enter a valid 4 to 6 digit PIN."
            )
            return

        try:
            user, message = login_with_pin(pin)
        except Exception as e:
            messagebox.showerror("Database Error", str(e))
            return

        if user:
            global current_user
            current_user = user
            login_screen_open = False

            messagebox.showinfo(
                "NOVA",
                f"Welcome {user['username']}!"
            )
            start_assistant()

        else:
            messagebox.showerror("Login Failed", message)
            pin_entry.delete(0, tk.END)
            pin_entry.focus_set()

    make_button(root, "LOGIN", handle_login).pack(pady=25)

    tk.Button(
        root,
        text="New user? Create Account",
        command=show_register,
        bg="#101827",
        fg="#38bdf8",
        activebackground="#101827",
        relief="flat"
    ).pack()

    tk.Button(
        root,
        text="Back",
        command=back_to_idle,
        bg="#101827",
        fg="#94a3b8",
        activebackground="#101827",
        relief="flat"
    ).pack(pady=10)


def back_to_idle():
    global login_screen_open
    login_screen_open = False
    show_idle_screen()


# ================= REGISTRATION SCREEN =================

def show_register():
    clear_screen()

    tk.Label(
        root,
        text="CREATE ACCOUNT",
        font=("Arial", 23, "bold"),
        fg="#38bdf8",
        bg="#101827"
    ).pack(pady=25)

    fields = {}

    for label in ["Username", "Email", "PIN", "Confirm PIN"]:

        tk.Label(
            root,
            text=label,
            fg="white",
            bg="#101827"
        ).pack(pady=(8, 4))

        entry = tk.Entry(
            root,
            font=("Arial", 12),
            width=30,
            show="*" if "PIN" in label else ""
        )

        entry.pack(ipady=6)
        fields[label] = entry

    def handle_register():
        username = fields["Username"].get().strip()
        email = fields["Email"].get().strip()
        pin = fields["PIN"].get().strip()
        confirm_pin = fields["Confirm PIN"].get().strip()

        if not username or not email or not pin or not confirm_pin:
            messagebox.showwarning(
                "NOVA",
                "All fields are required."
            )
            return

        if "@" not in email or "." not in email:
            messagebox.showwarning(
                "NOVA",
                "Enter a valid email."
            )
            return

        if len(pin) not in (4, 5, 6) or not pin.isdigit():
            messagebox.showwarning(
                "NOVA",
                "PIN must contain 4 to 6 digits."
            )
            return

        if pin != confirm_pin:
            messagebox.showerror(
                "NOVA",
                "PINs do not match."
            )
            return

        try:
            success, message = register_user(
                username,
                email,
                pin
            )
        except Exception as e:
            messagebox.showerror("Registration Error", str(e))
            return

        if success:
            messagebox.showinfo("NOVA", message)
            show_login()
        else:
            messagebox.showerror("Registration Failed", message)

    make_button(
        root,
        "CREATE ACCOUNT",
        handle_register
    ).pack(pady=20)

    tk.Button(
        root,
        text="Back to PIN Login",
        command=show_login,
        bg="#101827",
        fg="#38bdf8",
        relief="flat"
    ).pack()


# ================= TASKS =================

def show_time():
    current_time = datetime.datetime.now().strftime("%I:%M %p")
    messagebox.showinfo("NOVA", f"The time is {current_time}")


def show_date():
    today = datetime.datetime.now().strftime("%d %B %Y")
    messagebox.showinfo("NOVA", f"Today's date is {today}")


def open_notepad():
    if platform.system() == "Windows":
        subprocess.Popen(["notepad.exe"])


def open_calculator():
    if platform.system() == "Windows":
        subprocess.Popen(["calc.exe"])


def open_youtube():
    webbrowser.open("https://www.youtube.com")


# ================= COMMAND STATUS =================

def update_status(text):
    def update():
        if popup_open and status_label and popup and popup.winfo_exists():
            status_label.config(text=text)

    root.after(0, update)


# ================= COMMAND EXECUTION =================

def execute_command(words):
    words = words.lower().strip()

    if "time" in words:
        command_type = "information"
        task = show_time

    elif "date" in words or "today" in words:
        command_type = "information"
        task = show_date

    elif "notepad" in words:
        command_type = "application"
        task = open_notepad

    elif "calculator" in words or "calculate" in words:
        command_type = "application"
        task = open_calculator

    elif "youtube" in words:
        command_type = "application"
        task = open_youtube

    elif "close nova" in words or "logout nova" in words:
        command_type = "assistant_control"
        task = close_popup

    else:
        update_status("Command not recognised.")
        return

    save_voice_command(words, command_type)
    update_status("Executing: " + words)
    root.after(0, task)


# ================= POPUP =================

def close_popup():
    global popup, popup_open, assistant_active, current_user

    assistant_active = False
    popup_open = False

    if popup:
        try:
            popup.destroy()
        except tk.TclError:
            pass
        popup = None

    close_session()
    current_user = None
    show_idle_screen()


def show_popup():
    global popup, popup_open, status_label

    if popup_open or not current_user:
        return

    popup_open = True

    popup = tk.Toplevel(root)
    popup.title("NOVA AI")
    popup.geometry("360x440")
    popup.configure(bg="#101827")
    popup.attributes("-topmost", True)
    popup.protocol("WM_DELETE_WINDOW", close_popup)

    tk.Label(
        popup,
        text="NOVA AI",
        font=("Arial", 25, "bold"),
        fg="#38bdf8",
        bg="#101827"
    ).pack(pady=(20, 5))

    tk.Label(
        popup,
        text=f"Welcome {current_user['username']}!",
        fg="white",
        bg="#101827"
    ).pack(pady=5)

    status_label = tk.Label(
        popup,
        text="I'm listening!",
        fg="#7dd3fc",
        bg="#101827"
    )
    status_label.pack(pady=10)

    tasks = [
        ("Show Time", "show time"),
        ("Show Date", "show date"),
        ("Open Notepad", "open notepad"),
        ("Open Calculator", "open calculator"),
        ("Open YouTube", "open youtube")
    ]

    for label, command in tasks:
        tk.Button(
            popup,
            text=label,
            command=lambda c=command: execute_command(c),
            font=("Arial", 11),
            bg="#1e293b",
            fg="white",
            width=24,
            relief="flat"
        ).pack(pady=4)

    tk.Button(
        popup,
        text="Close NOVA / Logout",
        command=close_popup,
        bg="#dc2626",
        fg="white",
        width=20,
        relief="flat"
    ).pack(pady=12)


# ================= WAKE WORD =================

def process_command(words):
    global assistant_active, login_screen_open

    words = words.lower().strip()

    wake_detected = (
        "hello nova" in words
        or "hey nova" in words
    )

    if not current_user:
        if wake_detected and not login_screen_open:
            login_screen_open = True
            print("Wake word detected. Opening PIN screen...")
            root.after(0, show_login)

        return

    if wake_detected:
        if not assistant_active:
            assistant_active = True
            root.after(0, show_popup)
        else:
            update_status("I'm already listening.")

        return

    if not assistant_active:
        return

    execute_command(words)


# ================= MICROPHONE =================

def listen_for_commands():
    recognizer = sr.Recognizer()

    try:
        microphone = sr.Microphone()

    except Exception as error:
        print("Microphone error:", error)

        root.after(
            0,
            lambda: messagebox.showerror(
                "NOVA Microphone",
                f"Microphone could not start:\n{error}"
            )
        )

        return

    with microphone as source:
        print("Adjusting microphone...")
        recognizer.adjust_for_ambient_noise(
            source,
            duration=1
        )

    print('NOVA is waiting. Say "Hello Nova" or "Hey Nova".')

    while app_running:

        try:
            with microphone as source:
                audio = recognizer.listen(
                    source,
                    timeout=5,
                    phrase_time_limit=5
                )

            words = recognizer.recognize_google(audio).lower()

            print("You said:", words)
            process_command(words)

        except sr.WaitTimeoutError:
            continue

        except sr.UnknownValueError:
            continue

        except sr.RequestError as error:
            print("Speech recognition needs internet:", error)

        except Exception as error:
            print("Voice error:", error)


# ================= START ASSISTANT =================

def start_assistant():
    global assistant_active

    root.withdraw()
    create_session()

    assistant_active = True
    root.after(0, show_popup)


# ================= APPLICATION CLOSE =================

def on_app_close():
    global app_running, assistant_active, popup_open

    app_running = False
    assistant_active = False
    popup_open = False

    close_session()

    try:
        root.destroy()

    except tk.TclError:
        pass


root.protocol("WM_DELETE_WINDOW", on_app_close)

# Start with idle screen instead of PIN login.
show_idle_screen()

# Start microphone listening in background.
threading.Thread(
    target=listen_for_commands,
    daemon=True
).start()

root.mainloop()
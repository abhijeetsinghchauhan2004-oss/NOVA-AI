
import sqlite3
import hashlib
import secrets
import os
import platform
from pathlib import Path


# ================= DATABASE LOCATION =================

def get_database_path():
    system = platform.system()

    if system == "Windows":
        base = Path(os.getenv("APPDATA", Path.home()))
        app_folder = base / "NOVA AI"

    elif system == "Darwin":
        app_folder = (
            Path.home()
            / "Library"
            / "Application Support"
            / "NOVA AI"
        )

    else:
        app_folder = (
            Path.home()
            / ".local"
            / "share"
            / "NOVA AI"
        )

    app_folder.mkdir(parents=True, exist_ok=True)

    return app_folder / "nova_database.db"


DB_PATH = get_database_path()


# ================= SQLITE CONNECTION =================

class NOVACursor:

    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):
        query = query.replace("%s", "?")

        if params is None:
            self.cursor.execute(query)
        else:
            self.cursor.execute(query, params)

        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def close(self):
        self.cursor.close()


class NOVAConnection:

    def __init__(self, connection):
        self.connection = connection

    def cursor(self, dictionary=False):
        return NOVACursor(
            self.connection.cursor()
        )

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def connect_db():

    try:
        connection = sqlite3.connect(DB_PATH)

        connection.row_factory = sqlite3.Row

        # Compatibility with existing MySQL-style queries
        connection.create_function(
            "NOW",
            0,
            lambda: __import__("datetime").datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        return NOVAConnection(connection)

    except sqlite3.Error as e:
        print("Database connection error:", e)
        return None


# ================= DATABASE TABLES =================

def initialize_database():

    connection = connect_db()

    if connection is None:
        return

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pin_auth (
                pin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                pin_code TEXT NOT NULL,
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                login_time TEXT DEFAULT CURRENT_TIMESTAMP,
                logout_time TEXT,
                session_status TEXT DEFAULT 'Active',
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voice_commands (
                command_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                command_text TEXT NOT NULL,
                command_type TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        connection.commit()

        print("NOVA SQLite database ready!")
        print("Database location:", DB_PATH)

    except sqlite3.Error as e:
        connection.rollback()
        print("Database initialization error:", e)

    finally:
        if cursor:
            cursor.close()

        connection.close()


# ================= PIN SECURITY =================

def hash_pin(pin):

    salt = secrets.token_bytes(16)

    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt,
        600000
    )

    return salt.hex() + ":" + hashed.hex()


def verify_pin(pin, stored_hash):

    try:
        salt_hex, hash_hex = stored_hash.split(":")

        salt = bytes.fromhex(salt_hex)

        new_hash = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            salt,
            600000
        )

        return secrets.compare_digest(
            new_hash.hex(),
            hash_hex
        )

    except (ValueError, TypeError):
        return False


# ================= USER REGISTRATION =================

def register_user(username, email, pin):

    connection = connect_db()

    if connection is None:
        return False, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT user_id FROM users WHERE email = %s",
            (email,)
        )

        if cursor.fetchone():
            return False, "Email already registered."

        cursor.execute(
            """
            INSERT INTO users (username, email)
            VALUES (%s, %s)
            """,
            (username, email)
        )

        user_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO pin_auth (user_id, pin_code)
            VALUES (%s, %s)
            """,
            (user_id, hash_pin(pin))
        )

        connection.commit()

        return True, "Registration successful!"

    except sqlite3.Error as e:
        connection.rollback()
        return False, str(e)

    finally:
        if cursor:
            cursor.close()

        connection.close()


# ================= LOGIN WITH PIN =================

def login_with_pin(pin):

    connection = connect_db()

    if connection is None:
        return None, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                users.user_id,
                users.username,
                pin_auth.pin_code
            FROM users
            JOIN pin_auth
            ON users.user_id = pin_auth.user_id
        """)

        users = cursor.fetchall()

        if not users:
            return None, "No registered user found."

        matched_user = None

        for user in users:

            if verify_pin(pin, user["pin_code"]):

                if matched_user is not None:
                    return None, (
                        "Multiple users have the same PIN. "
                        "Please use a unique PIN."
                    )

                matched_user = user

        if matched_user is None:
            return None, "Incorrect PIN."

        return {
            "user_id": matched_user["user_id"],
            "username": matched_user["username"]
        }, "Login successful!"

    except sqlite3.Error as e:
        return None, str(e)

    finally:
        if cursor:
            cursor.close()

        connection.close()


# ================= EMAIL + PIN LOGIN =================

def login_user(email, pin):

    connection = connect_db()

    if connection is None:
        return None, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                users.user_id,
                users.username,
                pin_auth.pin_code
            FROM users
            JOIN pin_auth
            ON users.user_id = pin_auth.user_id
            WHERE users.email = %s
            """,
            (email,)
        )

        user = cursor.fetchone()

        if not user:
            return None, "Account not found."

        if not verify_pin(pin, user["pin_code"]):
            return None, "Incorrect PIN."

        return {
            "user_id": user["user_id"],
            "username": user["username"]
        }, "Login successful!"

    except sqlite3.Error as e:
        return None, str(e)

    finally:
        if cursor:
            cursor.close()

        connection.close()


# ================= START DATABASE =================

initialize_database()


if __name__ == "__main__":
    print("NOVA authentication module ready!")

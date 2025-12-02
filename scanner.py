import os
import cv2
import psycopg2
import threading
from dotenv import load_dotenv
from tkinter import *
from tkinter import ttk
from PIL import Image, ImageTk

# Load .env for DB creds
load_dotenv()

# DB CONFIG
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "new_year")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "2014230")


# =================== DB FUNCTIONS =====================

def get_db_connection():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )

def verify_ticket(conn, ticket_uid: str):
    """
    Check ticket in DB and update is_scanned if valid.

    Returns: (message: str, is_success: bool)
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT is_scanned FROM tickets WHERE ticket_uid = %s;", (ticket_uid,))
            row = cur.fetchone()

            if not row:
                return "USER DOESN'T EXIST", False

            is_scanned = row[0]

            if is_scanned:
                return "USER ALREADY VERIFIED", False

            # mark as scanned
            cur.execute(
                "UPDATE tickets SET is_scanned = TRUE WHERE ticket_uid = %s;",
                (ticket_uid,),
            )

        conn.commit()
        return "USER VERIFIED - OK", True

    except Exception as e:
        print("DB ERROR:", e)
        return "DB ERROR", False


# =================== TKINTER + CAMERA APP =====================

class QRScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Ticket Scanner")
        self.root.geometry("900x700")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # DB connection
        try:
            self.conn = get_db_connection()
            print("Connected to Postgres.")
        except Exception as e:
            print("Could not connect to DB:", e)
            exit(1)

        # OpenCV
        self.cap = cv2.VideoCapture(0)
        self.detector = cv2.QRCodeDetector()

        # Tracking last scan
        self.last_ticket = None
        self.last_success = False

        # UI Layout
        self.video_label = Label(self.root)
        self.video_label.pack(pady=10)

        self.status_label = Label(self.root, text="SCAN A QR CODE", font=("Arial", 20, "bold"))
        self.status_label.pack(pady=20)

        self.clear_button = ttk.Button(self.root, text="Clear & Scan Next", command=self.clear_scan)
        self.clear_button.pack(pady=10)

        # Start camera loop in Tkinter
        self.update_frame()

    def update_frame(self):
        """Grab video frame, detect QR if visible, update UI."""
        ret, frame = self.cap.read()
        if not ret:
            self.status_label.config(text="CAMERA ERROR", fg="red")
            return

        # Flip for natural orientation
        frame = cv2.flip(frame, 1)

        # detect QR
        data, bbox, _ = self.detector.detectAndDecode(frame)

        if data:
            ticket_uid = data.strip()

            if ticket_uid != self.last_ticket:
                print("Scanned:", ticket_uid)
                msg, success = verify_ticket(self.conn, ticket_uid)
                self.last_ticket = ticket_uid
                self.last_success = success

                # update UI colors
                if success:
                    self.status_label.config(text=msg, fg="green")
                else:
                    self.status_label.config(text=msg, fg="red")

        # Convert frame to Tkinter image
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img).resize((800, 500))
        imgtk = ImageTk.PhotoImage(image=img)

        self.video_label.imgtk = imgtk
        self.video_label.configure(image=imgtk)

        # Continue updating frames
        self.root.after(10, self.update_frame)

    def clear_scan(self):
        self.last_ticket = None
        self.last_success = False
        self.status_label.config(text="SCAN A QR CODE", fg="black")

    def on_close(self):
        print("Closing scanner...")
        self.cap.release()
        self.conn.close()
        self.root.destroy()


# ======================= RUN APP =======================

if __name__ == "__main__":
    root = Tk()
    app = QRScannerApp(root)
    root.mainloop()

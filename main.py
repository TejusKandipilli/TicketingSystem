# main.py
import uuid
import io
import smtplib
from enum import Enum
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
import os
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, constr

import qrcode
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# Load .env
load_dotenv()  # this reads .env and puts values into environment

# ========== CONFIG ==========

# Gmail SMTP config (use app password, not your real Gmail password)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "yourgmail@gmail.com")
SMTP_PASS = os.getenv("SMTP_PASS", "your_app_password")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USER)

PARTY_NAME = "New Year Bash 2026"
PARTY_VENUE = "INS KURSURA SUBMARINE LAWN"
PARTY_DATE = "31 Dec 2025, 7:30 PM - 12:30 AM"

# Optional banner image for email
BANNER_IMAGE_URL = os.getenv(
    "PARTY_BANNER_URL",
    "https://example.com/your-party-banner.jpg"  # replace with real URL
)

# Neon / Postgres connection string from env
# Example .env:
# DATABASE_URL=postgresql://neondb_owner:PASS@ep-...neon.tech/neondb?sslmode=require&target_session_attrs=read-write
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment variables.")

# ========== Postgres Connection Pool (Neon) ==========

try:
    # psycopg2 can take a full DSN URL directly
    pool = SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        dsn=DATABASE_URL,
    )

    # Optional sanity check at startup
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT now();")
            ts = cur.fetchone()
            print(f"Connected to Postgres. Server time: {ts[0]}")
    finally:
        pool.putconn(conn)

except Exception as e:
    # Fail fast if DB is unreachable on startup
    raise RuntimeError(f"Could not connect to Postgres: {e}")


def get_db_conn():
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


# ========== Pydantic Schemas ==========

class TicketType(str, Enum):
    PREMIUM = "premium"
    NON_PREMIUM = "non_premium"
    GUEST = "guest"


class TicketCreate(BaseModel):
    name: constr(strip_whitespace=True, min_length=1)
    mobile: constr(strip_whitespace=True, min_length=8, max_length=15)
    email: EmailStr
    upi_id: constr(strip_whitespace=True, min_length=5)
    ticket_type: TicketType


class TicketResponse(BaseModel):
    ticket_uid: str
    name: str
    mobile: str
    email: EmailStr
    upi_id: str
    ticket_type: TicketType


# ========== QR Code Generation ==========

def generate_qr_png_bytes(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ========== Email Sending (Gmail) ==========

def send_ticket_email(
    recipient_email: str,
    ticket_uid: str,
    ticket: TicketCreate,
    qr_png_bytes: bytes
):
    subject = f"Your Ticket for {PARTY_NAME}"

    body = f"""
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">

    <div style="max-width: 600px; margin: auto; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 0 10px rgba(0,0,0,0.15);">

      <!-- Banner Image -->
      <img src="{BANNER_IMAGE_URL}" alt="Party Banner" style="width:100%; max-height:280px; object-fit:cover;">

      <div style="padding: 25px;">

        <h2 style="color: #333; text-align:center;">Your Ticket is Confirmed 🎉</h2>
        <p style="font-size: 16px; color: #555;">
          Hi <strong>{ticket.name}</strong>,<br><br>
          Your ticket has been successfully booked for 
          <strong>{PARTY_NAME}</strong>!
        </p>

        <h3 style="color: #333; margin-top:30px;">Ticket Details</h3>

        <table style="width:100%; border-collapse: collapse;">
          <tr><td style="padding: 8px; font-weight:bold;">Ticket ID:</td><td>{ticket_uid}</td></tr>
          <tr><td style="padding: 8px; font-weight:bold;">Ticket Type:</td><td>{ticket.ticket_type.value.replace('_', ' ').title()}</td></tr>
          <tr><td style="padding: 8px; font-weight:bold;">Name:</td><td>{ticket.name}</td></tr>
          <tr><td style="padding: 8px; font-weight:bold;">Mobile:</td><td>{ticket.mobile}</td></tr>
          <tr><td style="padding: 8px; font-weight:bold;">UPI ID:</td><td>{ticket.upi_id}</td></tr>
          <tr><td style="padding: 8px; font-weight:bold;">Venue:</td><td>{PARTY_VENUE}</td></tr>
          <tr><td style="padding: 8px; font-weight:bold;">Date & Time:</td><td>{PARTY_DATE}</td></tr>
        </table>

        <p style="font-size: 15px; color: #444; margin-top: 25px;">
          Please show this email and the attached QR code at the entry gate.
          <br>Do <strong>not</strong> share your ticket or QR code with anyone.
        </p>

        <p style="font-size: 16px; margin-top: 25px;">
          See you at the party! 🥳🍾
        </p>

      </div>

    </div>
  </body>
</html>
"""

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email
    msg["Subject"] = subject

    # IMPORTANT: send as HTML, not plain text
    msg.attach(MIMEText(body, "html"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(qr_png_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="ticket_{ticket_uid}.png"',
    )
    msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        server.quit()
    except Exception as e:
        raise RuntimeError(f"Failed to send email: {e}")


# ========== FastAPI App + CORS ==========

app = FastAPI(title="New Year Party Ticketing API (pg + gmail + qr)")

# CORS so frontend can call this API
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # add your deployed frontend origin here when you host it
    # "https://your-frontend-domain.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      # use ["*"] during dev if you want it wide open
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/tickets", response_model=TicketResponse)
def create_ticket(ticket: TicketCreate, conn=Depends(get_db_conn)):
    """
    Insert into existing tickets table, generate QR, send email.
    Block duplicate UPI IDs: if upi_id already exists, reject the request.
    """
    ticket_uid = str(uuid.uuid4())

    # 0) Check if UPI already exists
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM tickets WHERE upi_id = %s LIMIT 1;",
                (ticket.upi_id,),
            )
            existing = cur.fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="This UPI ID is already registered for a ticket.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB lookup failed: {e}")

    # 1) Insert into DB
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tickets (ticket_uid, name, mobile, email, upi_id, ticket_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING ticket_uid, name, mobile, email, upi_id, ticket_type;
                """,
                (
                    ticket_uid,
                    ticket.name,
                    ticket.mobile,
                    ticket.email,
                    ticket.upi_id,
                    ticket.ticket_type.value,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}")

    # 2) Generate QR
    qr_bytes = generate_qr_png_bytes(ticket_uid)

    # 3) Send email
    try:
        send_ticket_email(
            recipient_email=ticket.email,
            ticket_uid=ticket_uid,
            ticket=ticket,
            qr_png_bytes=qr_bytes,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return TicketResponse(
        ticket_uid=row[0],
        name=row[1],
        mobile=row[2],
        email=row[3],
        upi_id=row[4],
        ticket_type=TicketType(row[5]),
    )


@app.get("/tickets/{ticket_uid}", response_model=TicketResponse)
def get_ticket(ticket_uid: str, conn=Depends(get_db_conn)):
    """
    Fetch ticket by ticket_uid for verification at entry.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticket_uid, name, mobile, email, upi_id, ticket_type
                FROM tickets
                WHERE ticket_uid = %s;
                """,
                (ticket_uid,),
            )
            row = cur.fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return TicketResponse(
        ticket_uid=row[0],
        name=row[1],
        mobile=row[2],
        email=row[3],
        upi_id=row[4],
        ticket_type=TicketType(row[5]),
    )

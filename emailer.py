import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import streamlit as st

def gmail_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/gmail.send"]
    )
    return build("gmail", "v1", credentials=creds)

def send_email_with_pdf(pdf_buffer, filename="Weekly_Report.pdf"):
    sender = st.secrets["gmail"]["sender"]
    to = st.secrets["gmail"]["to"]
    subject = st.secrets["gmail"]["subject"]
    body = "Dear researcher,\n\nPlease find attached the weekly Smart Irrigation report.\n\nBest regards,\nSmart Irrigation Dashboard"

    message = MIMEMultipart()
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))

    part = MIMEApplication(pdf_buffer.getvalue(), _subtype="pdf")
    part.add_header("Content-Disposition", "attachment", filename=filename)
    message.attach(part)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = gmail_service()
    sent = service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
    return sent.get("id")

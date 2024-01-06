import os
from twilio.rest import Client

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ['TWILIO_ACCOUNT_SID']
TWILIO_AUTH_TOKEN = os.environ['TWILIO_AUTH_TOKEN']
TWILIO_PHONE_NUMBER = os.environ['TWILIO_PHONE_NUMBER']

# Function to send SMS
def send_sms(to_number, message):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(
        to=to_number,
        from_=TWILIO_PHONE_NUMBER,
        body=message
    )

# Function to make a voice call
def make_call(to_number):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.calls.create(
        to=to_number,
        from_=TWILIO_PHONE_NUMBER,
        url="http://demo.twilio.com/docs/voice.xml"
    )

# Function to handle the entire WUPHF process
def handle_wuphf(user_name, data, wuphf_message):
    # Extract user contact details
    user_contact = data.get("contact_data", {}).get(user_name, {})

    if not user_contact:
        return "Contact details for the user not found."

    # Send SMS
    phone_number = user_contact.get('phone')
    if phone_number:
        send_sms(phone_number, wuphf_message)

    # Make a voice call
    if phone_number:
        make_call(phone_number)

    return f"WUPHF sent to {user_name}!"

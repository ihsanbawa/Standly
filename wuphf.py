import os
from twilio.rest import Client
from database import database
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ['TWILIO_ACCOUNT_SID']
TWILIO_AUTH_TOKEN = os.environ['TWILIO_AUTH_TOKEN']
TWILIO_PHONE_NUMBER = os.environ['TWILIO_PHONE_NUMBER']

# Email credentials (assuming Gmail for this example)
EMAIL_ADDRESS = os.environ['EMAIL_ADDRESS']
EMAIL_PASSWORD = os.environ['EMAIL_PASSWORD']

# Function to send an email
def send_email(to_email, subject, message):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject

        body = MIMEText(message, 'plain')
        msg.attach(body)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, to_email, text)
        server.quit()
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Error sending email: {e}")

# Function to send SMS
def send_sms(to_number, message):
  try:
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    message = client.messages.create(to=to_number,
                                     from_=TWILIO_PHONE_NUMBER,
                                     body=message)
    print(f"SMS sent: {message.sid}")
  except Exception as e:
    print(f"Error sending SMS: {e}")


# Function to make a voice call
def make_call(to_number):
  client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
  client.calls.create(to=to_number,
                      from_=TWILIO_PHONE_NUMBER,
                      url="http://demo.twilio.com/docs/voice.xml")


# Fetch user contact details from the database using Discord ID
async def get_user_contact(guild_id, discord_id):
  print(f"Fetching contact for guild_id: {guild_id}, discord_id: {discord_id}")  # Debug print
  query = """
  SELECT primary_phone, secondary_phone, email
  FROM users
  WHERE guild_id = :guild_id AND discord_id = :discord_id;
  """
  result = await database.fetch_one(query, {'guild_id': guild_id, 'discord_id': discord_id})
  print(f"Query result: {result}")  # Debug print
  return result



  # Adjusted handle_wuphf function to use the database and Discord ID
async def handle_wuphf(guild_id, discord_id, wuphf_message):
  user_contact = await get_user_contact(guild_id, discord_id)
  
  if user_contact is None:
      return "User not found or contact details not set."
  
  primary_phone = user_contact['primary_phone']
  secondary_phone = user_contact['secondary_phone']
  email = user_contact['email']
  
  actions = []
  
  # Sending SMS and making calls to both primary and secondary phones
  for phone_number in [primary_phone, secondary_phone]:
      if phone_number:
          send_sms(phone_number, wuphf_message)
          make_call(phone_number)
          actions.append(f"SMS and call to {phone_number}")
      # Uncomment the following lines if you wish to send an email as well
      # if email:
      #     send_email(email, "WUPHF Message", wuphf_message)
      #     actions.append(f"Email to {email}")
  
  if not actions:
      return "No contact methods available for the specified user."
  
  return "WUPHF request received. Actions taken: " + ", ".join(actions)
  




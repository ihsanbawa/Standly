import os
from twilio.rest import Client

# Twilio credentials
TWILIO_ACCOUNT_SID = os.environ['TWILIO_ACCOUNT_SID']
TWILIO_AUTH_TOKEN = os.environ['TWILIO_AUTH_TOKEN']
TWILIO_PHONE_NUMBER = os.environ['TWILIO_PHONE_NUMBER']


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


# Function to handle the entire WUPHF process
def handle_wuphf(guild_id, user_name, data, wuphf_message):
  guild_data = data.get(str(guild_id), {})
  user_contact = guild_data.get("contact_data", {}).get(user_name, {})

  if not user_contact:
    return "Contact details for the user not found."


  # Make a voice call
  phone_numbers = user_contact.get('phones', [])
  for phone_number in phone_numbers:
    if phone_number:
      send_sms(phone_number, wuphf_message)
      make_call(phone_number)

  return f"WUPHF sent to {user_name}!"

  return f"WUPHF sent to {user_name}!"


def get_all_contacts(data, guild_id):
  guild_data = data.get(str(guild_id), {})
  contact_data = guild_data.get("contact_data", {})
  print(f"Contact data retrieved: {contact_data}")  # Debug: Check the retrieved contact data
  
  if not contact_data:
      return "No contact information available."
  
  contact_list = []
  for username, info in contact_data.items():
      phone_info = ', '.join(info.get('phones', ['N/A']))  # Ensure it's correctly accessing 'phones'
      contact_info = f"Username: {username}, Phone: {phone_info}, Email: {info.get('email', 'N/A')}"
      contact_list.append(contact_info)
  
  return "\n".join(contact_list)



def add_or_update_contact(data, guild_id, username, phones, email):
  print(f"Received phones: {phones}")  # Debug: Check the input format

  # Split phones into a list if there are multiple, or create a single-element list
  phone_list = phones.split(',') if ',' in phones else [phones]
  print(f"Processed phone_list: {phone_list}")  # Debug: Check how the list is formed

  guild_data = data.get(str(guild_id), {})

  # Update or add the new contact data
  contact_data = guild_data.get("contact_data", {})
  contact_data[username] = {"phones": phone_list, "email": email}
  guild_data["contact_data"] = contact_data
  data[str(guild_id)] = guild_data

  print(f"Updated contact data for {username}: {contact_data[username]}")  # Debug: Check the final stored data

  return data



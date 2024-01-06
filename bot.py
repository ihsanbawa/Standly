import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import aiohttp
import time
import json
import threading
from app import app
from wuphf import handle_wuphf, add_or_update_contact, get_all_contacts

# Load environment variables
# load_dotenv()
#TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# SANDBOX_MODE = os.getenv('SANDBOX_MODE') == 'True'

TOKEN = os.environ['DISCORD_BOT_TOKEN']
SANDBOX_MODE = os.environ['SANDBOX_MODE']

# Define the intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Initialize the bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Path to the JSON data file
data_file = 'data.json'


# Function to read data from the JSON file
def read_data():
  try:
    with open(data_file, 'r') as file:
      return json.load(file)
  except (FileNotFoundError, json.JSONDecodeError):
    return {}


# Function to write data to the JSON file
def write_data(data):
  with open(data_file, 'w') as file:
    json.dump(data, file, indent=4)


# Function to log standups internally
async def log_standups_internal(guild_id, channel):
  data = read_data()
  guild_data = data.get(guild_id, {})
  user_data = guild_data.get("user_data", {})

  if not user_data:
    print("No user data available.")
    return

  successful_requests = 0
  errors = []

  async with aiohttp.ClientSession() as session:
    for username, authToken in user_data.items():
      apiUrl = f"https://www.beeminder.com/api/v1/users/{username}/goals/standup/datapoints.json"
      postData = {
          'auth_token': authToken,
          'timestamp': int(time.time()),
          'value': 1,
          'comment': 'logged via discord bot'
      }

      if SANDBOX_MODE:
        # Mock POST for demonstration
        await channel.send(f"Mock POST to {apiUrl} with data: {postData}")

        successful_requests += 1
      else:
        try:
          async with session.post(apiUrl, data=postData) as response:
            if response.status == 200:
              successful_requests += 1
            else:
              error = await response.text()
              errors.append(
                  f"Error for {username}: {response.status} - {error}")
        except Exception as e:
          errors.append(f"Exception for {username}: {str(e)}")

  if successful_requests == len(user_data):
    print("Standup logged successfully for all users.")
  else:
    error_messages = '\n'.join(errors)
    print(f"Errors occurred:\n{error_messages}")


# Event when bot is ready
@bot.event
async def on_ready():
  print(f'{bot.user.name} has connected to Discord!')


# Command to set the monitored channel
@bot.command(name='setchannel',
             help='Set a channel to be monitored by the bot')
async def set_channel(ctx, *, channel_name: str):
  guild_id = str(ctx.guild.id)
  voice_channel = discord.utils.get(ctx.guild.voice_channels,
                                    name=channel_name)

  if voice_channel:
    data = read_data()
    if guild_id not in data:
      data[guild_id] = {}
    data[guild_id]["monitored_channel_id"] = voice_channel.id
    data[guild_id]["monitored_channel_name"] = channel_name
    write_data(data)

    await ctx.send(f"Voice channel '{channel_name}' is now being monitored.")
  else:
    await ctx.send(f"No voice channel named '{channel_name}' found.")


# Command to list all voice channels in the server
@bot.command(name='listchannels', help='List all voice channels in the server')
async def list_channels(ctx):
  channels = ctx.guild.voice_channels
  channel_list = '\n'.join([f"- {channel.name}" for channel in channels])
  await ctx.send(f"Voice Channels:\n{channel_list}")


# Command to add a user with their authToken
@bot.command(
    name='adduser',
    help=
    'Add a user with their authToken. Usage: !adduser [username] [authToken]')
async def add_user(ctx, username: str, authToken: str):
  if username is None or authToken is None:
    await ctx.send("Please provide both a username and an authToken.")
    return

  guild_id = str(ctx.guild.id)
  data = read_data()
  if guild_id not in data:
    data[guild_id] = {"user_data": {}}
  data[guild_id]["user_data"][username] = authToken
  write_data(data)

  await ctx.send(f"User {username} added/updated successfully.")


# Command to delete a user
@bot.command(name='deleteuser',
             help='Delete a user from the bot. Usage: !deleteuser [username]')
async def delete_user(ctx, username: str):
  guild_id = str(ctx.guild.id)
  data = read_data()
  if guild_id in data and username in data[guild_id].get("user_data", {}):
    del data[guild_id]["user_data"][username]
    write_data(data)
    await ctx.send(f"User {username} has been removed.")
  else:
    await ctx.send(f"User {username} not found in stored data.")


# Command to list all users stored in the bot
@bot.command(name='listusers', help='List all users stored in the bot')
async def list_users(ctx):
  guild_id = str(ctx.guild.id)
  data = read_data()
  user_data = data.get(guild_id, {}).get("user_data", {})

  if not user_data:
    await ctx.send("No users are currently stored.")
    return

  users_list = '\n'.join([f"- {username}" for username in user_data])
  await ctx.send(f"Stored users:\n{users_list}")


# Command to toggle sandbox mode
@bot.command(name='sandbox', help='Toggle the sandbox mode')
async def toggle_sandbox_mode(ctx):
  global SANDBOX_MODE
  SANDBOX_MODE = not SANDBOX_MODE
  await ctx.send(f"Sandbox mode is now {'True' if SANDBOX_MODE else 'False'}.")


# Command to display Beeminder graphs for all users
@bot.command(name='graphs', help='Display Beeminder graphs for all users')
async def graphs(ctx):
  timestamp = int(time.time())
  guild_id = str(ctx.guild.id)
  data = read_data()
  user_data = data.get(guild_id, {}).get("user_data", {})

  if not user_data:
    await ctx.send("No user data available.")
    return

  for username in user_data:
    graph_url = f"https://www.beeminder.com/{username}/standup.png?{timestamp}"
    await ctx.send(f"Graph for {username}: {graph_url}")


# Command to log standups to Beeminder for all users
@bot.command(name='logstandups',
             help='Log standups to Beeminder for all users')
async def log_standups(ctx):
  guild_id = str(ctx.guild.id)
  # Retrieve the monitored text channel from the guild data
  data = read_data()
  guild_data = data.get(guild_id, {})
  channel_name = guild_data.get("monitored_channel_name")
  channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
  # If the channel is found, pass it to the log_standups_internal function
  if channel:
    await log_standups_internal(guild_id, channel)
    await ctx.send("Manually logged all standups for all users.")
  else:
    await ctx.send("Monitored text channel not found.")


@bot.event
async def on_voice_state_update(member, before, after):
  print(f"Voice state update detected for member: {member.name}")

  # Check if the user has joined a new channel or left a channel
  if before.channel != after.channel:
    print(f"Member {member.name} changed channels.")

    # Check if the user has joined a channel (and not just left one)
    if after.channel:
      print(f"Member {member.name} joined channel: {after.channel.name}")

      guild_id = str(after.channel.guild.id)
      data = read_data()
      guild_data = data.get(guild_id, {})

      # Attempt to find the monitored text channel
      text_channel = discord.utils.get(
          after.channel.guild.text_channels,
          name=guild_data.get("monitored_channel_name"))

      if text_channel:
        print(f"Found monitored text channel: {text_channel.name}")
      else:
        print("Monitored text channel not found.")

      # Check if the newly joined channel is the monitored channel
      if guild_data.get("monitored_channel_id") == after.channel.id:
        print(f"Member {member.name} joined the monitored channel.")

        today = time.strftime("%Y-%m-%d")
        if len(after.channel.members) == len(guild_data.get(
            "user_data", {})) and guild_data.get("last_log_date") != today:
          print("Logging standup...")
          await log_standups_internal(guild_id, text_channel)
          guild_data["last_log_date"] = today
          write_data(data)

          if text_channel:
            await text_channel.send(
                f"Standup logged for users: {', '.join(guild_data['user_data'].keys())} on {today}"
            )
            print("Standup log message sent.")
        else:
          print("Conditions for logging standup not met.")
    else:
      print(f"Member {member.name} left channel: {before.channel.name}")
  else:
    print(
        f"Member {member.name} had a voice state change in the same channel.")


@bot.command(name='wuphf', help='Send a WUPHF to a user')
async def wuphf(ctx, username: str):
  # Read data from JSON
  data = read_data()

  # Define your message
  wuphf_message = "This is a WUPHF from Discord!"

  # Handle the WUPHF
  response = handle_wuphf(ctx.guild.id, username, data, wuphf_message)

  await ctx.send(response)


@bot.command(name='addcontact', help='Add or update contact information for a user')
async def add_contact(ctx, username: str, phones: str, email: str):
    data = read_data()
    updated_data = add_or_update_contact(data, ctx.guild.id, username, phones, email)
    write_data(updated_data)
    await ctx.send(f"Contact information updated for {username}")


@bot.command(name='listcontacts', help='List all stored contact information')
async def list_contacts(ctx):
  data = read_data()
  contacts = get_all_contacts(data, ctx.guild.id)
  await ctx.send(contacts)


def run():
  app.run(host='0.0.0.0', port=8080)


if __name__ == "__main__":
  # Start the Flask app in a separate thread
  t = threading.Thread(target=run)
  t.start()

  # Start the Discord bot
  bot.run(TOKEN)

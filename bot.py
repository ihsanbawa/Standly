import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import aiohttp
import time
import json
import threading
from app import app

# Load environment variables
# load_dotenv()
#TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# SANDBOX_MODE = os.getenv('SANDBOX_MODE') == 'True'

TOKEN = os.environ['DISCORD_BOT_TOKEN']
SANDBOX_MODE = os.environ['SANDBOX_MODE'] == 'True'

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
async def log_standups_internal(guild_id):
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
        print(f"Mock POST to {apiUrl} with data: {postData}")
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
  await log_standups_internal(guild_id)
  await ctx.send("Attempted to log standups for all users.")


# Event triggered when a user's voice state updates
@bot.event
async def on_voice_state_update(member, before, after):
  if after.channel:
    guild_id = str(after.channel.guild.id)
    data = read_data()
    guild_data = data.get(guild_id, {})

    # Define text_channel here
    text_channel = discord.utils.get(
        after.channel.guild.text_channels,
        name=guild_data.get("monitored_channel_name"))

    if guild_data.get("monitored_channel_id") == after.channel.id:
      today = time.strftime("%Y-%m-%d")
      if len(after.channel.members) == len(guild_data.get(
          "user_data", {})) and guild_data.get("last_log_date") != today:
        await log_standups_internal(guild_id)
        guild_data["last_log_date"] = today
        write_data(data)

        if text_channel:
          await text_channel.send(
              f"Standup logged for users: {', '.join(guild_data['user_data'].keys())} on {today}"
          )


def run():
  app.run(host='0.0.0.0', port=8080)


if __name__ == "__main__":
  # Start the Flask app in a separate thread
  t = threading.Thread(target=run)
  t.start()

  # Start the Discord bot
  bot.run(TOKEN)

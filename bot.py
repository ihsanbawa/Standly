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
from replit import db
from database import database
from datetime import datetime
import pytz

# Load environment variables
# load_dotenv()
#TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# SANDBOX_MODE = os.getenv('SANDBOX_MODE') == 'True'

TOKEN = os.environ['DISCORD_BOT_TOKEN']
SANDBOX_MODE = False  # Change to True when you want to enable sandbox mode

# Define the intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Initialize the bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Path to the JSON data file
data_file = 'data.json'

async def execute_query(query, values={}):
  try:
      return await database.execute(query, values)
  except Exception as e:
      print(f"Database query error: {e}")
      return None

# Helper function to fetch data from the database
async def fetch_query(query, values={}):
  try:
      return await database.fetch_all(query, values)
  except Exception as e:
      print(f"Database query error: {e}")
      return []




# Function to log standups internally
async def log_standups_internal(guild_id, channel):
    # Fetch users with their Beeminder auth tokens for the guild
    query = """
    SELECT beeminder_username, beeminder_auth_token
    FROM users
    WHERE guild_id = :guild_id;
    """
    users = await fetch_query(query, {'guild_id': guild_id})

    if not users:
        print("No user data available for this guild.")
        return

    successful_requests = 0
    errors = []

    async with aiohttp.ClientSession() as session:
        for user in users:
            beeminder_username = user['beeminder_username']
            auth_token = user['beeminder_auth_token']
            apiUrl = f"https://www.beeminder.com/api/v1/users/{beeminder_username}/goals/standup/datapoints.json"
            postData = {
                'auth_token': auth_token,
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
                            errors.append(f"Error for {beeminder_username}: {response.status} - {error}")
                except Exception as e:
                    errors.append(f"Exception for {beeminder_username}: {str(e)}")

    if successful_requests == len(users):
        print("Standup logged successfully for all users.")
    else:
        error_messages = '\n'.join(errors)
        print(f"Errors occurred:\n{error_messages}")

# Event when bot is ready
@bot.event
async def on_ready():
  print(f'{bot.user.name} has connected to Discord!')
  try:
    print("Attempting to connect to the database...")
    await database.connect()
    print("Successfully connected to the database.")
  except Exception as e:
    print(f"Failed to connect to the database: {e}")

  print(f'{bot.user.name} has connected to Discord!')




@bot.event
async def on_disconnect():
  print("Bot is disconnecting...")
  await database.disconnect()
  print("Disconnected from the database.")



# Command to toggle sandbox mode
@bot.command(name='sandbox', help='Toggle the sandbox mode')
async def toggle_sandbox_mode(ctx):
  global SANDBOX_MODE
  SANDBOX_MODE = not SANDBOX_MODE
  await ctx.send(f"Sandbox mode is now {'True' if SANDBOX_MODE else 'False'}.")


@bot.command(name='graphs', help='Display Beeminder graphs for all users')
async def graphs(ctx):
    timestamp = int(time.time())
    guild_id = ctx.guild.id

    # Fetch Beeminder usernames for users in the guild
    query = """
    SELECT beeminder_username
    FROM users
    WHERE guild_id = :guild_id;
    """
    users = await fetch_query(query, {'guild_id': guild_id})

    if not users:
        await ctx.send("No user data available.")
        return

    for user in users:
        beeminder_username = user['beeminder_username']
        graph_url = f"https://www.beeminder.com/{beeminder_username}/standup.png?{timestamp}"
        await ctx.send(f"Graph for {beeminder_username}: {graph_url}")



@bot.command(name='logstandups', help='Log standups to Beeminder for all users')
async def log_standups(ctx):
    guild_id = ctx.guild.id

    # Use fetch_query with the guild information query
    guild_query = """
    SELECT monitored_channel_name, monitored_channel_id, last_log_date
    FROM guilds WHERE guild_id = :guild_id;
    """
    guild_info_result = await fetch_query(guild_query, {"guild_id": guild_id})

    # Check if guild information is available
    if not guild_info_result or len(guild_info_result) == 0:
        await ctx.send("Monitored channel not set for this guild.")
        return

    # Extract guild information
    guild_info = guild_info_result[0]
    channel_name = guild_info['monitored_channel_name']

    # Find the channel by name
    channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
    if not channel:
        await ctx.send(f"Monitored text channel '{channel_name}' not found.")
        return

    # Call log_standups_internal function with the found channel
    await log_standups_internal(guild_id, channel)
    await ctx.send("Standups logged for all users.")






@bot.event
async def on_voice_state_update(member, before, after):
    print(f"Voice state update detected for member: {member.name}")

    if before.channel != after.channel:
        print(f"Member {member.name} changed channels.")

        if after.channel:
            print(f"Member {member.name} joined channel: {after.channel.name}")

            guild_id = after.channel.guild.id

            # Fetch guild information
            guild_query = """
            SELECT monitored_channel_name, last_log_date
            FROM guilds
            WHERE guild_id = :guild_id;
            """
            guild_info_result = await fetch_query(guild_query, {"guild_id": guild_id})

            if guild_info_result and len(guild_info_result) > 0:
                guild_info = guild_info_result[0]
                monitored_channel_name = guild_info['monitored_channel_name']

                if monitored_channel_name and after.channel.name == monitored_channel_name:
                    print(f"Member {member.name} joined the monitored channel: {monitored_channel_name}")
                    central_tz = pytz.timezone('America/Chicago')  # Central Time Zone
                    central_time = datetime.now(central_tz)
                    today = central_time.strftime('%Y-%m-%d')
                    today_date = datetime.strptime(today, '%Y-%m-%d')
                    last_log_date = guild_info['last_log_date']
                    user_count_query = "SELECT COUNT(*) FROM users WHERE guild_id = :guild_id;"
                    user_count_result = await fetch_query(user_count_query, {"guild_id": guild_id})
                    user_count = user_count_result[0][0] if user_count_result else 0

                    if len(after.channel.members) == user_count and (not last_log_date or last_log_date != today):
                        print("Logging standup...")
                        text_channel = discord.utils.get(after.channel.guild.text_channels, name=monitored_channel_name)
                        if text_channel:
                            await log_standups_internal(guild_id, text_channel)
                            # Update the last log date in the database
                            update_query = """
                            UPDATE guilds SET last_log_date = :today WHERE guild_id = :guild_id;
                            """
                            await execute_query(update_query, {'today': today_date, 'guild_id': guild_id})
                            await text_channel.send(f"Standup logged for users in the channel on {today}")
                            print("Standup log message sent.")
                        else:
                            print(f"Monitored text channel '{monitored_channel_name}' not found.")
                    else:
                        print("Conditions for logging standup not met.")
            else:
                print("Guild information not found or the user did not join the monitored channel.")
        else:
            print(f"Member {member.name} left channel: {before.channel.name}")
    else:
        print(f"Member {member.name} had a voice state change in the same channel.")





# @bot.command(name='wuphf', help='Send a WUPHF to a user')
# async def wuphf(ctx, username: str):
#   # Read data from JSON
#   data = read_data()

#   # Define your message
#   wuphf_message = "This is a WUPHF from Discord!"

#   # Handle the WUPHF
#   response = handle_wuphf(ctx.guild.id, username, data, wuphf_message)

#   await ctx.send(response)







@bot.command(name='info', help='Display bot configuration and guild-specific information')
async def info(ctx):
    guild_id = ctx.guild.id

    # Query to get guild information
    guild_query = """
    SELECT monitored_channel_name, monitored_channel_id, last_log_date
    FROM guilds WHERE guild_id = :guild_id;
    """
    guild_info = await fetch_query(guild_query, {"guild_id": guild_id})

    # Fetch the number of users
    user_count_query = "SELECT COUNT(*) FROM users WHERE guild_id = :guild_id;"
    user_count_result = await fetch_query(user_count_query, {"guild_id": guild_id})
    user_count = user_count_result[0][0] if user_count_result else 0

    sandbox_status = 'Enabled' if SANDBOX_MODE else 'Disabled'
    monitored_channel = guild_info[0]['monitored_channel_name'] if guild_info else "Not set"
    monitored_channel_id = guild_info[0]['monitored_channel_id'] if guild_info else "Not set"
    last_log_date = guild_info[0]['last_log_date'] if guild_info else "Not available"

    info_message = (
        f"**Bot Configuration Information**\n"
        f"- Sandbox Mode: {sandbox_status}\n"
        f"- Number of Users: {user_count}\n"
        f"- Monitored Channel: {monitored_channel} (ID: {monitored_channel_id})\n"
        f"- Last Log Date: {last_log_date}\n"
    )
    await ctx.send(info_message)



# Command to get a user's Discord ID
@bot.command(name='getid')
async def get_id(ctx, member: discord.Member):
  # Send a message with the member's Discord ID
  await ctx.send(f"The Discord ID of {member.mention} is `{member.id}`")


def run():
  app.run(host='0.0.0.0', port=8080)


if __name__ == "__main__":
  # Start the Flask app in a separate thread
  t = threading.Thread(target=run)
  t.start()

  # Start the Discord bot
  bot.run(TOKEN)

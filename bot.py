from functools import partial
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import aiohttp
import time
import json
import threading
from app import app
from wuphf import handle_wuphf
from replit import db
from database import database
from datetime import datetime, timedelta
import pytz
import asyncio
from goals import view_goals, add_goal
from discord import Thread
from daily_updates import fetch_user_info, fetch_todoist_token, fetch_tasks_from_todoist, fetch_completed_tasks_from_todoist, get_or_create_thread
import uuid







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


async def execute_query(query, values={}):
  try:
    return await database.execute(query, values)
  except Exception as e:
    print(f"Database query error: {e}")
    return None

async def db_heartbeat():
  while True:
    await asyncio.sleep(300)
    if not database.is_connected:
      try:
        await database.connect()
        print("Database connection re-established.")
      except Exception as e:
        print(f"Error reconnecting to the database: {e}")
    else:
      try:
        await database.execute("SELECT 1"
                               )  # Simple query to keep the connection alive
        print("Heartbeat query executed to keep DB connection alive.")
      except Exception as e:
        print(f"Error during heartbeat query: {e}")

def generate_random_uuid():
  return str(uuid.uuid4())

# Helper function to fetch data from the database
async def fetch_query(query, values={}):
  try:
    return await database.fetch_all(query, values)
  except Exception as e:
    print(f"Database query error: {e}")
    return []


async def fetch_user_info(user_id, database):
  # Assuming 'database' is an async database connection object
  query = """
      SELECT guild_id, discord_username
      FROM users
      WHERE discord_id = :user_id
  """
  result = await database.fetch_one(query, {'user_id': user_id})
  print(f"fetch_user_info result: {result}")
  
  if result:
      return {
          'guild_id': result['guild_id'],
          'discord_username': result['discord_username']
      }
  return None


async def fetch_user_habits(discord_id):
  query = """
      SELECT id, title
      FROM habits
      WHERE user_id = :discord_id
  """
  return await fetch_query(query, {'discord_id': discord_id})


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
              errors.append(
                  f"Error for {beeminder_username}: {response.status} - {error}"
              )
        except Exception as e:
          errors.append(f"Exception for {beeminder_username}: {str(e)}")

  if successful_requests == len(users):
    print("Standup logged successfully for all users.")
  else:
    error_messages = '\n'.join(errors)
    print(f"Errors occurred:\n{error_messages}")


async def determine_streak_update(last_entry_date, entry_date):
  central_tz = pytz.timezone('America/Chicago')
  last_entry_date = last_entry_date.astimezone(central_tz) if last_entry_date else None
  entry_date = entry_date.astimezone(central_tz)

  if last_entry_date is None or last_entry_date.date() != entry_date.date() - timedelta(days=1):
      return 1
  else:
      return 1

async def record_habit_entry(user_id, habit_id, quantity=None):
  print(f"Starting to record habit entry for user {user_id} and habit {habit_id}")

  central_tz = pytz.timezone('America/Chicago')
  entry_date = datetime.now(central_tz)
  print(f"Entry date (Central Time): {entry_date}")

  # Start a transaction
  async with database.transaction():
      # Step 1: Check the last completion date for this habit
      last_entry_query = """
          SELECT entry_date FROM habit_entries
          WHERE user_id = :user_id AND habit_id = :habit_id
          ORDER BY entry_date DESC LIMIT 1
      """
      print("Last Entry Query:", last_entry_query)

      last_entry = await database.fetch_one(last_entry_query, {'user_id': user_id, 'habit_id': habit_id})

      last_entry_date = last_entry['entry_date'] if last_entry else None

      # Determine the streak update
      streak_update = await determine_streak_update(last_entry_date, entry_date)

      # Step 2: Update habits table
      streak_update_query = """
          UPDATE habits SET 
              streak = streak + :streak_update,
              overall_counter = overall_counter + 1
          WHERE id = :habit_id
      """
      await database.execute(streak_update_query, {
          'streak_update': streak_update,
          'habit_id': habit_id
      })
      print("Habit streak and overall counter updated.")

      # Generate a new UUID for the habit entry
      new_entry_id = generate_random_uuid()
      print(f"Generated new entry ID: {new_entry_id}")

      # Insert the new habit entry with the generated UUID
      insert_entry_query = """
          INSERT INTO habit_entries (id, habit_id, entry_date, quantity, user_id)
          VALUES (:new_entry_id, :habit_id, :entry_date, :quantity, :user_id)
      """

      quantity_value = int(quantity) if quantity is not None else 1
      print("db params", new_entry_id, habit_id, entry_date, quantity_value, user_id)

      await database.execute(insert_entry_query, {
          'new_entry_id': new_entry_id,
          'habit_id': habit_id,
          'entry_date': entry_date,
          'quantity': quantity_value,
          'user_id': user_id
      })
      print("New habit entry recorded.")



def make_button_callback(user_id, habit_id, habit_title):
  async def button_callback(interaction):
      try:
          # Call the function to record the habit entry in the database
          await record_habit_entry(user_id, habit_id)
          # Send a confirmation message to the user
          await interaction.response.send_message(f"'{habit_title}' habit recorded successfully!", ephemeral=True)
      except Exception as e:
          # Handle any errors that occur during the database operation
          print(f"Error recording habit entry: {e}")
          await interaction.response.send_message("There was an error recording your habit. Please try again.", ephemeral=True)
  return button_callback


# Event when bot is ready
@bot.event
async def on_ready():
  print(f'{bot.user.name} has connected to Discord!')
  try:
    print("Attempting to connect to the database...")
    await database.connect()
    print("Successfully connected to the database.")
    # Start the heartbeat task
    bot.loop.create_task(db_heartbeat())
  except Exception as e:
    print(f"Failed to connect to the database: {e}")


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


@bot.command(name='logstandups',
             help='Log standups to Beeminder for all users')
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


@bot.command(name='viewgoals', help='View your goals')
async def view_goals_command(ctx):
    await view_goals(ctx)

from goals import add_goal  # Make sure to import the add_goal function

@bot.command(name='addgoal', help='Add a new goal')
async def add_goal_command(ctx):
    await add_goal(ctx)  # Call the add_goal function from goals.py


@bot.command(name='removestandups', help='Remove the most recent standup data point for all users')
async def remove_standups(ctx):
    guild_id = ctx.guild.id

    # Fetch users and their Beeminder auth tokens for the guild
    query = """
        SELECT beeminder_username, beeminder_auth_token
        FROM users
        WHERE guild_id = :guild_id;
        """
    users = await fetch_query(query, {'guild_id': guild_id})

    if not users:
        await ctx.send("No user data available for this guild.")
        return

    successful_deletions = 0
    errors = []

    async with aiohttp.ClientSession() as session:
        for user in users:
            beeminder_username = user['beeminder_username']
            auth_token = user['beeminder_auth_token']

            # Fetch the most recent data point for the user
            # This is a placeholder, you'll need to adjust based on how you can identify the data point to delete
            data_point_id = await fetch_most_recent_data_point_id(beeminder_username, auth_token)

            if not data_point_id:
                errors.append(f"No data point found for {beeminder_username}")
                continue

            delete_url = f"https://www.beeminder.com/api/v1/users/{beeminder_username}/goals/standup/datapoints/{data_point_id}.json?auth_token={auth_token}"

            try:
                async with session.delete(delete_url) as response:
                    if response.status == 200:
                        successful_deletions += 1
                    else:
                        error = await response.text()
                        errors.append(f"Error for {beeminder_username}: {response.status} - {error}")
            except Exception as e:
                errors.append(f"Exception for {beeminder_username}: {str(e)}")

    if successful_deletions == len(users):
        await ctx.send("Most recent standup data point removed successfully for all users.")
    else:
        error_messages = '\n'.join(errors)
        await ctx.send(f"Errors occurred during deletion:\n{error_messages}")

async def fetch_most_recent_data_point_id(beeminder_username, auth_token):
  # Beeminder API URL to fetch all data points for a user's goal
  url = f"https://www.beeminder.com/api/v1/users/{beeminder_username}/goals/standup/datapoints.json?auth_token={auth_token}"

  async with aiohttp.ClientSession() as session:
      try:
          async with session.get(url) as response:
              if response.status == 200:
                  data_points = await response.json()

                  if not data_points:
                      print(f"No data points found for {beeminder_username}")
                      return None

                  # Sort the data points by the 'updated_at' or 'timestamp' field to find the most recent one
                  # Assuming that the data points are returned as a list of dictionaries
                  most_recent_data_point = max(data_points, key=lambda x: x['timestamp'])

                  # Return the ID of the most recent data point
                  return most_recent_data_point['id']
              else:
                  error = await response.text()
                  print(f"Error fetching data points for {beeminder_username}: {response.status} - {error}")
                  return None
      except Exception as e:
          print(f"Exception occurred while fetching data points for {beeminder_username}: {str(e)}")
          return None




@bot.command(name='addhabit', help='Add a new habit')
async def add_habit(ctx, *, habit_title):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a Direct Message with me.")
        return

    user_id = str(ctx.author.id)  # Use Discord ID as the user_id in the database

    # Insert the new habit into the database
    insert_habit_query = """
        INSERT INTO habits (id, title, user_id, streak, overall_counter)
        VALUES (:habit_id, :habit_title, :user_id, 0, 0)
    """

    # Generate a new UUID for the habit
    habit_id = generate_random_uuid()

    try:
        await database.execute(insert_habit_query, {
            'habit_id': habit_id,
            'habit_title': habit_title,
            'user_id': user_id
        })
        await ctx.send(f"New habit '{habit_title}' added successfully!")
    except Exception as e:
        print(f"Error adding new habit: {e}")
        await ctx.send("Failed to add the new habit. Please try again later.")

@bot.command(name='deletehabit', help='Delete a habit')
async def delete_habit(ctx, *, habit_title):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a Direct Message with me.")
        return

    user_id = str(ctx.author.id)  # Use Discord ID as the user_id in the database

    # Fetch the habit ID using the habit title and user ID
    habit_query = """
        SELECT id
        FROM habits
        WHERE user_id = :user_id AND title = :habit_title
    """
    habit_result = await database.fetch_one(habit_query, {'user_id': user_id, 'habit_title': habit_title})

    if not habit_result:
        await ctx.send(f"You don't have a habit with the title '{habit_title}'.")
        return

    habit_id = habit_result['id']

    # Delete all entries associated with the habit
    delete_entries_query = """
        DELETE FROM habit_entries
        WHERE habit_id = :habit_id
    """
    try:
        await database.execute(delete_entries_query, {'habit_id': habit_id})
    except Exception as e:
        print(f"Error deleting entries associated with habit: {e}")
        await ctx.send("Failed to delete entries associated with the habit. Please try again later.")
        return

    # Delete the habit from the database
    delete_habit_query = """
        DELETE FROM habits
        WHERE id = :habit_id
    """

    try:
        await database.execute(delete_habit_query, {'habit_id': habit_id})
        await ctx.send(f"Habit '{habit_title}' deleted successfully!")
    except Exception as e:
        print(f"Error deleting habit: {e}")
        await ctx.send("Failed to delete the habit. Please try again later.")



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
      guild_info_result = await fetch_query(guild_query,
                                            {"guild_id": guild_id})

      if guild_info_result and len(guild_info_result) > 0:
        guild_info = guild_info_result[0]
        monitored_channel_name = guild_info['monitored_channel_name']

        if monitored_channel_name and after.channel.name == monitored_channel_name:
          print(
              f"Member {member.name} joined the monitored channel: {monitored_channel_name}"
          )
          central_tz = pytz.timezone('America/Chicago')  # Central Time Zone
          central_time = datetime.now(central_tz)
          today = central_time.strftime('%Y-%m-%d')
          today_date = datetime.strptime(today, '%Y-%m-%d').date()
          last_log_date = guild_info['last_log_date']
          user_count_query = "SELECT COUNT(*) FROM users WHERE guild_id = :guild_id;"
          user_count_result = await fetch_query(user_count_query,
                                                {"guild_id": guild_id})
          user_count = user_count_result[0][0] if user_count_result else 0
          print("dates", today_date, last_log_date)
          if len(after.channel.members) == user_count and (today_date != last_log_date):
            print("Logging standup...")
            text_channel = discord.utils.get(after.channel.guild.text_channels,
                                             name=monitored_channel_name)
            if text_channel:
              await log_standups_internal(guild_id, text_channel)
              # Update the last log date in the database
              update_query = """
                            UPDATE guilds SET last_log_date = :today WHERE guild_id = :guild_id;
                            """
              await execute_query(update_query, {
                  'today': today_date,
                  'guild_id': guild_id
              })
              await text_channel.send(
                  f"Standup logged for users in the channel on {today}")
              print("Standup log message sent.")
            else:
              print(
                  f"Monitored text channel '{monitored_channel_name}' not found."
              )
          else:
            print("Conditions for logging standup not met.")
      else:
        print(
            "Guild information not found or the user did not join the monitored channel."
        )
    else:
      print(f"Member {member.name} left channel: {before.channel.name}")
  else:
    print(
        f"Member {member.name} had a voice state change in the same channel.")


@bot.command(name='wuphf', help='Send a WUPHF to a user')
async def wuphf(ctx, member: discord.Member):
  # Construct your message
  await ctx.send("Wuphf being processed for " + member.mention)
  wuphf_message = "WUPHF! It's time for standup!"

  # Call the handle_wuphf function with the member's ID
  response = await handle_wuphf(ctx.guild.id, member.id, wuphf_message)
  await ctx.send(response)


@bot.command(name='info',
             help='Display bot configuration and guild-specific information')
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
  user_count_result = await fetch_query(user_count_query,
                                        {"guild_id": guild_id})
  user_count = user_count_result[0][0] if user_count_result else 0

  sandbox_status = 'Enabled' if SANDBOX_MODE else 'Disabled'
  monitored_channel = guild_info[0][
      'monitored_channel_name'] if guild_info else "Not set"
  monitored_channel_id = guild_info[0][
      'monitored_channel_id'] if guild_info else "Not set"
  last_log_date = guild_info[0][
      'last_log_date'] if guild_info else "Not available"

  info_message = (
      f"**Bot Configuration Information**\n"
      f"- Sandbox Mode: {sandbox_status}\n"
      f"- Number of Users: {user_count}\n"
      f"- Monitored Channel: {monitored_channel} (ID: {monitored_channel_id})\n"
      f"- Last Log Date: {last_log_date}\n")
  await ctx.send(info_message)

@bot.command(name='dailyupdate', help='Send your daily update')
async def daily_update(ctx):
    # Ensure this command is used in a DM, not in a public guild channel
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("This command can only be used in DMs.")
        return

    # Fetch user info from the database
    user_info = await fetch_user_info(ctx.author.id, database)
    if not user_info:
        await ctx.send("Could not find your user information in the database.")
        return

    guild_id = user_info['guild_id']
    guild = bot.get_guild(guild_id)
    if not guild:
        await ctx.send("Could not find the guild associated with your user information.")
        return

    # Fetch the monitored channel name for this guild
    guild_info_result = await fetch_query("""
        SELECT monitored_channel_name
        FROM guilds
        WHERE guild_id = :guild_id;
    """, {"guild_id": guild_id})

    if not guild_info_result or len(guild_info_result) == 0:
        await ctx.send("Monitored channel not set for the associated guild.")
        return

    monitored_channel_name = guild_info_result[0]['monitored_channel_name']
    channel = discord.utils.get(guild.text_channels, name=monitored_channel_name)
    if not channel:
        await ctx.send(f"Monitored text channel '{monitored_channel_name}' not found in the associated guild.")
        return

    # Prepare the message content for the thread
    user_message = ctx.message.content[len(ctx.invoked_with) + 1:].strip()

    # Find or create a thread named after the user's username in the monitored channel
    thread = await get_or_create_thread(channel, ctx.author.display_name)

    # Post the initial update in the thread
    await thread.send(f"{ctx.author.mention}'s daily update:\n{user_message}")

    # Fetch and display yesterday's completed tasks
    todoist_token = await fetch_todoist_token(ctx.author.id, database)
    if todoist_token:
        completed_tasks = await fetch_completed_tasks_from_todoist(todoist_token)
        if completed_tasks:
            completed_message = "Your completed tasks from yesterday:\n" + "\n".join([f"- {task['content']}" for task in completed_tasks])
            await thread.send(completed_message)
        else:
            await thread.send("You had no completed tasks yesterday.")

        # Fetch and display today's tasks
        today_tasks = await fetch_tasks_from_todoist(todoist_token, "today")
        if today_tasks:
            today_message = "Your tasks for today:\n" + "\n".join([f"- {task[0]}" for task in today_tasks])
            await thread.send(today_message)
        else:
            await thread.send("You have no tasks for today.")
    else:
        await thread.send("Todoist API token not found. Please set it up.")

@bot.command(name='recordhabit', help='Record a habit from a list')
async def record_habit(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a Direct Message with me.")
        return

    user_id = str(ctx.author.id)  # Use Discord ID as the user_id in the database

    user_habits = await fetch_user_habits(user_id)

    if not user_habits:
        await ctx.send("You don't have any habits set up yet.")
        return

    view = View()

    for habit in user_habits:
        habit_id, habit_title = habit['id'], habit['title']
        button = Button(label=habit_title, style=discord.ButtonStyle.primary)

        async def button_callback(interaction, habit_id=habit_id, habit_title=habit_title, user_id=user_id):
            try:
                await record_habit_entry(user_id, habit_id)
                await interaction.response.send_message(f"'{habit_title}' habit recorded successfully!", ephemeral=True)
            except Exception as e:
                print(f"Error recording habit entry: {e}")
                await interaction.response.send_message("There was an error recording your habit. Please try again.", ephemeral=True)

        # Directly assign the callback function to the button
        button.callback = button_callback

        view.add_item(button)

    await ctx.send("Click the button corresponding to the habit you want to record for today:", view=view)

  

def run():
  app.run(host='0.0.0.0', port=8080)


if __name__ == "__main__":
  # Start the Flask app in a separate thread
  t = threading.Thread(target=run)
  t.start()

  # Start the Discord bot
  bot.run(TOKEN)

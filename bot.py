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
from database import database, fetch_query, execute_query
from datetime import datetime, timedelta, date
import pytz
import asyncio
from goals import view_goals, add_goal
from discord import Thread, Embed
from daily_updates import fetch_user_info, fetch_todoist_token, fetch_tasks_from_todoist, fetch_completed_tasks_from_todoist, get_or_create_thread
from habits import add_habit, delete_habit, record_habit_entry, fetch_completed_habits, fetch_user_habits, calculate_7_day_momentum
import aiocron
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


#Log standups internally
async def log_standups_internal(guild_id, channel):
  # Fetch the goal for the guild
  goal_query = """
      SELECT goal
      FROM guilds
      WHERE guild_id = :guild_id;
  """
  goal_result = await fetch_query(goal_query, {'guild_id': guild_id})

  if not goal_result:
    print("No goal data available for this guild.")
    return

  goal = goal_result[0]['goal']

  # Fetch users with their Beeminder auth tokens for the guild
  user_query = """
      SELECT beeminder_username, beeminder_auth_token
      FROM users
      WHERE guild_id = :guild_id;
  """
  users = await fetch_query(user_query, {'guild_id': guild_id})

  if not users:
    print("No user data available for this guild.")
    return

  successful_requests = 0
  errors = []

  async with aiohttp.ClientSession() as session:
    for user in users:
      beeminder_username = user['beeminder_username']
      auth_token = user['beeminder_auth_token']
      apiUrl = f"https://www.beeminder.com/api/v1/users/{beeminder_username}/goals/{goal}/datapoints.json"
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
  last_entry_date = last_entry_date.astimezone(
      central_tz) if last_entry_date else None
  entry_date = entry_date.astimezone(central_tz)

  if last_entry_date is None or last_entry_date.date(
  ) != entry_date.date() - timedelta(days=1):
    return 1
  else:
    return 1


def make_button_callback(user_id, habit_id, habit_title):

  async def button_callback(interaction):
    try:
      # Call the function to record the habit entry in the database
      await record_habit_entry(user_id, habit_id)
      # Send a confirmation message to the user
      await interaction.response.send_message(
          f"'{habit_title}' habit recorded successfully!", ephemeral=True)
    except Exception as e:
      # Handle any errors that occur during the database operation
      print(f"Error recording habit entry: {e}")
      await interaction.response.send_message(
          "There was an error recording your habit. Please try again.",
          ephemeral=True)

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

  # Fetch the goal for the guild
  goal_query = """
        SELECT goal
        FROM guilds
        WHERE guild_id = :guild_id;
    """
  goal_result = await fetch_query(goal_query, {'guild_id': guild_id})

  if not goal_result:
    await ctx.send("No goal data available for this guild.")
    return

  goal = goal_result[0]['goal']

  # Fetch Beeminder usernames for users in the guild
  user_query = """
        SELECT beeminder_username
        FROM users
        WHERE guild_id = :guild_id;
    """
  users = await fetch_query(user_query, {'guild_id': guild_id})

  if not users:
    await ctx.send("No user data available.")
    return

  for user in users:
    beeminder_username = user['beeminder_username']
    graph_url = f"https://www.beeminder.com/{beeminder_username}/{goal}.png?{timestamp}"
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


@bot.command(name='removestandups',
             help='Remove the most recent standup data point for all users')
async def remove_standups(ctx):
  guild_id = ctx.guild.id

  # Fetch the goal for the guild
  goal_query = """
  SELECT goal
  FROM guilds
  WHERE guild_id = :guild_id;
  """
  goal_result = await fetch_query(goal_query, {'guild_id': guild_id})

  if not goal_result:
    await ctx.send("No goal data available for this guild.")
    return

  goal = goal_result[0]['goal']

  # Fetch users and their Beeminder auth tokens for the guild
  user_query = """
  SELECT beeminder_username, beeminder_auth_token
  FROM users
  WHERE guild_id = :guild_id;
  """
  users = await fetch_query(user_query, {'guild_id': guild_id})

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
      data_point_id = await fetch_most_recent_data_point_id(
          beeminder_username, auth_token, goal)

      if not data_point_id:
        errors.append(f"No data point found for {beeminder_username}")
        continue

      delete_url = f"https://www.beeminder.com/api/v1/users/{beeminder_username}/goals/{goal}/datapoints/{data_point_id}.json?auth_token={auth_token}"

      try:
        async with session.delete(delete_url) as response:
          if response.status == 200:
            successful_deletions += 1
          else:
            error = await response.text()
            errors.append(
                f"Error for {beeminder_username}: {response.status} - {error}")
      except Exception as e:
        errors.append(f"Exception for {beeminder_username}: {str(e)}")

  if successful_deletions == len(users):
    await ctx.send("Most recent data point removed successfully for all users."
                   )
  else:
    error_messages = '\n'.join(errors)
    await ctx.send(f"Errors occurred during deletion:\n{error_messages}")


async def fetch_most_recent_data_point_id(beeminder_username, auth_token,
                                          goal):
  url = f"https://www.beeminder.com/api/v1/users/{beeminder_username}/goals/{goal}/datapoints.json?auth_token={auth_token}"

  async with aiohttp.ClientSession() as session:
    try:
      async with session.get(url) as response:
        if response.status == 200:
          data_points = await response.json()

          if not data_points:
            print(f"No data points found for {beeminder_username}")
            return None

          # Sort the data points by the 'updated_at' or 'timestamp' field to find the most recent one
          most_recent_data_point = max(data_points,
                                       key=lambda x: x['timestamp'])

          # Return the ID of the most recent data point
          return most_recent_data_point['id']
        else:
          error = await response.text()
          print(
              f"Error fetching data points for {beeminder_username}: {response.status} - {error}"
          )
          return None
    except Exception as e:
      print(
          f"Exception occurred while fetching data points for {beeminder_username}: {str(e)}"
      )
      return None


@bot.event
async def on_voice_state_update(member, before, after):
  print(f"Voice state update detected for member: {member.name}")

  if before.channel != after.channel:
    print(f"Member {member.name} changed channels.")
    guild = after.channel.guild if after.channel else before.channel.guild
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
          user_discordid_query = "SELECT discord_id FROM users WHERE guild_id = :guild_id;"
          active_users = await fetch_query(user_discordid_query, {"guild_id": guild_id})
          active_user_ids = {user['discord_id'] for user in active_users}
          active_members = []

          # Fetch Member objects for each active user ID
          for user_id in active_user_ids:
            try:
                member = await guild.fetch_member(user_id)
                if member:
                    active_members.append(member)
            except Exception as e:
                print(f"Error fetching member with ID {user_id}: {e}")
          user_count_result = await fetch_query(user_count_query,
                                                {"guild_id": guild_id})
          user_count = user_count_result[0][0] if user_count_result else 0
          print("dates", today_date, last_log_date)
          # Adjust condition based on sandbox mode
          if SANDBOX_MODE:
              condition = (today_date == last_log_date)
          else:
              condition = (len(after.channel.members) == user_count and today_date != last_log_date)

          if condition:
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
              # Trigger daily updates for each user in the voice channel
              monitored_channel = discord.utils.get(member.guild.text_channels, name=monitored_channel_name)
              for member in active_members:
                try:
                  await direct_daily_update(member, monitored_channel)
                  print(f"Daily update triggered for {member.display_name}")
                except Exception as e:
                  print(f"Failed to trigger daily update for {member.display_name}: {e}")
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


async def fetch_habit_completion_days(user_id, habit_id, database):
  # Calculate the date range for the last 7 days
  today = date.today()
  seven_days_ago = today - timedelta(
      days=6)  # Include today in the count

  completion_query = """
  SELECT COUNT(DISTINCT DATE(entry_date)) AS completed_days
  FROM habit_entries
  WHERE user_id = :user_id AND habit_id = :habit_id AND entry_date BETWEEN :start_date AND :end_date
  """
  result = await database.fetch_one(
      completion_query, {
          'user_id': user_id,
          'habit_id': habit_id,
          'start_date': seven_days_ago,
          'end_date': today
      })
  return result['completed_days'] if result else 0

async def get_task_summary(user_id, database):
  todoist_token = await fetch_todoist_token(user_id, database)
  if not todoist_token:
      return None, "Todoist API token not found. Please set it up."

  completed_tasks = await fetch_completed_tasks_from_todoist(todoist_token)
  today_tasks = await fetch_tasks_from_todoist(todoist_token, "today")

  completed_tasks_str = "\n".join([f"✅ {task['content']}" for task in completed_tasks]) if completed_tasks else "No tasks completed yesterday."
  today_tasks_str = "\n".join([f"🕒 {task[0]}" for task in today_tasks]) if today_tasks else "You're all clear for today!"

  return completed_tasks_str, today_tasks_str

async def create_habit_embed(user_id, database):
  habit_embed = Embed(title="💪 Habit Tracker", color=0x00ff00)
  habits = await fetch_user_habits(user_id)
  if habits:
      for habit in habits:
          completed_days = await fetch_habit_completion_days(str(user_id), habit['id'], database)
          habit_embed.add_field(name=f"{habit['title']}",
                                value=f"Streak: {habit['streak']} | Overall: {habit['overall_counter']} | Last 7 Days: {completed_days}/7",
                                inline=False)
  else:
      habit_embed.description = "No habits recorded."
  
  return habit_embed

def format_task_message(completed_tasks_str, today_tasks_str):
  base_message = "🎯 **Completed Tasks Yesterday:**\n"
  additional_message = "\n🚀 **Today's Tasks:**\n"
  available_length = 2000 - len(base_message) - len(additional_message) - 100  # 100 characters reserved for potential truncation message
  
  if len(completed_tasks_str) + len(today_tasks_str) > available_length:
      # Calculate how much space we can use for each part
      half_length = available_length // 2
      truncated_completed_tasks = (completed_tasks_str[:half_length] + '...') if len(completed_tasks_str) > half_length else completed_tasks_str
      truncated_today_tasks = (today_tasks_str[:half_length] + '...') if len(today_tasks_str) > half_length else today_tasks_str
  
      message = f"{base_message}{truncated_completed_tasks}\n{additional_message}{truncated_today_tasks}\n*Not all tasks are displayed due to message length limits.*"
  else:
      message = f"{base_message}{completed_tasks_str}\n{additional_message}{today_tasks_str}"
  
  return message


@bot.command(name='t', help='Send your daily update')
async def daily_update(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("This command can only be used in DMs.")
        return

    user_id = ctx.author.id  # Get the user ID of the person sending the command
    user_info = await fetch_user_info(user_id, database)
    if not user_info:
        await ctx.send("Could not find your user information in the database.")
        return

    # Assuming you have a method to fetch or create a thread for the user
    guild_id = user_info['guild_id']
    guild = bot.get_guild(guild_id)
    if not guild:
        await ctx.send("Could not find the guild associated with your user information.")
        return

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

    thread = await get_or_create_thread(channel, ctx.author.display_name)

    completed_tasks_str, today_tasks_str = await get_task_summary(user_id, database)
    if not completed_tasks_str:  # This will be None if the token wasn't found
        await thread.send(today_tasks_str)  # This contains the error message
        return

    # Format the task message using the helper function
    task_message = f"🌟 **Daily Update for {ctx.author.name}** 🌟\n\n"
    task_message += format_task_message(completed_tasks_str, today_tasks_str)
    await thread.send(task_message)  # Send the task summary in the thread

    # Create and send the habit tracker embed
    habit_embed = await create_habit_embed(user_id, database)
    await thread.send(embed=habit_embed)



#original dailyupdate2
# @bot.command(name='t', help='Send your daily update')
# async def daily_update(ctx):
#     if not isinstance(ctx.channel, discord.DMChannel):
#         await ctx.send("This command can only be used in DMs.")
#         return

#     user_info = await fetch_user_info(ctx.author.id, database)
#     if not user_info:
#         await ctx.send("Could not find your user information in the database.")
#         return

#     guild_id = user_info['guild_id']
#     guild = bot.get_guild(guild_id)
#     if not guild:
#         await ctx.send("Could not find the guild associated with your user information.")
#         return

#     guild_info_result = await fetch_query(
#         """
#         SELECT monitored_channel_name
#         FROM guilds
#         WHERE guild_id = :guild_id;
#         """, {"guild_id": guild_id})
#     if not guild_info_result or len(guild_info_result) == 0:
#         await ctx.send("Monitored channel not set for the associated guild.")
#         return

#     monitored_channel_name = guild_info_result[0]['monitored_channel_name']
#     channel = discord.utils.get(guild.text_channels, name=monitored_channel_name)
#     if not channel:
#         await ctx.send(f"Monitored text channel '{monitored_channel_name}' not found in the associated guild.")
#         return

#     thread = await get_or_create_thread(channel, ctx.author.display_name)
#     todoist_token = await fetch_todoist_token(ctx.author.id, database)

#     if todoist_token:
#         completed_tasks = await fetch_completed_tasks_from_todoist(todoist_token)
#         today_tasks = await fetch_tasks_from_todoist(todoist_token, "today")

#         task_message = f"🌟 **Daily Update for {ctx.author.name}** 🌟\n\n"

#         # Formatting completed tasks
#         if completed_tasks:
#             completed_tasks_str = "\n".join([f"✅ {task['content']}" for task in completed_tasks])
#         else:
#             completed_tasks_str = "No tasks completed yesterday."

#         # Formatting today's tasks
#         if today_tasks:
#             today_tasks_str = "\n".join([f"🕒 {task[0]}" for task in today_tasks])
#         else:
#             today_tasks_str = "You're all clear for today!"

#         # Checking if the message exceeds the limit
#         if len(task_message + completed_tasks_str + today_tasks_str) > 2000:
#             task_message += f"🎯 **Completed Tasks Yesterday:**\n{completed_tasks_str[:1000]}...\n"
#             task_message += f"\n🚀 **Today's Tasks (partially shown):**\n{today_tasks_str[:500]}...\n"
#             task_message += "\n*Not all tasks are displayed due to message length limits.*"
#         else:
#             task_message += f"🎯 **Completed Tasks Yesterday:**\n{completed_tasks_str}\n"
#             task_message += f"\n🚀 **Today's Tasks:**\n{today_tasks_str}"

#         await thread.send(task_message)

#     else:
#         await thread.send("\nTodoist API token not found. Please set it up.")

#     # Sending the habit tracker as an embed
#     habit_embed = Embed(title="💪 Habit Tracker", color=0x00ff00)
#     habits = await fetch_user_habits(ctx.author.id)
#     if habits:
#         for habit in habits:
#             completed_days = await fetch_habit_completion_days(str(ctx.author.id), habit['id'], database)
#             habit_embed.add_field(name=f"{habit['title']}",
#                             value=f"Streak: {habit['streak']} | Overall: {habit['overall_counter']} | Last 7 Days: {completed_days}/7",
#                             inline=False)
#     else:
#         habit_embed.description = "You have no habits recorded."

#     await thread.send(embed=habit_embed)  # Send the habit summary as an embed


  # # Prepare the habit tracker message with adequate spacing
  # habits_message = "\n\n\n💪 **Habit Tracker:**\n\n"  # Ensure there are two line breaks before and after the header

  # habits = await fetch_user_habits(ctx.author.id)
  # if habits:
  #     for habit in habits:
  #         completed_days = await fetch_habit_completion_days(str(ctx.author.id), habit['id'], database)
  #         habits_message += f"**{habit['title']}**\nStreak: {habit['streak']} | Overall: {habit['overall_counter']} | Last 7 Days: {completed_days}/7\n"
  # else:
  #     habits_message += "You have no habits recorded.\n"

  # await thread.send(habits_message)  # Send the habit summary message


async def fetch_subscribed_users():
  # Example query, adjust according to your database schema
  query = "SELECT discord_id, guild_id FROM users WHERE daily_updates = TRUE"
  print("Fetching subscribed users...")
  return await fetch_query(query)


# @bot.command(name='triggerupdates', help='Manually trigger daily updates for testing.')
# async def trigger_updates(ctx):
#     await ctx.send("Starting manual trigger of daily updates...")
#     await automated_daily_updates()  # Call the function directly
#     local_time_with_zone = datetime.now().astimezone().tzinfo
#     print(f"Server's Local Time Zone: {local_time_with_zone}")
#     await ctx.send("Manual trigger of daily updates completed.")


@bot.command(name='setchannel',
             help='Set a channel to be monitored by the bot')
async def set_channel(ctx, *, channel_name: str):
  guild_id = str(ctx.guild.id)
  voice_channel = discord.utils.get(ctx.guild.voice_channels,
                                    name=channel_name)

  if voice_channel:
    # Check if the guild is already in the database
    check_guild_query = """
      SELECT guild_id FROM guilds WHERE guild_id = :guild_id;
    """
    guild_exists = await fetch_query(check_guild_query, {"guild_id": guild_id})

    # If the guild is not in the database, insert it
    if not guild_exists:
      insert_guild_query = """
          INSERT INTO guilds (guild_id, monitored_channel_id, monitored_channel_name)
          VALUES (:guild_id, :monitored_channel_id, :monitored_channel_name);
      """
      await execute_query(
          insert_guild_query, {
              "guild_id": int(guild_id),
              "monitored_channel_id": voice_channel.id,
              "monitored_channel_name": channel_name
          })
    else:
      # Update the monitored channel details in the database
      update_guild_query = """
          UPDATE guilds
          SET monitored_channel_id = :monitored_channel_id, monitored_channel_name = :monitored_channel_name
          WHERE guild_id = :guild_id;
      """
      await execute_query(
          update_guild_query, {
              "guild_id": int(guild_id),
              "monitored_channel_id": voice_channel.id,
              "monitored_channel_name": channel_name
          })

    await ctx.send(f"Voice channel '{channel_name}' is now being monitored.")
  else:
    await ctx.send(f"No voice channel named '{channel_name}' found.")



async def direct_daily_update(member: discord.Member, channel: discord.TextChannel):
  print('Running daily command')
  user_info = await fetch_user_info(member.id, database)
  if not user_info:
      await channel.send("Could not find user information in the database.")
      return

  guild_id = user_info['guild_id']
  guild = bot.get_guild(guild_id)
  if not guild:
      await channel.send("Could not find the guild associated with the user information.")
      return

  thread = await get_or_create_thread(channel, member.display_name)

  completed_tasks_str, today_tasks_str = await get_task_summary(member.id, database)
  if not completed_tasks_str:  # This will be None if the token wasn't found
      await thread.send(today_tasks_str)  # This contains the error message
      return

  task_message = f"🌟 **Daily Update for {member.display_name}** 🌟\n\n"
  task_message += format_task_message(completed_tasks_str, today_tasks_str)
  await thread.send(task_message)

  habit_embed = await create_habit_embed(member.id, database)
  await thread.send(embed=habit_embed)



# @bot.command(name='daily', help='Send the daily update for a specified user in the current channel')
# async def direct_daily_update(ctx, user: discord.Member):
#     user_info = await fetch_user_info(user.id, database)
#     print('Running daily command')
#     if not user_info:
#         await ctx.send("Could not find user information in the database.")
#         return

#     guild_id = user_info['guild_id']
#     guild = bot.get_guild(guild_id)
#     if not guild:
#         await ctx.send("Could not find the guild associated with the user information.")
#         return

#     guild_info_result = await fetch_query("""
#         SELECT monitored_channel_name
#         FROM guilds
#         WHERE guild_id = :guild_id;
#         """, {"guild_id": guild_id})
#     if not guild_info_result or len(guild_info_result) == 0:
#         await ctx.send("Monitored channel not set for the associated guild.")
#         return

#     monitored_channel_name = guild_info_result[0]['monitored_channel_name']
#     monitored_channel = discord.utils.get(guild.text_channels, name=monitored_channel_name)
#     if not monitored_channel:
#         await ctx.send(f"Monitored text channel '{monitored_channel_name}' not found in the associated guild.")
#         return

#     thread = await get_or_create_thread(monitored_channel, user.display_name)

#     completed_tasks_str, today_tasks_str = await get_task_summary(user.id, database)
#     if not completed_tasks_str:  # This will be None if the token wasn't found
#         await thread.send(today_tasks_str)  # This contains the error message
#         return

#     task_message = f"🌟 **Daily Update for {user.display_name}** 🌟\n\n"
#     task_message += format_task_message(completed_tasks_str, today_tasks_str)
#     await thread.send(task_message)

#     habit_embed = await create_habit_embed(user.id, database)
#     await thread.send(embed=habit_embed)





@bot.command(
    name='adduser',
    help=
    'Add a user with their authToken. Usage: !adduser [username] [authToken]')
async def add_user(ctx, username: str, authToken: str):
  if not username or not authToken:
    await ctx.send("Please provide both a username and an authToken.")
    return

  guild_id = ctx.guild.id
  # Check if the user already exists in the database
  check_user_query = """
      SELECT beeminder_username FROM users WHERE guild_id = :guild_id AND beeminder_username = :username;
  """
  user_exists = await fetch_query(check_user_query, {
      "guild_id": guild_id,
      "username": username
  })

  if user_exists:
    # Update the existing user's authToken
    update_user_query = """
          UPDATE users
          SET beeminder_auth_token = :authToken
          WHERE guild_id = :guild_id AND beeminder_username = :username;
      """
    await execute_query(update_user_query, {
        "guild_id": guild_id,
        "username": username,
        "authToken": authToken
    })
    operation = "updated"
  else:
    # Insert the new user into the database
    insert_user_query = """
          INSERT INTO users (guild_id, beeminder_username, beeminder_auth_token)
          VALUES (:guild_id, :username, :authToken);
      """
    await execute_query(insert_user_query, {
        "guild_id": guild_id,
        "username": username,
        "authToken": authToken
    })
    operation = "added"

  await ctx.send(f"User {username} {operation} successfully.")


# # Command to delete a user
# @bot.command(name='deleteuser',
#              help='Delete a user from the bot. Usage: !deleteuser [username]')
# async def delete_user(ctx, username: str):
#   guild_id = str(ctx.guild.id)
#   data = read_data()
#   if guild_id in data and username in data[guild_id].get("user_data", {}):
#     del data[guild_id]["user_data"][username]
#     write_data(data)
#     await ctx.send(f"User {username} has been removed.")
#   else:
#     await ctx.send(f"User {username} not found in stored data.")

# # Command to list all users stored in the bot
# @bot.command(name='listusers', help='List all users stored in the bot')
# async def list_users(ctx):
#   guild_id = str(ctx.guild.id)
#   data = read_data()
#   user_data = data.get(guild_id, {}).get("user_data", {})
#   if not user_data:
#     await ctx.send("No users are currently stored.")
#     return
#   users_list = '\n'.join([f"- {username}" for username in user_data])
#   await ctx.send(f"Stored users:\n{users_list}")


# Update command definitions to use functions from habits.py
@bot.command(name='addhabit', help='Add a new habit')
async def add_habit_command(ctx, *, habit_title):
  await add_habit(ctx, habit_title)


@bot.command(name='deletehabit', help='Delete a habit')
async def delete_habit_command(ctx, *, habit_title):
  await delete_habit(ctx, habit_title)


#original dailyupdate command
@bot.command(name='h', help='Daily Update w/ Habits in DM')
async def record_habit(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a Direct Message with me.")
        return

    user_id = str(ctx.author.id)
    user_habits = await fetch_user_habits(user_id)

    if not user_habits:
        await ctx.send("You don't have any habits set up yet.")
        return

    view = View()

    # Function to create button callbacks
    def make_button_callback(habit_id, habit_title, user_id):
        async def button_callback(interaction):
            try:
                await record_habit_entry(user_id, habit_id)
                await interaction.response.send_message(f"'{habit_title}' recorded!", ephemeral=True)
            except Exception as e:
                print(f"Error recording habit entry: {e}")
                await interaction.response.send_message("Failed to record habit entry. Please try again later.", ephemeral=True)
        return button_callback

    for habit in user_habits:
        button = Button(label=habit['title'], style=discord.ButtonStyle.primary)
        button.callback = make_button_callback(habit['id'], habit['title'], user_id)
        view.add_item(button)

    finish_button = Button(label="Finish", style=discord.ButtonStyle.green)
    async def finish_callback(interaction):
        # Create an embed with the user's habits
        habit_embed = await create_habit_embed(user_id, database)
        await interaction.response.send_message("Here's your updated habit summary:", embed=habit_embed, ephemeral=True)

    finish_button.callback = finish_callback
    view.add_item(finish_button)

    await ctx.send("Select a habit to record or click 'Finish' when done:", view=view)





@bot.command(name='displayhabits', help='Display completed habits summary')
async def display_habits(ctx):
  # Get the user's Discord ID
  user_id = ctx.author.id

  # Get today's date and yesterday's date
  today_date = datetime.now().date()
  yesterday_date = today_date - timedelta(days=1)

  # Fetch habits completed today and yesterday for the user
  today_habits = await fetch_completed_habits(user_id, today_date)
  yesterday_habits = await fetch_completed_habits(user_id, yesterday_date)

  # Prepare the message
  message = "**Habit Summary**\n-----------------\n"

  # Add completed habits for today
  if today_habits:
    message += "**Completed Today:**\n"
    for habit in today_habits:
      message += f"{habit['title']} - Streak: {habit['streak']}, Overall Counter: {habit['overall_counter']}\n"
  else:
    message += "No habits completed today.\n"

  # Add completed habits for yesterday
  if yesterday_habits:
    message += "\n**Completed Yesterday:**\n"
    for habit in yesterday_habits:
      message += f"{habit['title']} - Streak: {habit['streak']}, Overall Counter: {habit['overall_counter']}\n"
  else:
    message += "No habits completed yesterday.\n"

  # Send the message
  await ctx.send(message)


@bot.command(name='discordid', help='Get the Discord ID of a mentioned user.')
async def discord_id(ctx, user: discord.Member = None):
  if user is None:
    await ctx.send("Please mention a user to get their Discord ID.")
  else:
    await ctx.send(f"The Discord ID of {user.mention} is `{user.id}`.")

async def record_attendance(guild, present_user_ids):
  # Fetch all users in the guild
  query = """
  SELECT discord_id, attendance, missed_standup FROM users WHERE guild_id = :guild_id
  """
  params = {'guild_id': guild.id}
  all_users = await fetch_query(query, params)

  if not all_users:
      return "No users found in the database for this guild."

  present_users = []
  absent_users = []

  for user in all_users:
      if user['discord_id'] in present_user_ids:
          present_users.append(user['discord_id'])
      else:
          absent_users.append(user['discord_id'])

  # Update attendance for present users
  if present_users:
      update_present_query = """
      UPDATE users
      SET attendance = attendance + 1
      WHERE discord_id = ANY(:present_user_ids)
      """
      await execute_query(update_present_query, {'present_user_ids': present_users})

  # Update missed_standup for absent users
  if absent_users:
      update_absent_query = """
      UPDATE users
      SET missed_standup = missed_standup + 1
      WHERE discord_id = ANY(:absent_user_ids)
      """
      await execute_query(update_absent_query, {'absent_user_ids': absent_users})

  return all_users, present_users, absent_users

last_karma_updates = {}

@bot.command(name='karma', help='Record attendance and missed standups, and display karma scores with random insults for absentees')
async def karma(ctx):
    guild = ctx.guild

    # Fetch the monitored channel information from the database
    guild_query = """
        SELECT monitored_channel_name
        FROM guilds
        WHERE guild_id = :guild_id;
    """
    guild_info_result = await fetch_query(guild_query, {"guild_id": guild.id})

    if not guild_info_result:
        await ctx.send("Monitored channel not set for this guild.")
        return

    monitored_channel_name = guild_info_result[0]['monitored_channel_name']
    monitored_channel = discord.utils.get(guild.voice_channels, name=monitored_channel_name)

    if not monitored_channel:
        await ctx.send(f"Monitored voice channel '{monitored_channel_name}' not found.")
        return

    present_user_ids = {member.id for member in monitored_channel.members}

    # Record attendance
    all_users_result = await record_attendance(guild, present_user_ids)
    if isinstance(all_users_result, str):
        await ctx.send(all_users_result)
        return

    all_users, present_users, absent_users = all_users_result

    # Store the changes in last_karma_updates
    last_karma_updates[guild.id] = {'present_users': present_users, 'absent_users': absent_users}

    # Prepare the karma output
    karma_output = "📊 **Karma Scores** 📊\n\n"
    insult_tasks = []

    for user in all_users:
        discord_id = user['discord_id']
        attendance = user['attendance']
        missed_standup = user['missed_standup']

        if discord_id in present_users:
            attendance += 1
        else:
            missed_standup += 1
            insult_tasks.append(get_insult(discord_id))

        karma_score = attendance - missed_standup
        member = guild.get_member(discord_id)
        username = member.display_name if member else f"User ID: {discord_id}"
        karma_output += f"👤 **{username}**\n"
        karma_output += f"- ✅ Attempted: {attendance}\n"
        karma_output += f"- ❌ Missed: {missed_standup}\n"
        karma_output += f"- ⚖️ Karma Score: {karma_score}\n\n"

    insults = await asyncio.gather(*insult_tasks)
    for discord_id, insult in insults:
        member = guild.get_member(discord_id)
        username = member.display_name if member else f"User ID: {discord_id}"
        karma_output += f"**{username}**, {insult}\n"

    await ctx.send(karma_output)

async def get_insult(discord_id):
    async with aiohttp.ClientSession() as session:
        async with session.get('https://evilinsult.com/generate_insult.php?lang=en&type=text') as response:
            if response.status == 200:
                insult = await response.text()
                return (discord_id, insult)
            else:
                return (discord_id, "You're absent, shame on you!")
@bot.command(name='undo_karma', help='Undo the last karma command')
async def undo_karma(ctx):
    guild = ctx.guild
    guild_id = guild.id

    if guild_id not in last_karma_updates:
        await ctx.send("No karma command to undo.")
        return

    updates = last_karma_updates[guild_id]
    present_users = updates['present_users']
    absent_users = updates['absent_users']

    # Revert attendance for present users
    if present_users:
        update_present_query = """
        UPDATE users
        SET attendance = attendance - 1
        WHERE discord_id = ANY(:present_user_ids)
        """
        await execute_query(update_present_query, {'present_user_ids': present_users})

    # Revert missed_standup for absent users
    if absent_users:
        update_absent_query = """
        UPDATE users
        SET missed_standup = missed_standup - 1
        WHERE discord_id = ANY(:absent_user_ids)
        """
        await execute_query(update_absent_query, {'absent_user_ids': absent_users})

    await ctx.send("The last karma command has been undone.")

    # Remove the entry from the dictionary
    del last_karma_updates[guild_id]

@bot.command(name='karmascores', help='Display karma scores for all users')
async def karmascore(ctx):
    guild = ctx.guild

    # Fetch all users information from the database
    query = """
    SELECT discord_id, attendance, missed_standup FROM users WHERE guild_id = :guild_id
    """
    params = {'guild_id': guild.id}
    all_users = await fetch_query(query, params)

    if not all_users:
        await ctx.send("No karma data found for this guild.")
        return

    # Prepare the karma output
    karma_output = "📊 **Karma Scores for All Members** 📊\n\n"
    karma_output += "```"
    karma_output += "👤 User          | ✅ Attempted | ❌ Missed | ⚖️ Karma Score\n"
    karma_output += "------------------------------------------------------------\n"

    for user in all_users:
        discord_id = user['discord_id']
        attendance = user['attendance']
        missed_standup = user['missed_standup']
        karma_score = attendance - missed_standup

        member = guild.get_member(discord_id)
        username = member.display_name if member else f"User ID: {discord_id}"

        # Format the output to align the columns
        karma_output += f"{username:<15} | {attendance:<12} | {missed_standup:<9} | {karma_score:<12}\n"

    karma_output += "```"

    await ctx.send(karma_output)





def run():
  app.run(host='0.0.0.0', port=8080)


if __name__ == "__main__":
  # Start the Flask app in a separate thread
  t = threading.Thread(target=run)
  t.start()

  # Start the Discord bot
  bot.run(TOKEN)

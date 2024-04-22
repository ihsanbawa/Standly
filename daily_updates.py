# daily_updates.py
import aiohttp
import discord
from discord.ext import commands
import datetime
import pytz  # Ensure pytz is installed


async def fetch_todoist_token(user_id, database):
  # Assuming 'database' is an async database connection object
  query = """
    SELECT todoist_api_token
    FROM users
    WHERE discord_id = :user_id;
    """
  result = await database.fetch_one(query, {'user_id': user_id})
  return result['todoist_api_token'] if result else None


async def fetch_tasks_from_todoist(todoist_token, filter):
  headers = {"Authorization": f"Bearer {todoist_token}"}
  url = f"https://api.todoist.com/rest/v2/tasks?filter={filter}"

  async with aiohttp.ClientSession() as session:
    response = await session.get(url, headers=headers)
    if response.status == 200:
      tasks = await response.json()
      return [(task['content'], task.get('due', {}).get('date'))
              for task in tasks]
    else:
      print(
          f"Failed to fetch tasks with filter '{filter}', status code: {response.status}"
      )
      return []


async def post_daily_update(bot, user_id, database):
  user_info = await fetch_user_info(user_id, database)
  if not user_info:
    return "Could not find your user information in the database."

  guild = bot.get_guild(user_info['guild_id'])
  if not guild:
    return "Could not find the guild associated with your user information."

  channel = discord.utils.get(guild.text_channels,
                              name=user_info['monitored_channel_name'])
  if not channel:
    return f"Monitored text channel '{user_info['monitored_channel_name']}' not found in the associated guild."

  thread = await get_or_create_thread(channel, user_info['discord_username'])

  todoist_token = await fetch_todoist_token(user_id, database)
  if todoist_token:
    tasks = await fetch_tasks_from_todoist(todoist_token, "today")
    message_content = "Your tasks for today:\n" + "\n".join(
        [f"- {task[0]}" for task in tasks])
    await thread.send(message_content)
  else:
    await thread.send("Todoist API token not found. Please set it up.")

  return "Daily update posted successfully."


async def fetch_user_info(user_id, database):
  query = """
    SELECT guild_id, discord_username, monitored_channel_name
    FROM users
    WHERE discord_id = :user_id
    """
  result = await database.fetch_one(query, {'user_id': user_id})
  if result:
    return {
        'guild_id': result['guild_id'],
        'discord_username': result['discord_username'],
        'monitored_channel_name': result['monitored_channel_name']
    }
  return None


async def get_or_create_thread(channel, thread_name):
  thread = discord.utils.find(
      lambda t: t.name == thread_name and isinstance(t, discord.Thread),
      channel.threads)
  if not thread:
    thread = await channel.create_thread(
        name=thread_name, type=discord.ChannelType.public_thread)
  return thread


async def fetch_completed_tasks_from_todoist(todoist_token):
  headers = {"Authorization": f"Bearer {todoist_token}"}
  url = "https://api.todoist.com/sync/v9/completed/get_all"

  # Time zone aware datetime for Central Time
  central_tz = pytz.timezone('America/Chicago')
  # Get the current time in Central Time
  now_central = datetime.datetime.now(central_tz)
  # Calculate 'yesterday' in Central Time
  yesterday_central = now_central - datetime.timedelta(days=1)
  since_date = yesterday_central.strftime(
      '%Y-%m-%dT00:00:00')  # Start of yesterday in Central Time

  print("Yesterday for completed tasks (Central Time):", since_date)
  data = {"since": since_date}

  async with aiohttp.ClientSession() as session:
    response = await session.post(url, headers=headers, json=data)
    if response.status == 200:
      completed_tasks = await response.json()
      return completed_tasks.get('items', [])
    else:
      print(f"Failed to fetch completed tasks, status code: {response.status}")
      return []

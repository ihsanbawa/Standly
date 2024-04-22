from database import database, execute_query, fetch_query
from datetime import datetime, timedelta
import pytz
import uuid
import asyncio
import discord
from discord.ui import Button, View, Modal, TextInput


async def fetch_user_habits(discord_id):
  query = """
      SELECT id, title, streak, overall_counter
      FROM habits
      WHERE user_id = :discord_id
  """
  return await fetch_query(query, {'discord_id': str(discord_id)})

async def fetch_completed_habits(user_id, date):
  query = """
      SELECT title, 
             MAX(streak) AS streak, 
             MAX(overall_counter) AS overall_counter 
      FROM habit_entries 
      JOIN habits ON habit_entries.habit_id = habits.id 
      WHERE habit_entries.user_id = :user_id 
      AND DATE(habit_entries.entry_date) = :date 
      GROUP BY title;
  """
  return await fetch_query(query, {'user_id': str(user_id), 'date': date})
async def generate_random_uuid():
    return str(uuid.uuid4())


async def record_habit_entry(user_id, habit_id, quantity=None):
  print(f"Starting to record habit entry for user {user_id} and habit {habit_id}")

  central_tz = pytz.timezone('America/Chicago')
  entry_date = datetime.now(central_tz)
  print(f"Entry date (Central Time): {entry_date}")

  streak_update = await determine_streak_update(user_id, habit_id, entry_date)

  # Update the streak and overall counter in the habits table
  current_streak_query = """
      SELECT streak, overall_counter FROM habits WHERE id = :habit_id
  """
  current_streak_data = await database.fetch_one(current_streak_query, {'habit_id': habit_id})
  new_streak = current_streak_data['streak'] + 1 if streak_update == 1 else 1
  new_overall_counter = current_streak_data['overall_counter'] + 1

  streak_update_query = """
      UPDATE habits SET 
          streak = :new_streak, 
          overall_counter = :new_overall_counter
      WHERE id = :habit_id
  """
  await database.execute(streak_update_query, {
      'new_streak': new_streak,
      'new_overall_counter': new_overall_counter,
      'habit_id': habit_id
  })
  print("Habit streak and overall counter updated.")

  new_entry_id = await generate_random_uuid()
  insert_entry_query = """
      INSERT INTO habit_entries (id, habit_id, entry_date, quantity, user_id)
      VALUES (:new_entry_id, :habit_id, :entry_date, :quantity, :user_id)
  """
  quantity_value = int(quantity) if quantity is not None else 1
  await database.execute(insert_entry_query, {
      'new_entry_id': new_entry_id,
      'habit_id': habit_id,
      'entry_date': entry_date,
      'quantity': quantity_value,
      'user_id': user_id
  })
  print("New habit entry recorded.")


async def determine_streak_update(user_id, habit_id, entry_date):
  central_tz = pytz.timezone('America/Chicago')
  entry_date = entry_date.astimezone(central_tz)

  last_entry_query = """
      SELECT entry_date FROM habit_entries
      WHERE user_id = :user_id AND habit_id = :habit_id
      ORDER BY entry_date DESC LIMIT 1
  """
  last_entry = await database.fetch_one(last_entry_query, {'user_id': user_id, 'habit_id': habit_id})
  last_entry_date = last_entry['entry_date'].astimezone(central_tz) if last_entry else None

  if last_entry_date is None:
      return 1  # First entry for this habit

  date_difference = (entry_date.date() - last_entry_date.date()).days
  if date_difference == 0:
      return 1  # Same day entry, no streak increase
  elif date_difference == 1:
      return 1  # Consecutive day entry, increase streak by 1
  else:
      return 0  # Gap of more than one day, reset streak to zero



async def add_habit(ctx, habit_title):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a Direct Message with me.")
        return

    user_id = str(ctx.author.id)

    insert_habit_query = """
        INSERT INTO habits (id, title, user_id, streak, overall_counter)
        VALUES (:habit_id, :habit_title, :user_id, 0, 0)
    """

    habit_id = await generate_random_uuid()

    try:
        await execute_query(insert_habit_query, {
            'habit_id': habit_id,
            'habit_title': habit_title,
            'user_id': user_id
        })
        await ctx.send(f"New habit '{habit_title}' added successfully!")
    except Exception as e:
        print(f"Error adding new habit: {e}")
        await ctx.send("Failed to add the new habit. Please try again later.")

async def delete_habit(ctx, habit_title):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("Please use this command in a Direct Message with me.")
        return

    user_id = str(ctx.author.id)

    habit_query = """
        SELECT id
        FROM habits
        WHERE user_id = :user_id AND title = :habit_title
    """
    habit_result = await fetch_query(habit_query, {'user_id': user_id, 'habit_title': habit_title})

    if not habit_result:
        await ctx.send(f"You don't have a habit with the title '{habit_title}'.")
        return

    habit_id = habit_result[0]['id']

    delete_entries_query = """
        DELETE FROM habit_entries
        WHERE habit_id = :habit_id
    """
    try:
        await execute_query(delete_entries_query, {'habit_id': habit_id})
    except Exception as e:
        print(f"Error deleting entries associated with habit: {e}")
        await ctx.send("Failed to delete entries associated with the habit. Please try again later.")
        return

    delete_habit_query = """
        DELETE FROM habits
        WHERE id = :habit_id
    """

    try:
        await execute_query(delete_habit_query, {'habit_id': habit_id})
        await ctx.send(f"Habit '{habit_title}' deleted successfully!")
    except Exception as e:
        print(f"Error deleting habit: {e}")
        await ctx.send("Failed to delete the habit. Please try again later.")

from datetime import datetime, timedelta

async def calculate_7_day_momentum(user_id, habit_id, database):
    # Define the 7-day period
    end_date = datetime.now().date()  # Today's date
    start_date = end_date - timedelta(days=6)  # 7 days including today

    # Fetch the completion records for the habit in the last 7 days
    completions = await fetch_habit_completions(user_id, habit_id, start_date, end_date, database)

    # Calculate momentum
    if completions is not None:
        momentum = (completions / 7) * 100  # As a percentage
    else:
        momentum = 0  # If no completions, momentum is 0%

    return round(momentum)

async def fetch_habit_completions(user_id, habit_id, start_date, end_date, database):
# Query to count distinct days a habit was completed by the user in the last 7 days
  query = """
      SELECT COUNT(DISTINCT DATE(entry_date))
      FROM habit_entries
      WHERE user_id = :user_id
      AND habit_id = :habit_id
      AND entry_date::date BETWEEN :start_date AND :end_date
  """
  result = await database.fetch_one(query, {
      'user_id': user_id,
      'habit_id': habit_id,
      'start_date': start_date,
      'end_date': end_date
  })
  
  if result and result[0]:
      return result[0]  # Returns the count of distinct days with completions
  return 0


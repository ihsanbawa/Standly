from database import database
from datetime import datetime, timedelta
import pytz
import uuid
import asyncio
import discord
from discord.ui import Button, View, Modal, TextInput
async def execute_query(query, values={}):
    try:
        return await database.execute(query, values)
    except Exception as e:
        print(f"Database query error: {e}")
        return None

async def fetch_query(query, values={}):
    try:
        return await database.fetch_all(query, values)
    except Exception as e:
        print(f"Database query error: {e}")
        return []

async def generate_random_uuid():
    return str(uuid.uuid4())

async def fetch_user_habits(discord_id):
    query = """
        SELECT id, title
        FROM habits
        WHERE user_id = :discord_id
    """
    return await fetch_query(query, {'discord_id': discord_id})

async def record_habit_entry(user_id, habit_id, quantity=None):
    print(f"Starting to record habit entry for user {user_id} and habit {habit_id}")

    central_tz = pytz.timezone('America/Chicago')
    entry_date = datetime.now(central_tz)
    print(f"Entry date (Central Time): {entry_date}")

    async with database.transaction():
        last_entry_query = """
            SELECT entry_date FROM habit_entries
            WHERE user_id = :user_id AND habit_id = :habit_id
            ORDER BY entry_date DESC LIMIT 1
        """
        last_entry = await database.fetch_one(last_entry_query, {'user_id': user_id, 'habit_id': habit_id})
        last_entry_date = last_entry['entry_date'] if last_entry else None

        streak_update = await determine_streak_update(last_entry_date, entry_date)

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

async def determine_streak_update(last_entry_date, entry_date):
    central_tz = pytz.timezone('America/Chicago')
    last_entry_date = last_entry_date.astimezone(central_tz) if last_entry_date else None
    entry_date = entry_date.astimezone(central_tz)

    if last_entry_date is None or last_entry_date.date() != entry_date.date() - timedelta(days=1):
        return 1
    else:
        return 1

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

    for habit in user_habits:
        habit_id, habit_title = habit['id'], habit['title']

        button = Button(label=habit_title, style=discord.ButtonStyle.primary)

        async def button_callback(interaction, habit_id=habit_id, habit_title=habit_title, user_id=user_id):
            try:
                await record_habit_entry(user_id, habit_id)
                await interaction.response.send_message(f"'{habit_title}' recorded!")
            except Exception as e:
                print(f"Error recording habit entry: {e}")
                await interaction.response.send_message("Failed to record habit entry. Please try again later.")

        button.callback = button_callback

        view.add_item(button)

    await ctx.send("Select a habit to record:", view=view)

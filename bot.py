import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import aiohttp
import time

# Load environment variables from .env file
load_dotenv()
print(os.getenv('DISCORD_BOT_TOKEN'))

#my invitation link: https://discord.com/api/oauth2/authorize?client_id=1187087126219726988&permissions=388160&scope=bot+applications.commands


# Define the intents your bot requires
intents = discord.Intents.default()  # This enables the default intent
intents.members = True  # Enable the member intent if you need to track join/leave events
intents.message_content = True  # Enable the message content intent


# Accessing the bot token from an environment variable
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
monitored_channel_id = None
monitored_channel_name = None  # Store the name of the monitored channel
user_data = {}  # Dictionary to store user data
last_log_date = None  # Variable to track the last logged date
sandbox_mode = True  # Set to False to use the live Beeminder API

async def log_standups_internal():
    if not user_data:
        print("No user data available.")
        return

    successful_requests = 0
    errors = []

    async with aiohttp.ClientSession() as session:
        for username, authToken in user_data.items():
            apiUrl = "https://www.beeminder.com/api/v1/users/{}/goals/standup/datapoints.json".format(username)
            postData = {
                'auth_token': authToken,
                'timestamp': int(time.time()),
                'value': 1,
                'comment': 'logged via discord bot'
            }

            # Check if sandbox mode is enabled
            if sandbox_mode:
                print(f"Mock POST to {apiUrl} with data: {postData}")
                successful_requests += 1
            else:
                try:
                    async with session.post(apiUrl, data=postData) as response:
                        if response.status == 200:
                            successful_requests += 1
                        else:
                            error = await response.text()
                            errors.append(f"Error for {username}: {response.status} - {error}")
                except Exception as e:
                    errors.append(f"Exception for {username}: {str(e)}")

    # Print the response and errors
    if successful_requests == len(user_data):
        print("Standup logged successfully for all users.")
    else:
        error_messages = '\n'.join(errors)
        print(f"Errors occurred:\n{error_messages}")

            

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.command(name='setchannel', help='Set a channel to be monitored by the bot')
async def set_channel(ctx, *, channel_name: str):
    global monitored_channel_id, monitored_channel_name

    voice_channel = discord.utils.get(ctx.guild.voice_channels, name=channel_name)
    if voice_channel:
        monitored_channel_id = voice_channel.id
        monitored_channel_name = channel_name  # Store the name for later use
        await ctx.send(f"Voice channel '{channel_name}' is now being monitored.")
    else:
        await ctx.send(f"No voice channel named '{channel_name}' found.")


@bot.command(name='listchannels', help='List all voice channels in the server')
async def list_channels(ctx):
    channels = ctx.guild.voice_channels
    channel_list = '\n'.join([f"- {channel.name}" for channel in channels])
    await ctx.send(f"Voice Channels:\n{channel_list}")

@bot.command(name='test', help='Test command')
async def test_command(ctx):
    await ctx.send("Test command is working!")

@bot.command(name='adduser', help='Add a user with their authToken. Usage: !adduser [username] [authToken]')
async def add_user(ctx, username: str, authToken: str):
    # Check if the command is sent in a DM for security
    if not isinstance(ctx.channel, discord.channel.DMChannel):
        await ctx.send("Please send this information in a direct message for security.")
        return
        # Check if the user provided both username and authToken
    if username is None or authToken is None:
        await ctx.send("Please provide both a username and an authToken. Usage: `!adduser [username] [authToken]`")
        return
    # Add or update the user data
    user_data[username] = authToken
    print(user_data)
    await ctx.send(f"User {username} added/updated successfully.")

@bot.command(name='deleteuser', help='Delete a user from the bot. Usage: !deleteuser [username]')
async def delete_user(ctx, username: str):
    # Check if the user exists in user_data
    if username in user_data:
        del user_data[username]
        await ctx.send(f"User {username} has been removed.")
    else:
        await ctx.send(f"User {username} not found in stored data.")


@bot.command(name='listusers', help='List all users stored in the bot')
async def list_users(ctx):
    if not user_data:
        await ctx.send("No users are currently stored.")
        return

    users_list = '\n'.join([f"- {username}" for username in user_data])
    await ctx.send(f"Stored users:\n{users_list}")


@bot.command(name='graphs', help='Display Beeminder graphs for all users')
async def graphs(ctx):
    if not user_data:
        await ctx.send("No user data available.")
        return

    for username in user_data:
        graph_url = f"https://www.beeminder.com/{username}/standup.png"
        await ctx.send(f"Graph for {username}: {graph_url}")

@bot.command(name='logstandups', help='Log standups to Beeminder for all users')
async def log_standups(ctx):
    await log_standups_internal()
    await ctx.send("Attempted to log standups for all users.")


@bot.event
async def on_voice_state_update(member, before, after):
    global monitored_channel_id, monitored_channel_name, last_log_date

    if after.channel and after.channel.id == monitored_channel_id:
        today = time.strftime("%Y-%m-%d")
        text_channel = discord.utils.get(after.channel.guild.text_channels, name=monitored_channel_name)

        if len(after.channel.members) == len(user_data) and (last_log_date != today):
            await log_standups_internal()
            last_log_date = today

            if text_channel:
                await text_channel.send(f"Standup logged for users: {', '.join(user_data.keys())} on {today}")
            else:
                print("Corresponding text channel not found.")

        elif last_log_date == today and text_channel:
            await text_channel.send("Standup has already been logged for today.")




bot.run(TOKEN)


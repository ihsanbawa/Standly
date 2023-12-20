import discord
from discord.ext import commands, tasks
import requests
import os

#my invitation link: https://discord.com/api/oauth2/authorize?client_id=1187087126219726988&permissions=388160&scope=bot+applications.commands


# Define the intents your bot requires
intents = discord.Intents.default()  # This enables the default intent
intents.members = True  # Enable the member intent if you need to track join/leave events

# Bot setup
TOKEN = 'MTE4NzA4NzEyNjIxOTcyNjk4OA.GRVWu1.ANkHGqrZa4WNfnp702I4nzg6siitAN24kZtG7s'  # Replace with your bot's token
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variable to store the ID of the monitored channel
monitored_channel_id = None

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.command(name='setchannel', help='Set a channel to be monitored by the bot')
async def set_channel(ctx, *, channel_name: str):
    global monitored_channel_id
    # Find channel by name
    for channel in ctx.guild.voice_channels:
        if channel.name.lower() == channel_name.lower():
            monitored_channel_id = channel.id
            await ctx.send(f"Channel '{channel_name}' is now being monitored.")
            return
    await ctx.send(f"No voice channel named '{channel_name}' found.")

@bot.command(name='listchannels', help='List all voice channels in the server')
async def list_channels(ctx):
    channels = ctx.guild.voice_channels
    channel_list = '\n'.join([f"- {channel.name}" for channel in channels])
    await ctx.send(f"Voice Channels:\n{channel_list}")

@bot.event
async def on_voice_state_update(member, before, after):
    global monitored_channel_id
    channel = after.channel if after.channel is not None else before.channel

    if channel and (monitored_channel_id is None or channel.id == monitored_channel_id):
        channel_members = len(channel.members)
        print(f"Channel '{channel.name}' (ID: {channel.id}) has {channel_members} user(s)")

bot.run(TOKEN)


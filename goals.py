import discord
from discord.ui import Button, View, Modal, TextInput, Select
import aiohttp
from datetime import datetime

MICROSERVICE_BASE_URL = "http://zarathu-env.eba-5kgszm3t.us-east-2.elasticbeanstalk.com"


async def get_goals(discord_user_id):
  url = f"{MICROSERVICE_BASE_URL}/goals/?user_id={discord_user_id}"
  async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
      if response.status == 200:
        return await response.json()
      else:
        error_message = await response.text()
        return {
            "error":
            f"Failed to fetch goals. Status: {response.status}, Message: {error_message}"
        }


async def view_goals(ctx):
  discord_user_id = str(ctx.author.id)
  try:
    goals = await get_goals(discord_user_id)
    if "error" in goals:
      await ctx.send(
          f"Sorry, I couldn't fetch your goals. Error: {goals['error']}")
    else:
      response_message = "Your Goals:\n"
      for goal in goals:
        response_message += f"- {goal['title']} ({goal['status']})\n" \
                            f"  Description: {goal['description']}\n" \
                            f"  Start Date: {goal['start_date']}\n" \
                            f"  End Date: {goal['end_date']}\n" \
                            f"  Category: {goal['category']}\n"
      await ctx.send(response_message)
  except Exception as e:
    await ctx.send(f"An error occurred: {e}")


async def add_goal(ctx):
  button = Button(label="Add New Goal", style=discord.ButtonStyle.green)

  async def button_callback(interaction):
    await interaction.response.send_modal(GoalModal())

  button.callback = button_callback

  # Create an instance of View and add the button to it
  view = View()
  view.add_item(button)

  await ctx.send("Click the button to add a new goal:", view=view)


class GoalModal(Modal):
    def __init__(self):
        super().__init__(title="Add New Goal")
        self.add_item(TextInput(label="Title", placeholder="Enter your goal title", max_length=100))
        self.add_item(TextInput(label="Category", placeholder="e.g., Health, Productivity", max_length=100))
        self.add_item(TextInput(label="Status", placeholder="e.g., In Progress, Completed", max_length=100))

        # Dynamic year calculation
        current_year = datetime.now().year

        # Goal Type Select Menu
        self.goal_type_select = Select(placeholder="Choose the goal type")
        self.goal_type_select.add_option(label=str(current_year), value=str(current_year))
        for quarter in range(1, 5):
            self.goal_type_select.add_option(label=f"{current_year} Q{quarter}", value=f"{current_year} Q{quarter}")
        self.add_item(self.goal_type_select)

    async def callback(self, interaction: discord.Interaction):
        goal_title = self.children[0].value
        category = self.children[1].value
        status = self.children[2].value
        goal_type = self.goal_type_select.values[0]  # Get the selected value

        # User ID can be fetched from the interaction object
        discord_user_id = str(interaction.user.id)

        goal_data = {
            "title": goal_title,
            "category": category,
            "status": status,
            "goal_type": goal_type,
            "user_id": discord_user_id
        }

        url = f"{MICROSERVICE_BASE_URL}/goal/"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=goal_data) as response:
                if response.status in [200, 201]:
                    result = await response.json()
                    await interaction.response.send_message(f"Goal '{goal_title}' added successfully!")
                else:
                    error_message = await response.text()
                    await interaction.response.send_message(f"Failed to add goal. Error: {error_message}")

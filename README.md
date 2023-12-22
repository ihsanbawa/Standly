# 🤖 Standly - A Discord Bot for Standup Logging

Standly is a Discord bot 🤖 designed to facilitate standup logging for teams. It integrates with the Beeminder API 📊 to log standup data points and provides various Discord commands for managing standup sessions within a guild.

## 🌟 Features

- 🎤 Set a monitored voice channel for standup meetings.
- 📈 Automatically logs standup sessions for users.
- 🔗 Integration with Beeminder API for data logging.
- 🛠 Commands for adding and removing users, listing channels, and displaying user graphs.

## 🚀 Installation

Before installing Standly, ensure you have Python 3.8+ installed on your system. Standly can be set up in a few simple steps:

1. **Clone the Repository:** 📋
   ```bash
   git clone https://github.com/ihsanbawa/standly.git
   cd standly
   ```

2. **Set Up a Virtual Environment (Optional):** 🌐
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. **Install Dependencies:** 📥
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:** 🔑
   Create a `.env` file in the root directory and add your Discord bot token and other necessary configurations:
   ```
   DISCORD_BOT_TOKEN=your_discord_bot_token
   SANDBOX_MODE=True_or_False
   ```

## 📘 Usage

Run Standly using the following command:

```bash
python bot.py
```

### 🎮 Commands

- `!setchannel <channel_name>`: Set the voice channel to monitor for standups.
- `!adduser <username> <authToken>`: Add a user with their Beeminder authToken.
- `!deleteuser <username>`: Remove a user from the bot.
- `!listusers`: List all users stored in the bot.
- `!graphs`: Display Beeminder graphs for all users.
- `!logstandups`: Log standups to Beeminder for all users.

## 🤝 Contributing

Contributions to Standly are welcome! Here are a few ways you can help:

- 🐛 Report bugs and issues.
- 💡 Suggest new features or improvements.
- 👨‍💻 Contribute to the codebase with bug fixes or new features.

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

## 💐 Acknowledgements

- [Discord.py](https://github.com/Rapptz/discord.py)
- [Beeminder API](https://www.beeminder.com/api)



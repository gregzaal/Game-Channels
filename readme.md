# Game Channels

Automatically creates a text channel for each game that your users play, and gives them permissions to see it when they play that game. This way people only see the channels for the games they play and don't get spammed with chat they don't care about.

This bot is extremely WIP, good luck!


## Installation

Requires:

* Python 3.5+
* Discord.py (`pip install discord.py`)

## Quick start:

* Clone the repository: `git clone git@github.com:gregzaal/Game-Channels.git`
* Go to the directory: `cd Game-Channels`
* Make folder to store guild settings: `mkdir guilds`
* Install pip: `sudo apt-get -y install python3-pip`
* Install venv: `pip3 install virtualenv`
* Make venv: `python3 -m virtualenv bot-env`
* Use venv: `. bot-env/bin/activate`
* Create your application + bot here: <https://discordapp.com/developers/applications>
* Set up `config.json`:
  * `token` is your bot's private token you can find [here](https://discordapp.com/developers/applications) - do not share it with anyone else.
  * `background_interval` is how often the bot checks player activity. Recommended minimum 5s to avoid API ratelimiting.
```json
{
    "token":"XXXXXXXXXXXXXXXXXXXXXXXX.XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "background_interval":"5"
}
```

* Invite the bot to your own server, replacing `<YOUR BOT ID>` with... your bot ID: `https://discordapp.com/api/oauth2/authorize?client_id=<YOUR BOT ID>&permissions=8&scope=bot`
* Start your bot: `python3 auto-voice-channels.py`

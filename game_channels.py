import os
import json
import discord
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)

last_channel = None
script_dir = os.path.dirname(os.path.realpath(__file__))
script_dir = script_dir+('/' if not script_dir.endswith('/') else '')

default_sc_dict = {
    "role_id": 0,
    "channel_id": 0,
    "games": [],
    "users": [],
    "users_who_left": []
}

def read_json(fp):
    with open(fp, 'r') as f:
        data = json.load(f)
    return data

def write_json(fp, data):
    d = os.path.dirname(fp)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(fp, 'w') as f:
        f.write(json.dumps(data, f, indent=4, sort_keys=True))

def get_config():
    global script_dir
    cf = os.path.join(script_dir, 'config.json')
    if not os.path.exists(cf):
        print ("Config file doesn't exist!")
        import sys
        sys.exit(0)
    return read_json(cf)

config = get_config()

def get_serv_settings(serv_id):
    global script_dir
    fp = os.path.join(script_dir, 'guilds', str(serv_id)+'.json')
    if not os.path.exists(fp):
        write_json(fp, read_json(os.path.join(script_dir, 'default_settings.json')))
    return read_json(fp)

def set_serv_settings(serv_id, settings):
    global script_dir
    fp = os.path.join(script_dir, 'guilds', str(serv_id)+'.json')
    return write_json(fp, settings)

def ldir(o):
    return '[\n'+(',\n'.join(dir(o)))+'\n]'

def fmsg(m):
    # Format message to display in a code block
    s = '```\n'
    s += str(m)
    s += '\n```'
    return s

def strip_quotes(s):
    chars_to_strip = ['\'', '"', ' ']
    if s:
        while s[0] in chars_to_strip:
            if len(s) <= 1:
                break
            s = s[1:]
        while s[-1] in chars_to_strip:
            if len(s) <= 1:
                break
            s = s[:-1]
    return s

def ascii_only(s):
    ns = ""
    printable_chars = list([chr(i) for i in range(32,127)])
    for c in s:
        if c in printable_chars:
            ns += c
        else:
            ns += '_'
    return ns

def convert_to_valid_channel_name(s):
    allowed_characters = "qwertyuiopasdfghjklzxcvbnm-_1234567890"
    s = s.lower()
    s = s.replace(' ', '-')
    sn = ""
    for c in s:
        if c in allowed_characters:
            sn += c
    return sn

def log(msg, guild=None):
    text = datetime.now().strftime("%Y-%m-%d %H:%M")
    text += ' '
    if guild:
        text += '['+guild.name+']'
        text += ' '
    text += str(ascii_only(msg))
    print(text)

async def echo (msg, channel='auto', guild=None):
    global last_channel
    if channel == 'auto':
        channel = last_channel
    elif channel == None:
        log(msg, guild)
        return
    else:
        last_channel = channel

    max_chars = 1950  # Discord has a character limit of 2000 per message. Use 1950 to be safe.
    msg = str(msg)
    sent_msg = None
    if len(msg) < max_chars:
        sent_msg = await catch_http_error(channel.send, msg)
    else:
        # Send message in chunks if it's longer than max_chars
        chunks = list([msg[i:i+max_chars] for i in range(0, len(msg), max_chars)])
        for c in chunks:
            sent_msg = await catch_http_error(channel.send, c)
    return sent_msg

async def catch_http_error (function, *args, **kwargs):
    try:
        if args or kwargs:
            if args and not kwargs:
                r = await function(*args)
            elif kwargs and not args:
                r = await function(**kwargs)
            else:
                r = await function(*args, **kwargs)
        else:
            r = await function()
        return r
    except discord.errors.HTTPException:
        import traceback
        print(traceback.format_exc())
        log ("   !! ENCOUNTERED HTTP ERROR IN FUNC " + function.__name__ + " !!")

async def get_admin_channel (guild):
    settings = get_serv_settings(guild.id)
    for ch in guild.channels:
        if ch.id == settings['admin_channel_id']:
            return ch
    return None

async def update_info_message (guild):
    settings = get_serv_settings(guild.id)
    ch = guild.get_channel(settings['instructions_channel'])
    msg = await ch.get_message(settings['instructions_message'])
    text = "This server has channels for the following games:\n\n"
    scs = sorted(settings["subcommunities"], key=lambda s: s.lower())
    for sc in scs:
        text += "• **"+sc+"**"
        text += "  (" + str(len(settings["subcommunities"][sc]["users"])) + ")"
        text += "\n"
    text += "\n"
    text += "Use `gc-join Game Name` below to join one of them. You will also automatically join them when Discord detects you playing that game.\n"
    text += "These channels are created automatically when 4 or more people in this server play that game.\n"
    text += "Messages in this channel will automatically be deleted after a while."
    await msg.edit(content=text)

async def find_subcommunity (guild, keyword):
    ''' Return a tuple of (name, subcommunity) from a given keyword by matching SC name, game name and channel name. '''

    settings = get_serv_settings(guild.id)

    for scn in settings['subcommunities']:
        sc = settings['subcommunities'][scn]

        if keyword.lower() == scn.lower():
            return (scn, sc)

        for g in sc['games']:
            if keyword.lower() == g.lower():
                return (scn, sc)

        if convert_to_valid_channel_name(keyword) == guild.get_channel(sc['channel_id']):
            return (scn, sc)

    return (None, None)  # Couldn't find SC

async def get_wrapper_cat (guild):
    settings = get_serv_settings(guild.id)
    for cat in guild.categories:
        if cat.id == settings['wrapper_category']:
            return cat
    cat = await initialize_server(guild)  # no wrapper found, initilize server with one
    return cat

async def initialize_server (guild):
    print ("ini start")
    settings = get_serv_settings(guild.id)
    category = await guild.create_category("🎮 Games 🎮")
    settings['wrapper_category'] = category.id
    info_ch = await guild.create_text_channel("games-list…", category=category)
    settings['instructions_channel'] = info_ch.id
    im = await echo("This message will update itself automatically with a list of games that people in this server play.", info_ch)
    settings['instructions_message'] = im.id
    set_serv_settings(guild.id, settings)
    print ("ini end")

async def create_subcommunity (guild, gname, reply_channel=None):
    print (1)
    # Create role
    role_name = "Plays: "+gname
    role = await guild.create_role(name=role_name)
    print (2)
    
    # Create channel
    wrapper = await get_wrapper_cat(guild)
    print (3)
    cname = convert_to_valid_channel_name(gname)
    print (4)
    print (wrapper.id)
    print (5)
    channel = await guild.create_text_channel(cname, category=wrapper)
    print (6)
    await channel.set_permissions(guild.default_role, read_messages=False)
    print (7)
    await channel.set_permissions(role, read_messages=True)
    print (8)
    await echo("Created subcommunity for `"+gname+"` :smiley:", reply_channel)
    print (9)

    settings = get_serv_settings(guild.id)
    print (10)

    # Send welcome message
    text = "This channel for **" + gname + "** was just created automatically, have fun! :)"
    if "subcommunity_announcement" in settings:
        text = settings["subcommunity_announcement"].replace("##game_name##", gname)
    await echo(text, channel)
    print (11)

    # Add record to json
    if gname not in settings['subcommunities']:
        settings['subcommunities'][gname] = default_sc_dict
        settings['subcommunities'][gname]["role_id"] = role.id
        settings['subcommunities'][gname]["channel_id"] = channel.id
        settings['subcommunities'][gname]["games"] = [gname]
        set_serv_settings(guild.id, settings)
        print (12)
    print (13)

    return role

async def remove_subcommunity(guild, channel=None):
    settings = get_serv_settings(guild.id)

    # Find SC in json using channel ID
    sc = None
    for scn in settings['subcommunities']:
        if settings['subcommunities'][scn]['channel_id'] == channel.id:
            sc = settings['subcommunities'][scn]
            break

    if sc:
        # Remove role
        for r in guild.roles:
            if r.id == sc["role_id"]:
                await r.delete()

        # Remove channel
        await channel.delete()

        # Remove record from json
        del settings['subcommunities'][scn]
        set_serv_settings(guild.id, settings)
    else:
        await echo ("Subcommunity associated with this channel couldn't be found.", channel)

async def join_subcommunity(guild, gname, user, channel=None, auto=False):
    settings = get_serv_settings(guild.id)

    scn, sc = await find_subcommunity(guild, gname)

    if sc:
        if auto and user.id in sc["users"]:
            return True

        if user.id not in sc["users"]:
            sc["users"].append(user.id)
        if user.id in sc["users_who_left"]:
            sc["users_who_left"].remove(user.id)
        settings["subcommunities"][scn] = sc
        set_serv_settings(guild.id, settings)
        log(str(user.id) + " joined " + scn, guild)

        role = None
        for r in guild.roles:
            if r.id == sc["role_id"]:
                role = r
                break
        if role:
            await user.add_roles(role)
        else:
            if not auto:
                await echo ("There was an error giving you permissions to the requested subcommunity :cry: Please poke an admin so that they can look into it.", channel)
            return False

        return True
    else:
        if not auto:
            await echo ("Couldn't find any subcommunity using the keyword `" + gname + "`.", channel)
            return False

async def leave_subcommunity(guild, user, channel, gname=None):
    settings = get_serv_settings(guild.id)

    if not gname:
        gname = channel.name
    if not gname:
        await echo ("You need to type this in the channel for the game you want to leave, or specify the game name.", channel)
        return

    scn, sc = await find_subcommunity(guild, gname)

    if sc:
        if user.id in sc["users"]:
            sc["users"].remove(user.id)
            sc["users_who_left"].append(user.id)
            settings["subcommunities"][scn] = sc
            set_serv_settings(guild.id, settings)
            log(str(user.id) + " left " + scn, guild)

        role = None
        for r in guild.roles:
            if r.id == sc["role_id"]:
                role = r
                break
        if role:
            await user.remove_roles(role)
    else:
        await echo ("Couldn't find any subcommunity using the keyword `" + gname + "`.", channel)
    return

async def update_subcommunities(guild, channel=None):
    settings = get_serv_settings(guild.id)
    if not settings['enabled']:
        return

    admin_channel = await get_admin_channel(guild)

    # Check for new games and create communities for them
    games_dict = {}
    for m in guild.members:
        if m.activity and not m.bot:
            gname = m.activity.name
            if gname in games_dict:
                games_dict[gname].append(m)
            else:
                games_dict[gname] = [m]
    for gname in games_dict:
        scn, sc = await find_subcommunity(guild, gname)
        if len(games_dict[gname]) >= settings["playerthreshold"]:
            role = None
            if not sc:
                role = await create_subcommunity(guild, gname, admin_channel)
            else:
                for r in guild.roles:
                    if r.id == sc["role_id"]:
                        role = r
                        break
        if sc:
            for m in games_dict[gname]:
                if m.id not in sc["users_who_left"]:
                    await join_subcommunity(guild, gname, m, auto=True)

    # TODO Order channels by activity
    # for scn in settings['subcommunities']:
    #     sc = settings['subcommunities'][scn]
    #     ch = guild.get_channel(sc['channel_id'])
    #     if ch.category:  # must be inside the wrapper category
    #         ch.edit

    return


class MyClient(discord.Client):
    global config

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # create the background task and run it in the background
        self.bg_task = self.loop.create_task(self.background_task())

    async def on_ready(self):
        print ('Logged in as')
        print (self.user.name)
        print (self.user.id)
        curtime = datetime.now().strftime("%Y-%m-%d %H:%M")
        print (curtime)
        print ('-'*len(str(self.user.id)))
        for s in self.guilds:
            await update_subcommunities(s, None)  # Run once initially. Background task doesn't like printing errors :/

    async def background_task(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(config['background_interval'])
            for s in self.guilds:
                await update_subcommunities(s, None)

client = MyClient()

@client.event
async def on_message(message):
    guild = message.guild
    channel = message.channel
    settings = get_serv_settings(guild.id)

    if message.author == client.user:
        # Don't respond to self
        return

    # Commands
    if message.content.lower().startswith('gc-'):
        msg = message.content[3:]  # Remove prefix
        split = msg.split(' ')
        cmd = split[0].lower()
        params = split[1:]
        params_str = ' '.join(params)

        # Restricted commands
        user_role_ids = list([r.id for r in message.author.roles])
        has_permission = not settings['requiredrole'] or settings['requiredrole'] in user_role_ids
        if has_permission:
            if cmd == 'enable':
                if settings['enabled']:
                    await echo("Already enabled. Use 'gc-disable' to turn off.", channel)
                    await message.add_reaction("❌")
                else:
                    await echo("Enabling subcommunities. Turn off with 'gc-disable'.", channel)
                    settings['enabled'] = True
                    set_serv_settings(guild.id, settings)
                    await message.add_reaction("✅")
                return

            elif cmd == 'disable':
                if not settings['enabled']:
                    await echo("Already disabled. Use 'gc-enable' to turn on.", channel)
                    log("Enabling", guild)
                    await message.add_reaction("❌")
                else:
                    await echo("Disabling subcommunities. Turn on again with 'gc-enable'.", channel)
                    log("Disabling", guild)
                    settings['enabled'] = False
                    set_serv_settings(guild.id, settings)
                    await message.add_reaction("✅")
                return

            elif cmd == 'updateinfomessage':
                await update_info_message(guild)
                await message.add_reaction("✅")
                return

            elif cmd == 'listroles':
                username = strip_quotes(params_str)
                if username:
                    # Show roles of particular user if param is provided
                    found_user = False
                    for m in guild.members:
                        if m.name == username:
                            roles = m.roles
                            found_user = True
                            break
                    if not found_user:
                        await echo ("There is no user named \"" + username + "\"")
                        await message.add_reaction("❌")
                        return
                else:
                    # If no param is provided, show all roles in server
                    roles = guild.roles

                l = ["ID" + ' '*18 + "\"Name\"  (Creation Date)"]
                l.append('='*len(l[0]))
                roles = sorted(roles, key=lambda x: x.created_at)
                for r in roles:
                    l.append(str(r.id)+"  \""+r.name+"\"  (Created on "+r.created_at.strftime("%Y/%m/%d")+")")
                await echo('\n'.join(l), channel)
                await message.add_reaction("✅")
                return

            elif cmd == 'listchannels':
                ch_filter = strip_quotes(params_str)
                text = ""
                scs = sorted(settings["subcommunities"], key=lambda s: s.lower())
                for scn in scs:
                    sc = settings["subcommunities"][scn]
                    cat = await get_wrapper_cat(guild)
                    for ch in cat.channels:
                        if ch_filter == "" or ch_filter in ch.name:
                            text += "• **" + cat.name + "**"
                            text += " > " + ch.name + " `" + str(ch.id) + "`"
                            text += "\n"
                text += "\n"
                await echo (text, channel)
                await message.add_reaction("✅")
                return

            elif cmd == 'restrict':
                role_id = strip_quotes(params_str)
                if not role_id:
                    await echo ("You need to specifiy the id of the role. Use 'gc-listroles' to see the IDs of all roles, then do 'gc-restrict 123456789101112131'", channel)
                    await message.add_reaction("❌")
                else:
                    valid_ids = list([str(r.id) for r in guild.roles])
                    if role_id not in valid_ids:
                        await echo (valid_ids, channel)
                        await echo (role_id + " is not a valid id of any existing role. Use 'gc-listroles' to see the IDs of all roles.", channel)
                        await message.add_reaction("❌")
                    else:
                        role = None
                        for r in guild.roles:
                            if str(r.id) == role_id:    
                                role = r
                                break
                        if role not in message.author.roles:
                            await echo ("You need to have this role yourself in order to restrict commands to it.", channel)
                            await message.add_reaction("❌")
                        else:
                            settings['requiredrole'] = role.id
                            set_serv_settings(guild.id, settings)
                            await echo ("From now on, most commands will be restricted to users with the \"" + role.name + "\" role.", channel)
                            await message.add_reaction("✅")
                return

            elif cmd == 'new':
                await create_subcommunity(guild, params_str, channel)
                await message.add_reaction("✅")
                return

            elif cmd == 'remove':
                await remove_subcommunity(guild, channel=channel)
                await message.add_reaction("✅")
                return

            # TODO 'merge' command to join two communities - merge the user list and game names
            # TODO 'ignore' a game

        # Commands all users can do
        if cmd == 'join':
            success = await join_subcommunity(guild, params_str, message.author, channel)
            await message.add_reaction("✅" if success else "❌")
            return

        elif cmd == 'leave':
            if params_str:
                await leave_subcommunity(guild, message.author, channel, params_str)
                await message.add_reaction("✅")
            else:
                await leave_subcommunity(guild, message.author, channel)
                await message.add_reaction("✅")
            return

        elif cmd == 'list':
            text = "This server has communities for the following games:\n\n"
            scs = sorted(settings["subcommunities"], key=lambda s: s.lower())
            for sc in scs:
                text += "• **"+sc+"**"
                text += "  (" + str(len(settings["subcommunities"][sc]["users"])) + ")"
                text += "\n"
            text += "\n"
            text += "Use `gc-join Game Name` to join one of them. You will also automatically join them when Discord detects you playing that game.\n"
            text += "These communities are created automatically when 4 or more people in this server play that game. They can also be created manually by an admin."
            await echo (text, channel)
            await message.add_reaction("✅")
            return

        else:
            text = "Sorry, `" + cmd + "` is not a recognised command"
            text += ", or you don't have permission to use it." if not has_permission else "."
            await echo(text, channel)
            await message.add_reaction("❌")
            return

    # TODO Auto cleanup (note: returns above mean it rarely reaches here) - delete everything but the last 5 messages, unless they are younger than 24h
    # if channel.id == settings['instructions_channel']:
    #     await message.delete()


client.run(config['token'])

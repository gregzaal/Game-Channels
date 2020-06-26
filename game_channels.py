import os
import json
import discord
import logging
import sys
from datetime import datetime, timedelta
from discord.ext.tasks import loop

''' TODO
Prune channels older than 8 months that haven't had *any* activity ever.
If less than 10 players, just delete it.
If more than 10 players, send message "This channel will be deleted if it still has no activity in the next week".
Maybe keep roles around in case the game gets popular again?
'''

logging.basicConfig(level=logging.INFO)
ADMIN = None

last_channel = None
script_dir = os.path.dirname(os.path.realpath(__file__))
script_dir = script_dir + ('/' if not script_dir.endswith('/') else '')

default_sc_dict = {
    "role_id": 0,
    "channel_id": 0,
    "games": [],
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
        print("Config file doesn't exist!")
        import sys
        sys.exit(0)
    return read_json(cf)


config = get_config()


def get_serv_settings(serv_id):
    global script_dir
    fp = os.path.join(script_dir, 'guilds', str(serv_id) + '.json')
    if not os.path.exists(fp):
        write_json(fp, read_json(os.path.join(script_dir, 'default_settings.json')))
    return read_json(fp)


def set_serv_settings(serv_id, settings):
    global script_dir
    fp = os.path.join(script_dir, 'guilds', str(serv_id) + '.json')
    return write_json(fp, settings)


def ldir(o):
    return '[\n' + (',\n'.join(dir(o))) + '\n]'


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
    printable_chars = list([chr(i) for i in range(32, 127)])
    for c in s:
        if c in printable_chars:
            ns += c
        else:
            ns += '_'
    return ns


def convert_to_valid_channel_name(s):
    allowed_characters = "qwertyuiopasdfghjklzxcvbnm-_ 1234567890"
    s = s.lower()
    s = s.replace(' ', ' ')
    sn = ""
    for c in s:
        if c in allowed_characters:
            sn += c
    return sn


def log(msg, guild=None):
    text = datetime.now().strftime("%Y-%m-%d %H:%M")
    text += ' '
    if guild:
        text += '[' + guild.name + ']'
        text += ' '
    text += str(ascii_only(msg))
    print(text)


async def catch_http_error(function, *args, **kwargs):
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
        log("   !! ENCOUNTERED HTTP ERROR IN FUNC " + function.__name__ + " !!")


async def get_admin_channel(guild):
    settings = get_serv_settings(guild.id)
    for ch in guild.channels:
        if ch.id == settings['admin_channel_id']:
            return ch
    return None


async def update_info_message(guild):
    settings = get_serv_settings(guild.id)
    ch = guild.get_channel(settings['instructions_channel'])
    msg = await ch.fetch_message(settings['instructions_message'])
    scs = sorted(settings["subcommunities"], key=lambda s: s.lower())
    text = "This server has dedicated channels for the following {} games:\n\n".format(len(scs))
    for sc in scs:
        role = guild.get_role(settings["subcommunities"][sc]['role_id'])
        num = len(role.members) if role is not None else 0
        text += "• **" + sc + "**"
        text += "  (" + str(num) + ")"
        text += "\n"
    text += "\n"
    text += "Use `gc-join Game Name` below to join one of them. "
    text += "You will also automatically join them when Discord detects you playing that game.\n"
    text += "These channels are created automatically when "
    text += str(settings["playerthreshold"])
    text += " or more people in this server play that game.\n"
    text += "Messages in this channel will automatically be deleted after a while."
    await msg.edit(content=text)


async def find_subcommunity(guild, keyword):
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


async def get_wrapper_cat(guild):
    settings = get_serv_settings(guild.id)
    for cat in guild.categories:
        if cat.id == settings['wrapper_category']:
            return cat
    cat = await initialize_server(guild)  # no wrapper found, initilize server with one
    return cat


async def initialize_server(guild):
    print("ini start")
    settings = get_serv_settings(guild.id)
    category = await guild.create_category("🎮 Games 🎮")
    settings['wrapper_category'] = category.id
    info_ch = await guild.create_text_channel("games-list…", category=category)
    settings['instructions_channel'] = info_ch.id
    im = await info_ch.send("This message will update itself automatically " +
                            "with a list of games that people in this server play.")
    settings['instructions_message'] = im.id
    set_serv_settings(guild.id, settings)
    print("ini end")


async def create_subcommunity(guild, gname, reply_channel=None):
    # Create role
    role_name = "Plays: " + gname
    role = await guild.create_role(name=role_name)

    # Create channel
    wrapper = await get_wrapper_cat(guild)
    cname = convert_to_valid_channel_name(gname)
    channel = await guild.create_text_channel(cname, category=wrapper)
    await channel.set_permissions(guild.default_role, read_messages=False)
    await channel.set_permissions(role, read_messages=True)
    if reply_channel:
        await reply_channel.send("Created subcommunity for `" + gname + "` :smiley:")

    settings = get_serv_settings(guild.id)

    # Send welcome message
    text = "This channel for **" + gname + "** was just created automatically, have fun! :)"
    if "subcommunity_announcement" in settings:
        text = settings["subcommunity_announcement"].replace("##game_name##", gname)
    await channel.send(text)

    # Add record to json
    if gname not in settings['subcommunities']:
        settings['subcommunities'][gname] = default_sc_dict
        settings['subcommunities'][gname]["role_id"] = role.id
        settings['subcommunities'][gname]["channel_id"] = channel.id
        settings['subcommunities'][gname]["games"] = [gname]
        set_serv_settings(guild.id, settings)

    await update_info_message(guild)

    return role


async def remove_subcommunity(guild, channel=None, gname=None):
    settings = get_serv_settings(guild.id)

    if gname is not None:
        scn, sc = await find_subcommunity(guild, gname)
        if sc:
            channel = guild.get_channel(sc['channel_id'])
        else:
            if channel:
                await channel.send("Couldn't find any subcommunity using the keyword `" + gname + "`.")
            return False

    if channel is not None:
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
            await update_info_message(guild)
            return True
        else:
            await channel.send("Subcommunity associated with this channel couldn't be found.")
            return False

    return False


async def join_subcommunity(guild, gname, user, channel=None, auto=False, role=None):
    settings = get_serv_settings(guild.id)

    scn, sc = await find_subcommunity(guild, gname)

    if sc:
        if role is None:
            for r in guild.roles:
                if r.id == sc["role_id"]:
                    role = r
                    break
        if role is None and not auto:
            await channel.send("It seems the role for that game no longer exists :(")
            return False

        if auto and user in role.members:
            return True

        if user.id in sc["users_who_left"]:
            sc["users_who_left"].remove(user.id)
        settings["subcommunities"][scn] = sc
        set_serv_settings(guild.id, settings)
        log(str(user.id) + " joined " + scn, guild)

        if role:
            await user.add_roles(role)
            if 'welcome' in settings and settings['welcome'] is not None:
                wc = guild.get_channel(sc['channel_id'])
                if wc:
                    e = discord.Embed(color=discord.Color.from_rgb(205, 220, 57))
                    instructions_message = await guild.get_channel(settings['instructions_channel']).fetch_message(
                        settings['instructions_message'])
                    e.title = settings['welcome'].replace("#USER#", user.display_name).replace("#GNAME#", scn)
                    e.description = ("{} was added automatically because this is the first time we noticed them "
                                     "playing {}.\n[More info.]({})".format(
                                         user.mention,
                                         ' / '.join(sc['games']),
                                         instructions_message.jump_url
                                     ))
                    if not auto:
                        e.description = "{} added themselves manually using the join command.".format(user.mention)
                    e.set_thumbnail(url=user.avatar_url_as(size=128))
                    await wc.send(embed=e)
        else:
            if not auto:
                await channel.send("There was an error giving you permissions to the requested subcommunity :cry: " +
                                   "Please poke an admin so that they can look into it.")
            return False

        await update_info_message(guild)
        return True
    else:
        if not auto:
            await channel.send("Couldn't find any subcommunity using the keyword `" + gname + "`.")
            return False


async def leave_subcommunity(guild, user, channel, gname=None):
    settings = get_serv_settings(guild.id)

    if not gname:
        gname = channel.name
    if not gname:
        await channel.send("You need to type this in the channel for the game you want to leave, " +
                           "or specify the game name.")
        return

    scn, sc = await find_subcommunity(guild, gname)

    if sc:
        role = None
        for r in guild.roles:
            if r.id == sc["role_id"]:
                role = r
                break
        if role and user.id in role.members:
            await user.remove_roles(role)
            sc["users_who_left"].append(user.id)
            settings["subcommunities"][scn] = sc
            set_serv_settings(guild.id, settings)
            log(str(user.id) + " left " + scn, guild)
        else:
            await channel.send("It looks like you aren't in that subcommunity.")

        await update_info_message(guild)
    else:
        await channel.send("Couldn't find any subcommunity using the keyword `" + gname + "`.")
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
            if m.activity.type == discord.ActivityType.playing:
                gname = m.activity.name
                if gname in games_dict:
                    games_dict[gname].append(m)
                else:
                    games_dict[gname] = [m]
    for gname in games_dict:
        scn, sc = await find_subcommunity(guild, gname)
        if len(games_dict[gname]) >= settings["playerthreshold"]:
            if not sc:
                await create_subcommunity(guild, gname, admin_channel)
            # else:
            #     for r in guild.roles:
            #         if r.id == sc["role_id"]:
            #             role = r
            #             break
        if sc:
            role = None
            for r in guild.roles:
                if r.id == sc["role_id"]:
                    role = r
                    break
            for m in games_dict[gname]:
                if m.id not in sc["users_who_left"]:
                    await join_subcommunity(guild, gname, m, auto=True, role=role)

    # TODO Order channels by activity
    # for scn in settings['subcommunities']:
    #     sc = settings['subcommunities'][scn]
    #     ch = guild.get_channel(sc['channel_id'])
    #     if ch.category:  # must be inside the wrapper category
    #         ch.edit

    return


@loop(seconds=config['background_interval'])
async def update_loop(client):
    if not client.is_ready():
        return

    for g in client.guilds:
        await update_subcommunities(g, None)


class MyClient(discord.Client):
    global config

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        global ADMIN

        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        curtime = datetime.now().strftime("%Y-%m-%d %H:%M")
        print(curtime)
        print('-' * len(str(self.user.id)))

        if ADMIN is None:
            ADMIN = client.get_user(config['admin_id'])
            await ADMIN.send("READY")


client = MyClient()


@client.event
async def on_message(message):
    if not client.is_ready():
        return

    if message.author.bot:
        # Don't respond to self or bots
        return

    guild = message.guild
    channel = message.channel

    if not guild:
        if channel == ADMIN.dm_channel:
            cmd = message.content
            if cmd == 'log':
                logfile = "log.txt"
                if not os.path.exists(logfile):
                    await channel.send("No log file")
                    return
                with open(logfile, 'r', encoding="utf8") as f:
                    data = f.read()
                data = data[-10000:]  # Drop everything but the last 10k characters to make string ops quicker
                data = data.replace('  CMD Y: ', '  C✔ ')
                data = data.replace('  CMD F: ', '  C✖ ')
                data = data.replace("Traceback (most recent", "❗❗Traceback (most recent")
                data = data.replace("discord.errors.", "❗❗discord.errors.")
                data = data.replace('  ', ' ')  # Reduce indent to save character space
                character_limit = 2000 - 17  # 17 for length of ```autohotkey\n at start and ``` at end.
                data = data[character_limit * -1:]
                data = data.split('\n', 1)[1]
                lines = data.split('\n')
                for i, l in enumerate(lines):
                    # Fake colon (U+02D0) to prevent highlighting the line
                    if " ⏩" in l:
                        lines[i] = l.replace(':', 'ː')
                    elif l.startswith('T '):
                        if '[' in l:
                            s = l.split('[', 1)
                            lines[i] = s[0] + '[' + s[1].replace(':', 'ː')
                data = '\n'.join(lines)
                data = '```autohotkey\n' + data
                data = data + '```'
                await channel.send(data)

            if cmd == 'exit':
                print("Exiting!")
                await client.close()
                sys.exit()
        return

    settings = get_serv_settings(guild.id)

    # Cleanup instructions_channel - delete everything older than 24h
    if channel.id == settings['instructions_channel']:
        old = datetime.today() - timedelta(days=1)
        async for m in channel.history(before=old):
            if m.id != settings['instructions_message']:
                await m.delete()

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
                    await channel.send("Already enabled. Use 'gc-disable' to turn off.")
                    await message.add_reaction("❌")
                else:
                    await channel.send("Enabling subcommunities. Turn off with 'gc-disable'.")
                    settings['enabled'] = True
                    set_serv_settings(guild.id, settings)
                    await message.add_reaction("✅")
                return

            elif cmd == 'disable':
                if not settings['enabled']:
                    await channel.send("Already disabled. Use 'gc-enable' to turn on.")
                    log("Enabling", guild)
                    await message.add_reaction("❌")
                else:
                    await channel.send("Disabling subcommunities. Turn on again with 'gc-enable'.")
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
                        await channel.send("There is no user named \"" + username + "\"")
                        await message.add_reaction("❌")
                        return
                else:
                    # If no param is provided, show all roles in server
                    roles = guild.roles

                l = ["ID" + ' ' * 18 + "\"Name\"  (Creation Date)"]
                l.append('=' * len(l[0]))
                roles = sorted(roles, key=lambda x: x.created_at)
                for r in roles:
                    l.append(str(r.id) + "  \"" + r.name + "\"  (Created on " + r.created_at.strftime("%Y/%m/%d") + ")")
                await channel.send('\n'.join(l))
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
                await channel.send(text)
                await message.add_reaction("✅")
                return

            elif cmd == 'restrict':
                role_id = strip_quotes(params_str)
                if not role_id:
                    await channel.send("You need to specifiy the id of the role. " +
                                       "Use 'gc-listroles' to see the IDs of all roles, " +
                                       "then do 'gc-restrict 123456789101112131'")
                    await message.add_reaction("❌")
                else:
                    valid_ids = list([str(r.id) for r in guild.roles])
                    if role_id not in valid_ids:
                        await channel.send(valid_ids)
                        await channel.send(role_id + " is not a valid id of any existing role. " +
                                           "Use 'gc-listroles' to see the IDs of all roles.")
                        await message.add_reaction("❌")
                    else:
                        role = None
                        for r in guild.roles:
                            if str(r.id) == role_id:
                                role = r
                                break
                        if role not in message.author.roles:
                            await channel.send("You need to have this role in order to restrict commands to it.")
                            await message.add_reaction("❌")
                        else:
                            settings['requiredrole'] = role.id
                            set_serv_settings(guild.id, settings)
                            await channel.send("From now on, most commands will be restricted to users with the \"" +
                                               role.name + "\" role.")
                            await message.add_reaction("✅")
                return

            elif cmd == 'playerthreshold':
                thresh = strip_quotes(params_str)
                try:
                    int(thresh)
                except ValueError:
                    await channel.send("Invalid input: `" + thresh + "`, please type a valid number. " +
                                       "E.g: `gc-playerthreshold 4`")
                    await message.add_reaction("❌")
                    return
                else:
                    settings['playerthreshold'] = int(thresh)
                    set_serv_settings(guild.id, settings)
                    await message.add_reaction("✅")
                    return

            elif cmd == 'new':
                await create_subcommunity(guild, params_str, channel)
                await message.add_reaction("✅")
                return

            elif cmd == 'remove':
                gname = strip_quotes(params_str)
                if gname:
                    success = await remove_subcommunity(guild, channel=channel, gname=gname)
                else:
                    success = await remove_subcommunity(guild, channel=channel)
                await message.add_reaction("✅" if success else "❌")
                return

            elif cmd == 'ping':
                try:
                    r = await channel.send("One moment...")
                except discord.errors.Forbidden:
                    log("Forbidden to send message", guild)
                    return False, "NO RESPONSE"
                t1 = message.created_at
                t2 = r.created_at
                embed = discord.Embed(color=discord.Color.from_rgb(205, 220, 57))
                rc = (t2 - t1).total_seconds()
                e = '😭' if rc > 5 else ('😨' if rc > 1 else '👌')
                embed.add_field(name="Reaction time:", value="{0:.3f}s {1}\n".format(rc, e))
                rc = client.latency
                e = '😭' if rc > 5 else ('😨' if rc > 1 else '👌')
                embed.add_field(name="Discord latency:", value="{0:.3f}s {1}\n".format(rc, e))
                embed.add_field(name="Guild region:", value=guild.region)
                await r.edit(content="Pong!", embed=embed)
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

        else:
            text = "Sorry, `" + cmd + "` is not a recognised command"
            text += ", or you don't have permission to use it." if not has_permission else "."
            await channel.send(text)
            await message.add_reaction("❌")
            return

update_loop.start(client)
client.run(config['token'])

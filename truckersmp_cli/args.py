"""
Arguments handler for truckersmp-cli main script.

Licensed under MIT.
"""

import argparse
import logging
import os
import platform
import sys

from .utils import VDF_IS_AVAILABLE, get_current_steam_user
from .variables import AppId, Args, Dir


ACTIONS = (
    ("start", "start game"),
    ("update", "update/install latest game"),
    ("downgrade", 'downgrade game (install game from "temporary_X_Y" branch)'),
    ("updateandstart", '"update" and "start"'),
    ("ustart", 'same as "updateandstart" ("update" and "start")'),
    ("downgradeandstart", '"downgrade" and "start"'),
    ("dstart", 'same as "downgradeandstart" ("downgrade" and "start")'),
)

GAMES = (
    ("ets2mp", "ETS2 multiplayer"),
    ("ets2", "ETS2 singleplayer"),
    ("atsmp", "ATS multiplayer"),
    ("ats", "ATS singleplayer"),
)


def check_args_errors():
    """Check command-line arguments."""
    # pylint: disable=too-many-branches,too-many-statements

    # warn if using deprecated options
    if Args.ets2:
        logging.warning("'--ets2' ('-e') option is deprecated, use new syntax instead")
    if Args.ats:
        logging.warning("'--ats' ('-a') option is deprecated, use new syntax instead")
    if Args.update:
        logging.warning("'--update' ('-u') option is deprecated, use new syntax instead")
    if Args.downgrade:
        logging.warning("'--downgrade' option is deprecated, use new syntax instead")
    if Args.start:
        logging.warning("'--start' ('-s') option is deprecated, use new syntax instead")
    if Args.singleplayer:
        logging.warning("'--singleplayer' option is deprecated, use new syntax instead")

    # check actions in new syntax
    if Args.action == "start":
        Args.start = True
    elif Args.action == "update":
        Args.update = True
    elif Args.action == "downgrade":
        Args.downgrade = True
    elif Args.action == "updateandstart" or Args.action == "ustart":
        Args.update = Args.start = True
    elif Args.action == "downgradeandstart" or Args.action == "dstart":
        Args.downgrade = Args.start = True

    # check game names in new syntax
    if Args.game == "ets2mp":
        Args.ets2 = True
    elif Args.game == "atsmp":
        Args.ats = True
    elif Args.game == "ets2":
        Args.ets2 = Args.singleplayer = True
    elif Args.game == "ats":
        Args.ats = Args.singleplayer = True

    # "--downgrade" implies "--update"
    if Args.downgrade:
        Args.update = True

    # checks for updating and/or starting
    if not Args.update and not Args.start:
        logging.info("--update/--start not specified, doing both.")
        Args.start = True
        Args.update = True

    # make sure only one game is chosen
    if Args.ats and Args.ets2:
        sys.exit("It's only possible to use one game at a time.")
    elif not Args.ats and not Args.ets2:
        logging.info("--ats/--ets2 not specified, choosing ETS2.")
        Args.ets2 = True

    game = "ats" if Args.ats else "ets2"
    Args.steamid = str(AppId.game[game])
    if not Args.prefixdir:
        Args.prefixdir = Dir.default_prefixdir[game]
    if not Args.gamedir:
        Args.gamedir = Dir.default_gamedir[game]

    # make sure proton and wine aren't chosen at the same time
    if Args.proton and Args.wine:
        sys.exit("Start/Update with Proton (-p) or Wine (-w)?")
    elif not Args.proton and not Args.wine:
        if platform.system() == "Linux":
            logging.info("Platform is Linux, using Proton")
            Args.proton = True
        else:
            logging.info("Platform is not Linux, using Wine")
            Args.wine = True

    # make sure proton and wine are using the same default
    if Args.wine:
        if (Args.prefixdir == Dir.default_prefixdir["ats"]
                or Args.prefixdir == Dir.default_prefixdir["ets2"]):
            logging.debug("""Prefix directory is the default while using Wine,
making sure it's the same directory as Proton""")
            Args.prefixdir = os.path.join(Args.prefixdir, "pfx")

        # always activate the Windows Steam check when not using Proton
        Args.check_windows_steam = True

    # default Steam directory for Wine
    if not Args.wine_steam_dir:
        Args.wine_steam_dir = os.path.join(
            Args.prefixdir,
            "" if Args.wine else "pfx",
            "dosdevices/c:/Program Files (x86)/Steam")

    # checks for starting while not updating
    if Args.start and not Args.update:
        # check for game
        if (not os.path.isfile(
                os.path.join(Args.gamedir, "bin/win_x64/eurotrucks2.exe"))
                and not os.path.isfile(
                    os.path.join(Args.gamedir, "bin/win_x64/amtrucks.exe"))):
            sys.exit("""Game not found in {}
Need to download (-u) the game?""".format(Args.gamedir))

    # checks for updating
    if Args.update and not Args.account:
        if VDF_IS_AVAILABLE:
            Args.account = get_current_steam_user()
        if not Args.account:
            logging.info("Unable to find logged in steam user automatically.")
            sys.exit("Need the steam account name (-n name) to update.")

    # check for Wine desktop size
    if Args.wine_desktop:
        split_size = Args.wine_desktop.split("x")
        if len(split_size) != 2:
            sys.exit("Desktop size ({}) must be 'WIDTHxHEIGHT' format".format(
                Args.wine_desktop))
        try:
            # if given desktop size is too small,
            # set to 1024x768 (the lowest resolution in ETS2/ATS)
            if int(split_size[0]) < 1024 or int(split_size[1]) < 768:
                logging.info(
                    "Desktop size (%s) is too small, setting size to 1024x768.",
                    Args.wine_desktop,
                )
                Args.wine_desktop = "1024x768"
        except ValueError:
            sys.exit("Invalid desktop width or height ({})".format(Args.wine_desktop))

    # info
    logging.info("AppID/GameID: %s (%s)", Args.steamid, game)
    logging.info("Game directory: %s", Args.gamedir)
    logging.info("Prefix: %s", Args.prefixdir)
    if Args.proton:
        logging.info("Proton directory: %s", Args.protondir)
        logging.info("Steam Runtime directory: %s", Args.steamruntimedir)


def create_arg_parser():
    """
    Create an ArgumentParser object.

    This function returns 2-element tuple:
    * The 1st element is the new ArgumentParser object
      (used only in "truckersmp-cli" program)
    * The 2nd element is a list of _StoreAction objects
      (used only in "gen_completions" program)
    """
    # pylint: disable=too-many-statements
    desc = """
A simple launcher for TruckersMP to play ATS or ETS2 in multiplayer.

truckersmp-cli allows to download TruckersMP and handles starting TruckersMP
through Wine while supporting the Windows versions of
American Truck Simulator and Euro Truck Simulator 2.

The Windows version of Steam should already be able to run in the same
Wine prefix. The Windows versions of ATS and ETS2 can be installed and updated
via SteamCMD while all running Steam processes will be stopped
to prevent Steam from loosing connection. Your Steam password
and guard code are required by SteamCMD once for this to work.

On Linux it's possible to start TruckersMP through Proton.
A working native Steam installation is needed for this which has
the desired game installed or with an update pending.
SteamCMD can use your saved credentials for convenience.
"""
    store_actions = []
    epilog = "Proton AppID list:\n"
    for key, val in AppId.proton.items():
        default_mark = ""
        if key == AppId.proton["default"]:
            default_mark += " (Default)"
        if key != "default":
            epilog += "    Proton {:13}: {:>10}{}\n".format(key, val, default_mark)
    parser = argparse.ArgumentParser(
        description=desc, epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    store_actions.append(parser.add_argument(
        "-a", "--ats",
        help="**DEPRECATED** use American Truck Simulator",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "-b", "--beta", metavar="VERSION", type=str,
        help="""set game version to VERSION,
                useful for downgrading (e.g. "temporary_1_35")"""))
    store_actions.append(parser.add_argument(
        "-d", "--enable-d3d11",
        help="use Direct3D 11 instead of OpenGL",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "-e", "--ets2",
        help="""**DEPRECATED** use Euro Truck Simulator 2
                [Default if neither ATS or ETS2 are specified] """,
        action="store_true"))
    store_actions.append(parser.add_argument(
        "-g", "--gamedir", metavar="DIR", type=str,
        help="""choose a different directory for the game files
                [Default: $XDG_DATA_HOME/truckersmp-cli/(Game name)/data]"""))
    store_actions.append(parser.add_argument(
        "-i", "--proton-appid", metavar="APPID", type=int,
        default=AppId.proton[AppId.proton["default"]],
        help="""choose a different AppID for Proton (Needs an update for changes)
                [Default: {}]""".format(AppId.proton[AppId.proton["default"]])))
    store_actions.append(parser.add_argument(
        "-l", "--logfile", metavar="LOG", type=str,
        default="",
        help="""write log into LOG, "-vv" option is recommended
                [Default: Empty string (only stderr)]
                Note: Messages from Steam/SteamCMD won't be written,
                only from this script (Game logs are written into
                "My Documents/{ETS2,ATS}MP/logs/client_*.log")"""))
    store_actions.append(parser.add_argument(
        "-m", "--moddir", metavar="DIR", type=str,
        help="""choose a different directory for the mod files
                [Default: $XDG_DATA_HOME/truckersmp-cli/TruckersMP,
                Fallback: ./truckersmp]"""))
    store_actions.append(parser.add_argument(
        "-n", "--account", metavar="NAME", type=str,
        help="""steam account name to use
                (This account should own the game and ideally is logged in
                with saved credentials)"""))
    store_actions.append(parser.add_argument(
        "-o", "--protondir", metavar="DIR", type=str,
        default=Dir.default_protondir,
        help="""choose a different Proton directory
                [Default: $XDG_DATA_HOME/truckersmp-cli/Proton]
                While updating any previous version in this folder gets changed
                to the given (-i) or default Proton version"""))
    store_actions.append(parser.add_argument(
        "-p", "--proton",
        help="""start the game with Proton
                [Default on Linux if neither Proton or Wine are specified] """,
        action="store_true"))
    store_actions.append(parser.add_argument(
        "-s", "--start",
        help="""**DEPRECATED** start the game
                [Default if neither start or update are specified]""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--steamruntimedir", metavar="DIR",
        default=Dir.default_steamruntimedir,
        help="""choose a different Steam Runtime directory for Proton 5.13 or newer
                [Default: $XDG_DATA_HOME/truckersmp-cli/SteamRuntime]"""))
    store_actions.append(parser.add_argument(
        "-u", "--update",
        help="""**DEPRECATED** update the game
                [Default if neither start or update are specified]""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "-v", "--verbose",
        help="verbose output (none:error, once:info, twice or more:debug)",
        action="count"))
    store_actions.append(parser.add_argument(
        "-w", "--wine",
        help="""start the game with Wine
                [Default on other systems if neither Proton or Wine are specified]""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "-x", "--prefixdir", metavar="DIR", type=str,
        help="""choose a different directory for the prefix
                [Default: $XDG_DATA_HOME/truckersmp-cli/(Game name)/prefix]"""))
    store_actions.append(parser.add_argument(
        "--activate-native-d3dcompiler-47",
        help="""activate native 64-bit d3dcompiler_47.dll when starting
                (Needed for D3D11 renderer)""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--check-windows-steam",
        help="""check for the Windows Steam version on updating when using Proton""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--disable-proton-overlay",
        help="disable Steam Overlay when using Proton",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--downgrade",
        help="""**DEPRECATED** downgrade to the latest version supported by TruckersMP
                Note: This option implies "--update" option and
                is ignored if "--beta" ("-b") option is specified""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--game-options", metavar="OPTIONS", type=str,
        default="-nointro -64bit",
        help="""specify ATS/ETS2 options
                Note: If specifying one option, use "--game-options=-option" format
                [Default: "-nointro -64bit"]"""))
    store_actions.append(parser.add_argument(
        "--native-steam-dir", metavar="DIR", type=str,
        default="auto",
        help="""choose native Steam installation,
                useful only if your Steam directory is not detected automatically
                [Default: "auto"]"""))
    store_actions.append(parser.add_argument(
        "--self-update",
        help="""update files to the latest release and quit
                Note: Python package users should use pip instead""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--singleplayer",
        help="""**DEPRECATED** start singleplayer game, useful for save editing,
                using/testing DXVK in singleplayer, etc.""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--skip-update-proton",
        help="""skip updating already-installed Proton and Steam Runtime
                when updating game with Proton enabled""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--use-wined3d",
        help="use OpenGL-based D3D11 instead of DXVK when using Proton",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--xdg-runtime-dir", metavar="DIR",
        help="use custom XDG_RUNTIME_DIR for Discord IPC sockets"))
    store_actions.append(parser.add_argument(
        "--wine-desktop", metavar="SIZE", type=str,
        help="""use Wine desktop, work around missing TruckerMP overlay
                after tabbing out using DXVK, mouse clicking won't work
                in other GUI apps while the game is running, SIZE must be
                'WIDTHxHEIGHT' format (e.g. 1920x1080)"""))
    store_actions.append(parser.add_argument(
        "--wine-steam-dir", metavar="DIR", type=str,
        help="""choose a directory for Windows version of Steam
                [Default: "C:\\Program Files (x86)\\Steam" in the prefix]"""))
    store_actions.append(parser.add_argument(
        "--without-steam-runtime",
        help="""don't use Steam Runtime even when using Proton 5.13 or newer
                Note: If you want to use Discord Rich Presence
                without this option, you need to start Discord with
                "XDG_RUNTIME_DIR=/path/to/dir" beforehand
                and also specify "--xdg-runtime-dir" option""",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--without-wine-discord-ipc-bridge",
        help="don't use wine-discord-ipc-bridge for Discord Rich Presence",
        action="store_true"))
    store_actions.append(parser.add_argument(
        "--version",
        help="""print version information and quit""",
        action="store_true"))
    group_action_desc = "choose an action"
    for name, desc in ACTIONS:
        group_action_desc += "\n  {:17} : {}".format(name, desc)
    group_action = parser.add_argument_group("action", group_action_desc)
    group_action.add_argument(
        "action",
        # currently we can't set the default value because it may change
        # values from deprecated options
        # when we drop the options we need to
        # set default="updateandstart" and remove "none"
        choices=[act[0] for act in ACTIONS] + ["none", ],
        default="none",
        nargs="?")
    group_game_desc = "choose a game"
    for name, desc in GAMES:
        group_game_desc += "\n  {:6} : {}".format(name, desc)
    group_game = parser.add_argument_group("game", group_game_desc)
    group_game.add_argument(
        "game",
        # similarly, when we drop deprecated options we need to
        # set default="ets2mp" and remove "none"
        choices=[game[0] for game in GAMES] + ["none", ],
        default="none",
        nargs="?")

    return parser, store_actions

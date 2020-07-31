"""
steamcmd handler for truckersmp-cli main script.

Licensed under MIT.
"""

import io
import logging
import os
import platform
import subprocess as subproc
import sys
import tarfile
import urllib.parse
import urllib.request
from zipfile import ZipFile

from .truckersmp import get_beta_branch_name
from .utils import check_steam_process
from .variables import Dir, URL


def update_game(args):
    """
    Update game and Proton via SteamCMD.

    We make sure Steam is closed before updating.
    On Linux, we make sure both Windows and Linux version of Steam are closed.
    It's possible to update with the Steam client open but the client looses
    all connectivity and asks for password and Steam Guard code after restart.

    When "--wine" is specified, this function retrieves/uses Windows version of
    SteamCMD. When "--proton" is specified, this retrieves/uses
    Linux version of SteamCMD.
    """
    steamcmd_prolog = ""
    steamcmd_cmd = []

    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"
    env["WINEARCH"] = "win64"
    env_steam = env.copy()
    if args.proton:
        # Proton's "prefix" is for STEAM_COMPAT_DATA_PATH that contains
        # the directory "pfx" for WINEPREFIX
        env_steam["WINEPREFIX"] = os.path.join(args.prefixdir, "pfx")
    else:
        env_steam["WINEPREFIX"] = args.prefixdir
    # use a prefix only for SteamCMD to avoid every-time authentication
    env["WINEPREFIX"] = Dir.steamcmdpfx
    # don't show "The Wine configuration is being updated" dialog
    # or install Gecko/Mono
    env["WINEDLLOVERRIDES"] = "winex11.drv="

    wine = env["WINE"] if "WINE" in env else "wine"
    os.makedirs(Dir.steamcmdpfx, exist_ok=True)
    try:
        subproc.check_call((wine, "--version"), stdout=subproc.DEVNULL, env=env)
        logging.debug("Wine ({}) is available".format(wine))
    except subproc.CalledProcessError:
        logging.debug("Wine is not available")
        wine = None
    if args.proton:
        # we don't use system SteamCMD because something goes wrong in some cases
        # see https://github.com/lhark/truckersmp-cli/issues/43
        steamcmd = os.path.join(Dir.steamcmddir, "steamcmd.sh")
        steamcmd_url = URL.steamcmdlnx
        gamedir = args.gamedir
    else:
        if not wine:
            sys.exit("Wine ({}) is not available.".format(wine))
        steamcmd_prolog += """WINEDEBUG=-all
  WINEARCH=win64
  WINEPREFIX={}
  WINEDLLOVERRIDES=winex11.drv=
  {} """.format(Dir.steamcmdpfx, wine)

        # steamcmd.exe uses Windows path, not UNIX path
        try:
            gamedir = subproc.check_output(
              (wine, "winepath", "-w", args.gamedir), env=env).decode("utf-8").rstrip()
        except Exception as e:
            sys.exit(
              "Failed to convert game directory to Windows path: {}".format(e))

        steamcmd = os.path.join(Dir.steamcmddir, "steamcmd.exe")
        steamcmd_cmd.append(wine)
        steamcmd_url = URL.steamcmdwin
    steamcmd_cmd.append(steamcmd)

    # fetch SteamCMD if not in our data directory
    os.makedirs(Dir.steamcmddir, exist_ok=True)
    if not os.path.isfile(steamcmd):
        logging.debug("Retrieving SteamCMD")
        try:
            with urllib.request.urlopen(steamcmd_url) as f:
                steamcmd_archive = f.read()
        except Exception as e:
            sys.exit("Failed to retrieve SteamCMD: {}".format(e))
        logging.debug("Extracting SteamCMD")
        try:
            if args.proton:
                with tarfile.open(
                  fileobj=io.BytesIO(steamcmd_archive), mode="r:gz") as f:
                    f.extractall(Dir.steamcmddir)
            else:
                with ZipFile(io.BytesIO(steamcmd_archive)) as f:
                    with f.open("steamcmd.exe") as f_exe:
                        with open(steamcmd, "wb") as f_out:
                            f_out.write(f_exe.read())
        except Exception as e:
            sys.exit("Failed to extract SteamCMD: {}".format(e))

    logging.info("SteamCMD: " + steamcmd)

    # Linux version of Steam
    if platform.system() == "Linux" and check_steam_process(use_proton=True):
        logging.debug("Closing Linux version of Steam")
        subproc.call(("steam", "-shutdown"))
    # Windows version of Steam
    if wine and check_steam_process(use_proton=False, wine=wine, env=env_steam):
        logging.debug("Closing Windows version of Steam in " + args.wine_steam_dir)
        subproc.call(
          (wine, os.path.join(args.wine_steam_dir, "steam.exe"), "-shutdown"),
          env=env_steam)

    if args.proton:
        # download/update Proton
        os.makedirs(args.protondir, exist_ok=True)
        logging.debug("Updating Proton (AppID:{})".format(args.proton_appid))
        logging.info("""Command:
  {}
    +login {}
    +force_install_dir {}
    +app_update {} validate
    +quit""".format(steamcmd, args.account, args.protondir, args.proton_appid))
        try:
            subproc.check_call(
              (steamcmd,
               "+login", args.account,
               "+force_install_dir", args.protondir,
               "+app_update", str(args.proton_appid), "validate",
               "+quit"))
        except subproc.CalledProcessError:
            sys.exit("SteamCMD exited abnormally")

    # determine game branch
    branch = "public"
    if args.beta:
        branch = args.beta
    else:
        game = "ats" if args.ats else "ets2"
        beta_branch_name = get_beta_branch_name(game)
        if beta_branch_name:
            branch = beta_branch_name
    logging.info("Game branch: " + branch)

    # use SteamCMD to update the chosen game
    os.makedirs(args.gamedir, exist_ok=True)
    logging.debug("Updating Game (AppID:{})".format(args.steamid))
    logging.info("""Command:
  {}{}
    +@sSteamCmdForcePlatformType windows
    +login {}
    +force_install_dir {}
    +app_update {} -beta {} validate
    +quit""".format(
      steamcmd_prolog, steamcmd, args.account, gamedir, args.steamid, branch))
    steamcmd_args = [
        "+@sSteamCmdForcePlatformType", "windows",
        "+login", args.account,
        "+force_install_dir", gamedir,
        "+app_update", args.steamid,
        "-beta", branch,
        "validate",
        "+quit",
    ]
    try:
        subproc.check_call(steamcmd_cmd + steamcmd_args, env=env)
    except subproc.CalledProcessError:
        sys.exit("SteamCMD exited abnormally")
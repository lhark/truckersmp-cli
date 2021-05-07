"""
SteamCMD handler for truckersmp-cli main script.

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

from .truckersmp import determine_game_branch
from .utils import check_steam_process
from .variables import AppId, Args, Dir, URL


class SteamCMD:
    """SteamCMD command."""

    # pylint: disable=too-few-public-methods

    def __init__(self, path, wine=None, env=None):
        """
        Initialize SteamCMD object.

        path: Path to "steamcmd.sh" or "steamcmd.exe"
        wine: Path to "wine" command (can be None when native SteamCMD is used)
        env: "env" argument for subprocess.Popen
        """
        self._path = path
        self._wine = wine
        self._env = env

    def run(self, args):
        """
        Run SteamCMD using given command line.

        When it fails, sys.exit() is called and the program exits abnormally.
        args: SteamCMD arguments (list)
        """
        cmdline = []
        if self._wine is not None:
            cmdline.append(self._wine)
        cmdline.append(self._path)
        cmdline += args
        env_str = ""
        if self._env is not None:
            env_print = ("WINEDEBUG", "WINEARCH", "WINEPREFIX", "WINEDLLOVERRIDES")
            name_value_pairs = []
            for name in env_print:
                name_value_pairs.append("{}={}".format(name, self._env[name]))
            env_str += "\n  ".join(name_value_pairs) + "\n  "
        cmd_str = ""
        for i, arg in enumerate(cmdline):
            if arg.startswith("+"):
                # add newline before SteamCMD commands (e.g. "+login")
                cmd_str += "\n    "
            elif i > 0:
                cmd_str += " "
            cmd_str += arg
        logging.info("Running SteamCMD:\n  %s%s", env_str, cmd_str)

        try:
            subproc.check_call(cmdline, env=self._env)
        except subproc.CalledProcessError:
            sys.exit("SteamCMD exited abnormally")


def update_game():
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
    # pylint: disable=too-many-branches,too-many-locals,too-many-statements

    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"
    env["WINEARCH"] = "win64"
    env_steam = env.copy()
    if Args.proton:
        # Proton's "prefix" is for STEAM_COMPAT_DATA_PATH that contains
        # the directory "pfx" for WINEPREFIX
        env_steam["WINEPREFIX"] = os.path.join(Args.prefixdir, "pfx")
    else:
        env_steam["WINEPREFIX"] = Args.prefixdir
    # use a prefix only for SteamCMD to avoid every-time authentication
    env["WINEPREFIX"] = Dir.steamcmdpfx
    # don't show "The Wine configuration is being updated" dialog
    # or install Gecko/Mono
    env["WINEDLLOVERRIDES"] = "winex11.drv="

    wine = env["WINE"] if "WINE" in env else "wine"
    os.makedirs(Dir.steamcmdpfx, exist_ok=True)
    if Args.check_windows_steam:
        try:
            subproc.check_call((wine, "--version"), stdout=subproc.DEVNULL, env=env)
            logging.debug("Wine (%s) is available", wine)
        except subproc.CalledProcessError:
            logging.debug("Wine is not available")
            wine = None
    if Args.proton:
        # we don't use system SteamCMD because something goes wrong in some cases
        # see https://github.com/truckersmp-cli/truckersmp-cli/issues/43
        steamcmd_path = os.path.join(Dir.steamcmddir, "steamcmd.sh")
        steamcmd_url = URL.steamcmdlnx
        gamedir = Args.gamedir
    else:
        if not wine:
            sys.exit("Wine ({}) is not available.".format(wine))

        # steamcmd.exe uses Windows path, not UNIX path
        try:
            gamedir = subproc.check_output(
                (wine, "winepath", "-w", Args.gamedir), env=env).decode("utf-8").rstrip()
        except (OSError, subproc.CalledProcessError) as ex:
            sys.exit(
                "Failed to convert game directory to Windows path: {}".format(ex))

        steamcmd_path = os.path.join(Dir.steamcmddir, "steamcmd.exe")
        steamcmd_url = URL.steamcmdwin

    # fetch SteamCMD if not in our data directory
    os.makedirs(Dir.steamcmddir, exist_ok=True)
    if not os.path.isfile(steamcmd_path):
        logging.debug("Retrieving SteamCMD")
        try:
            with urllib.request.urlopen(steamcmd_url) as f_in:
                steamcmd_archive = f_in.read()
        except OSError as ex:
            sys.exit("Failed to retrieve SteamCMD: {}".format(ex))
        logging.debug("Extracting SteamCMD")
        try:
            if Args.proton:
                with tarfile.open(
                        fileobj=io.BytesIO(steamcmd_archive), mode="r:gz") as f_in:
                    f_in.extractall(Dir.steamcmddir)
            else:
                with ZipFile(io.BytesIO(steamcmd_archive)) as f_in:
                    with f_in.open("steamcmd.exe") as f_exe:
                        with open(steamcmd_path, "wb") as f_out:
                            f_out.write(f_exe.read())
        except (OSError, tarfile.TarError) as ex:
            sys.exit("Failed to extract SteamCMD: {}".format(ex))

    logging.info("SteamCMD: %s", steamcmd_path)

    # Linux version of Steam
    if platform.system() == "Linux" and check_steam_process(use_proton=True):
        logging.debug("Closing Linux version of Steam")
        subproc.call(("steam", "-shutdown"))
    # Windows version of Steam
    if (Args.check_windows_steam
            and wine
            and check_steam_process(use_proton=False, wine=wine, env=env_steam)):
        logging.debug("Closing Windows version of Steam in %s", Args.wine_steam_dir)
        subproc.call(
            (wine, os.path.join(Args.wine_steam_dir, "steam.exe"), "-shutdown"),
            env=env_steam)

    steamcmd = SteamCMD(
        steamcmd_path,
        wine=wine if not Args.proton else None,
        env=env if not Args.proton else None,
    )

    if Args.proton:
        if Args.skip_update_proton:
            logging.info("Skipping updating Proton and Steam Runtime")
        else:
            if not Args.without_steam_runtime:
                # download/update Steam Runtime and Proton
                os.makedirs(Args.steamruntimedir, exist_ok=True)
                # Proton and Steam Linux Runtime work only on Linux systems
                appid_steamruntime = AppId.steamruntime["Linux"]
                logging.debug("Updating Steam Runtime (AppID:%s)", appid_steamruntime)
                steamcmd.run(
                    [
                        "+login", Args.account,
                        "+force_install_dir", Args.steamruntimedir,
                        "+app_update", str(appid_steamruntime), "validate",
                        "+quit",
                    ]
                )
            os.makedirs(Args.protondir, exist_ok=True)
            logging.debug("Updating Proton (AppID:%s)", Args.proton_appid)
            steamcmd.run(
                [
                    "+login", Args.account,
                    "+force_install_dir", Args.protondir,
                    "+app_update", str(Args.proton_appid), "validate",
                    "+quit",
                ]
            )

    # determine game branch
    branch = determine_game_branch()
    logging.info("Game branch: %s", branch)

    # use SteamCMD to update the chosen game
    os.makedirs(Args.gamedir, exist_ok=True)
    logging.debug("Updating Game (AppID:%s)", Args.steamid)
    steamcmd.run(
        [
            "+@sSteamCmdForcePlatformType", "windows",
            "+login", Args.account,
            "+force_install_dir", gamedir,
            "+app_update", Args.steamid,
            "-beta", branch,
            "validate",
            "+quit",
        ]
    )

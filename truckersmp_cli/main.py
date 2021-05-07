"""
Main module for truckersmp-cli main script.

Licensed under MIT.
"""

import json
import logging
import os
import signal
import subprocess as subproc
import sys

from .args import check_args_errors, create_arg_parser
from .steamcmd import update_game
from .truckersmp import update_mod
from .utils import (
    activate_native_d3dcompiler_47, check_libsdl2, get_proton_version,
    perform_self_update, set_wine_desktop_registry,
    setup_wine_discord_ipc_bridge, wait_for_steam,
)
from .variables import AppId, Args, Dir, File, URL

PKG_RESOURCES_IS_AVAILABLE = False
try:
    import pkg_resources
    PKG_RESOURCES_IS_AVAILABLE = True
except ImportError:
    pass


def get_version_string():
    """
    Get the version of this program and return it in string format.

    This first tries to load "RELEASE" file
    for GitHub release assets or cloned git repo directory.
    If succeeded, it additionally tries to get git commit hash and append it.
    Otherwise, it tries to get version from Python package
    only when "pkg_resources" module is available.
    If the version is still unknown, this returns "unknown".
    """
    version = ""
    try:
        # try to load "RELEASE" file for release assets or cloned git directory
        with open(os.path.join(os.path.dirname(Dir.scriptdir), "RELEASE")) as f_in:
            version += f_in.readline().rstrip()
    except OSError:
        pass
    if version:
        try:
            # try to get git commit hash, and append it if succeeded
            version += subproc.check_output(
                ("git", "log", "-1", "--format= (%h)")).decode("utf-8").rstrip()
        except (OSError, subproc.CalledProcessError):
            pass
    else:
        # try to get version from Python package
        try:
            if PKG_RESOURCES_IS_AVAILABLE:
                version += pkg_resources.get_distribution(__package__).version
        except pkg_resources.DistributionNotFound:
            pass
    return version if version else "unknown"


def main():
    """truckersmp-cli main function."""
    # pylint: disable=too-many-branches,too-many-statements
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # load Proton AppID info from "proton.json":
    #     {"X.Y": AppID, ... , "default": "X.Y"}
    # example:
    #     {"5.0": 1245040, "4.11": 1113280, "default": "5.0"}
    try:
        with open(File.proton_json) as f_in:
            AppId.proton = json.load(f_in)
    except (OSError, ValueError) as ex:
        sys.exit("Failed to load proton.json: {}".format(ex))

    # load Steam Runtime AppID info from "steamruntime.json":
    #     {"platform": AppID, ... }
    # example:
    #     {"Linux": 1391110}
    try:
        with open(File.steamruntime_json) as f_in:
            AppId.steamruntime = json.load(f_in)
    except (OSError, ValueError) as ex:
        sys.exit("Failed to load steamruntime.json: {}".format(ex))

    # parse options
    arg_parser = create_arg_parser()[0]
    arg_parser.parse_args(namespace=Args)

    # print version
    if Args.version:
        print(get_version_string())
        sys.exit()

    # check whether the executable of our inject program is present
    if not os.access(File.inject_exe, os.R_OK):
        sys.exit("""DLL inject program ("{}") is missing.

Try one of the following:
* Install truckersmp-cli via pip [RECOMMENDED]
  (e.g. "python3 -m pip install --user truckersmp-cli[optional]")
  and run it (e.g. "~/.local/bin/truckersmp-cli [ARGUMENTS...]")
* Download GitHub release file from "{}", unpack it, and run
  the "truckersmp-cli" script in the unpacked directory
* Build "truckersmp-cli.exe" with mingw-w64, put it into "{}",
  and run this script again

See {} for additional information.""".format(
            File.inject_exe, URL.project_releases, Dir.scriptdir, URL.project_doc_inst))

    # set up logging
    setup_logging()

    # self update
    if Args.self_update:
        perform_self_update()
        sys.exit()

    # fallback to old local folder
    if not Args.moddir:
        old_local_moddir = os.path.join(Dir.scriptdir, "truckersmp")
        if (os.path.isdir(old_local_moddir)
                and os.access(old_local_moddir, os.R_OK | os.W_OK | os.X_OK)):
            logging.debug("No moddir set and fallback found")
            Args.moddir = old_local_moddir
        else:
            logging.debug("No moddir set, setting to default")
            Args.moddir = Dir.default_moddir
    logging.info("Mod directory: %s", Args.moddir)

    # check for errors
    check_args_errors()

    # download/update ATS/ETS2 and Proton
    if Args.update:
        logging.debug("Updating game files")
        update_game()

    # update truckersmp when starting multiplayer
    if not Args.singleplayer:
        logging.debug("Updating mod files")
        update_mod()

    # start truckersmp with proton or wine
    if Args.start:
        if Args.proton:
            # check for Proton availability when starting with Proton
            if not os.access(os.path.join(Args.protondir, "proton"), os.R_OK):
                sys.exit("""Proton is not found in {}
Run with '--update' option to install Proton""".format(Args.protondir))
            # check for Steam Runtime availability and the permission of "var"
            # when starting with Proton + Steam Runtime
            run = os.path.join(Args.steamruntimedir, "run")
            var = os.path.join(Args.steamruntimedir, "var")
            if not Args.without_steam_runtime:
                if not os.access(run, os.R_OK | os.X_OK):
                    sys.exit("""Steam Runtime is not found in {}
Update game with '--use-steam-runtime' option to install Steam Runtime""".format(
                             Args.steamruntimedir))
                if not os.access(var, os.R_OK | os.W_OK | os.X_OK):
                    sys.exit("""The "var" directory in Steam Runtime
({}) must be writable""".format(var))

        if not check_libsdl2():
            sys.exit("SDL2 was not found on your system.")
        start_functions = (("Proton", start_with_proton), ("Wine", start_with_wine))
        i = 0 if Args.proton else 1
        compat_tool, start_game = start_functions[i]
        logging.debug("Starting game with %s", compat_tool)
        start_game()

    sys.exit()


def setup_logging():
    """
    Set up Python logging facility.

    This function must be called after parse_args().
    """
    formatter = logging.Formatter("** {levelname} **  {message}", style="{")
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    logger = logging.getLogger()
    if Args.verbose:
        logger.setLevel(logging.INFO if Args.verbose == 1 else logging.DEBUG)
    logger.addHandler(stderr_handler)
    if Args.logfile != "":
        file_handler = logging.FileHandler(Args.logfile, mode="w")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def start_with_proton():
    """Start game with Proton."""
    # pylint: disable=consider-using-with,too-many-branches
    # pylint: disable=too-many-locals,too-many-statements
    steamdir = wait_for_steam(use_proton=True, loginvdf_paths=File.loginusers_paths)
    logging.info("Steam installation directory: %s", steamdir)

    logging.debug("Creating directory %s if it doesn't exist", Args.prefixdir)
    os.makedirs(Args.prefixdir, exist_ok=True)

    prefix = os.path.join(Args.prefixdir, "pfx")
    proton = os.path.join(Args.protondir, "proton")
    (major, minor) = get_proton_version(Args.protondir)
    logging.info("Proton version is (major=%d, minor=%d)", major, minor)
    proton_args = []
    run_in_steamrt = []
    if not Args.without_steam_runtime and (major >= 6 or (major == 5 and minor >= 13)):
        # use Steam Runtime container for Proton 5.13+
        logging.info("Using Steam Runtime container")
        # share directories with Steam Runtime container
        shared_dirs = [
            Args.gamedir,
            Args.protondir,
            Args.prefixdir,
        ]
        if not Args.singleplayer:
            shared_dirs += [
                Args.moddir,
                Dir.truckersmp_cli_data,
                Dir.scriptdir,
            ]
        if Args.xdg_runtime_dir:
            shared_dirs.append(Args.xdg_runtime_dir)
        logging.debug("Shared directories: %s", shared_dirs)
        run_in_steamrt.append(os.path.join(Args.steamruntimedir, "run"))
        for shared_dir in shared_dirs:
            run_in_steamrt += ["--filesystem", shared_dir]
        run_in_steamrt += ["--", "python3"]  # helper script
        proton_args += ["--", "python3"]     # Proton script
        wine = run_in_steamrt.copy()
    else:
        # don't use Steam Runtime container for older Proton
        logging.info("Not using Steam Runtime container")
        run_in_steamrt.append(sys.executable)  # helper
        proton_args += ["--", sys.executable]  # Proton
        wine = []
    proton_args += [proton, "run"]

    env = os.environ.copy()
    env["STEAM_COMPAT_DATA_PATH"] = Args.prefixdir
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = steamdir

    # Proton's "dist" directory tree is missing until first run
    # make sure it's present for using "dist/bin/wine" directly
    wine_command = os.path.join(Args.protondir, "dist/bin/wine")
    wine.append(wine_command)
    if (not os.access(wine_command, os.R_OK)
            # native d3dcompiler_47 is removed when the prefix is downgraded
            # make sure the prefix is already upgraded/downgraded
            or Args.activate_native_d3dcompiler_47):
        try:
            subproc.check_output(
                proton_args + ["wineboot", ], env=env, stderr=subproc.STDOUT)
        except OSError as ex:
            sys.exit("Failed to run wineboot: {}".format(ex))
        except subproc.CalledProcessError as ex:
            sys.exit("wineboot failed:\n{}".format(ex.output.decode("utf-8")))

    # activate native d3dcompiler_47
    if Args.activate_native_d3dcompiler_47:
        activate_native_d3dcompiler_47(prefix, wine)

    # enable Wine desktop if requested
    if Args.wine_desktop:
        set_wine_desktop_registry(prefix, wine, True)

    env["PROTON_USE_WINED3D"] = "1" if Args.use_wined3d else "0"
    env["PROTON_NO_D3D11"] = "1" if not Args.enable_d3d11 else "0"
    # enable Steam Overlay unless "--disable-proton-overlay" is specified
    if not Args.disable_proton_overlay:
        overlayrenderer = os.path.join(steamdir, File.overlayrenderer_inner)
        if "LD_PRELOAD" in env:
            env["LD_PRELOAD"] += ":" + overlayrenderer
        else:
            env["LD_PRELOAD"] = overlayrenderer

    # check whether singleplayer or multiplayer
    if Args.singleplayer:
        exename = "eurotrucks2.exe" if Args.ets2 else "amtrucks.exe"
        gamepath = os.path.join(Args.gamedir, "bin/win_x64", exename)
        proton_args.append(gamepath)
    else:
        proton_args += File.inject_exe, Args.gamedir, Args.moddir

    # game options
    for opt in Args.game_options.split(" "):
        if opt != "":
            proton_args.append(opt)

    env["SteamGameId"] = Args.steamid
    env["SteamAppId"] = Args.steamid
    env_print = ["SteamAppId", "SteamGameId"]
    if "LD_PRELOAD" in env:
        env_print.append("LD_PRELOAD")
    env_print += [
        "PROTON_NO_D3D11",
        "PROTON_USE_WINED3D",
        "STEAM_COMPAT_CLIENT_INSTALL_PATH",
        "STEAM_COMPAT_DATA_PATH",
    ]

    argv_helper = run_in_steamrt
    argv_helper.append(File.steamruntime_helper)
    if not Args.singleplayer and not Args.without_wine_discord_ipc_bridge:
        argv_helper += ["--executable", File.ipcbridge]
    if Args.xdg_runtime_dir:
        argv_helper += ["--xdg-runtime-dir", Args.xdg_runtime_dir]
    if Args.verbose:
        argv_helper.append("-v" if Args.verbose == 1 else "-vv")
    argv_helper += proton_args

    env_str = ""
    cmd_str = ""
    name_value_pairs = []
    for name in env_print:
        name_value_pairs.append("{}={}".format(name, env[name]))
    env_str += "\n  ".join(name_value_pairs) + "\n  "
    cmd_str += "\n    ".join(proton_args)
    logging.info("Running Steam Runtime helper:\n  %s%s", env_str, cmd_str)
    try:
        with subproc.Popen(
                argv_helper,
                env=env, stdout=subproc.PIPE, stderr=subproc.STDOUT) as proc:
            if Args.verbose and Args.verbose >= 1:
                for line in proc.stdout:
                    print(line.decode("utf-8"), end="")
    except subproc.CalledProcessError as ex:
        logging.error(
            "Steam Runtime helper exited abnormally:\n%s", ex.output.decode("utf-8"))

    # disable Wine desktop if enabled
    if Args.wine_desktop:
        set_wine_desktop_registry(prefix, wine, False)


def start_with_wine():
    """Start game with Wine."""
    # pylint: disable=consider-using-with,too-many-branches
    wine = os.environ["WINE"] if "WINE" in os.environ else "wine"
    argv = [wine, ]
    if Args.activate_native_d3dcompiler_47:
        activate_native_d3dcompiler_47(Args.prefixdir, argv)

    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"
    env["WINEARCH"] = "win64"
    env["WINEPREFIX"] = Args.prefixdir

    wait_for_steam(
        use_proton=False,
        loginvdf_paths=(os.path.join(Args.wine_steam_dir, File.loginvdf_inner), ),
        wine=wine,
        env=env,
    )

    ipcbr_proc = None
    if not Args.singleplayer and not Args.without_wine_discord_ipc_bridge:
        ipcbr_path = setup_wine_discord_ipc_bridge()
        logging.info("Starting wine-discord-ipc-bridge")
        ipcbr_proc = subproc.Popen(
            argv + [ipcbr_path, ],
            env=env, stdout=subproc.DEVNULL, stderr=subproc.DEVNULL)

    if "WINEDLLOVERRIDES" not in env:
        env["WINEDLLOVERRIDES"] = ""
    if not Args.enable_d3d11:
        env["WINEDLLOVERRIDES"] += ";d3d11=;dxgi="

    if Args.wine_desktop:
        argv += "explorer", "/desktop=TruckersMP,{}".format(Args.wine_desktop)
    if Args.singleplayer:
        exename = "eurotrucks2.exe" if Args.ets2 else "amtrucks.exe"
        gamepath = os.path.join(Args.gamedir, "bin/win_x64", exename)
        argv.append(gamepath)
    else:
        argv += File.inject_exe, Args.gamedir, Args.moddir

    for opt in Args.game_options.split(" "):
        if opt != "":
            argv.append(opt)

    env_str = ""
    cmd_str = ""
    name_value_pairs = []
    for name in ("WINEARCH", "WINEDEBUG", "WINEDLLOVERRIDES", "WINEPREFIX"):
        name_value_pairs.append("{}={}".format(name, env[name]))
    env_str += "\n  ".join(name_value_pairs) + "\n  "
    cmd_str += "\n    ".join(argv)
    logging.info("Running Wine:\n  %s%s", env_str, cmd_str)
    try:
        output = subproc.check_output(argv, env=env, stderr=subproc.STDOUT)
        logging.info("Wine output:\n%s", output.decode("utf-8"))
    except subproc.CalledProcessError as ex:
        logging.error("Wine output:\n%s", ex.output.decode("utf-8"))

    if ipcbr_proc:
        if ipcbr_proc.poll() is None:
            ipcbr_proc.kill()
        ipcbr_proc.wait()

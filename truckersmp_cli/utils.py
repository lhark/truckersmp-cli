"""
Utilities for truckersmp-cli main script.

Licensed under MIT.
"""

import ctypes
import hashlib
import http.client
import io
import logging
import os
import platform
import shutil
import subprocess as subproc
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from getpass import getuser
from gettext import ngettext

from .variables import Args, Dir, File, URL

VDF_IS_AVAILABLE = False
try:
    import vdf
    VDF_IS_AVAILABLE = True
except ImportError:
    pass


def activate_native_d3dcompiler_47(prefix, wine):
    """
    Download/activate native 64-bit version of d3dcompiler_47.

    wine: A list used to run Wine executable
    """
    # check whether DLL is already downloaded
    need_download = True
    try:
        if check_hash(File.d3dcompiler_47, File.d3dcompiler_47_md5, hashlib.md5()):
            logging.debug("d3dcompiler_47.dll is present, MD5 is OK.")
            need_download = False
    except OSError:
        pass

    # download 64-bit d3dcompiler_47.dll from ImagingSIMS' repo
    # https://github.com/ImagingSIMS/ImagingSIMS
    if need_download:
        logging.debug("Downloading d3dcompiler_47.dll")
        os.makedirs(Dir.dllsdir, exist_ok=True)
        if not download_files(
                URL.github,
                [(URL.d3dcompilerpath, File.d3dcompiler_47, File.d3dcompiler_47_md5), ]):
            sys.exit("Failed to download d3dcompiler_47.dll")

    # copy into system32
    destdir = os.path.join(prefix, "drive_c/windows/system32")
    logging.debug("Copying d3dcompiler_47.dll into %s", destdir)
    shutil.copy(File.d3dcompiler_47, destdir)

    # add DLL override setting
    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"
    env["WINEPREFIX"] = prefix
    if Args.proton:
        env["WINEESYNC"] = "0" if is_envar_enabled(env, "PROTON_NO_ESYNC") else "1"
    exename = "eurotrucks2.exe" if Args.ets2 else "amtrucks.exe"
    logging.debug("Adding DLL override setting for %s", exename)
    subproc.call(
        wine + [
            "reg", "add",
            "HKCU\\Software\\Wine\\AppDefaults\\{}\\DllOverrides".format(exename),
            "/v", "d3dcompiler_47", "/t", "REG_SZ", "/d", "native", "/f"],
        env=env)


def check_hash(path, digest, hashobj):
    """
    Compare given digest and calculated one.

    This returns True if the two digests match.
    Otherwise this returns False.

    path: Path to the input file
    digest: Expected hex digest string
    hashobj: hashlib object (e.g. hashlib.md5())
    """
    with open(path, "rb") as f_in:
        while True:
            buf = f_in.read(hashobj.block_size * 4096)
            if not buf:
                break
            hashobj.update(buf)
    return hashobj.hexdigest() == digest


def check_libsdl2():
    """
    Check whether SDL2 shared object file is present.

    If SDL2 is detected, this function returns True.
    Otherwise, this returns False.

    Currently the check is done only on Linux systems.
    """
    if platform.system() != "Linux":
        return True

    try:
        ctypes.cdll.LoadLibrary(File.sdl2_soname)
        return True
    except OSError:
        return False


def check_steam_process(use_proton, wine=None, env=None):
    """
    Check whether Steam client is already running.

    If Steam is running, this function returns True.
    Otherwise this returns False.

    use_proton: True if Proton is used, False if Wine is used
    wine: Wine command (path or name)
         (can be None if use_proton is True)
    env: A dictionary that contains environment variables
         (can be None if use_proton is True)
    """
    if use_proton:
        try:
            subproc.check_call(
                ("pgrep", "-u", getuser(), "-x", "steam"), stdout=subproc.DEVNULL)
            return True
        except (OSError, subproc.CalledProcessError):
            return False
    else:
        steam_is_running = False
        argv = (wine, "winedbg", "--command", "info process")
        env_wine = env.copy()
        env_wine["WINEDLLOVERRIDES"] = "winex11.drv="
        if "WINEPREFIX" in env_wine:
            os.makedirs(env_wine["WINEPREFIX"], exist_ok=True)
        try:
            output = subproc.check_output(argv, env=env_wine, stderr=subproc.DEVNULL)
            for line in output.decode("utf-8").splitlines():
                line = line[:-1]  # strip last "'" for rindex()
                try:
                    exename = line[line.rindex("'") + 1:]
                except ValueError:
                    continue
                if exename.lower().endswith("steam.exe"):
                    steam_is_running = True
                    break
        except (OSError, subproc.CalledProcessError) as ex:
            sys.exit("Failed to get Wine process list: " + ex.output.decode("utf-8"))
        return steam_is_running


def download_files(host, files_to_download, progress_count=None):
    """Download files."""
    # pylint: disable=too-many-branches,too-many-locals,too-many-statements

    file_count = progress_count[0] if progress_count else 1
    num_of_files = progress_count[1] if progress_count else len(files_to_download)
    conn = http.client.HTTPSConnection(host)
    try:
        while len(files_to_download) > 0:
            path, dest, md5 = files_to_download[0]
            md5hash = hashlib.md5()
            bufsize = md5hash.block_size * 256
            name = os.path.basename(dest)
            destdir = os.path.dirname(dest)
            name_getting = "[{}/{}] Get: {}".format(file_count, num_of_files, name)
            if len(name) >= 67:
                name = name[:63] + "..."
            if len(name_getting) >= 49:
                name_getting = name_getting[:45] + "..."
            logging.debug(
                "Downloading file https://%s%s to %s", host, path, destdir)

            # make file hierarchy
            os.makedirs(destdir, exist_ok=True)

            # download file
            conn.request("GET", path, headers={"Connection": "keep-alive"})
            res = conn.getresponse()

            if (res.status == 301
                    or res.status == 302
                    or res.status == 303
                    or res.status == 307
                    or res.status == 308):
                # HTTP redirection
                newloc = urllib.parse.urlparse(res.getheader("Location"))
                newpath = newloc.path
                if len(newloc.query) > 0:
                    newpath += "?" + newloc.query
                if not download_files(
                        newloc.netloc,
                        [(newpath, dest, md5), ],
                        (file_count, num_of_files)):
                    return False
                # downloaded successfully from redirected URL
                del files_to_download[0]
                file_count += 1
                conn = http.client.HTTPSConnection(host)
                continue
            if res.status != 200:
                logging.error(
                    "Server %s responded with status code %s.", host, res.status)
                return False

            lastmod = res.getheader("Last-Modified")
            content_len = res.getheader("Content-Length")

            with open(dest, "wb") as f_out:
                downloaded = 0
                while True:
                    buf = res.read(bufsize)
                    if not buf:
                        break
                    downloaded += len(buf)
                    f_out.write(buf)
                    md5hash.update(buf)
                    if content_len:
                        int_content_len = int(content_len)
                        ten_percent_count = int(downloaded * 10 / int_content_len)
                        # downloaded / length [progressbar]
                        # e.g. 555.5K / 777.7K [=======>  ]
                        progress = "{} / {} [{}{}{}]".format(
                            get_short_size(downloaded),
                            get_short_size(int_content_len),
                            "=" * ten_percent_count,
                            ">" if ten_percent_count < 10 else "",
                            " " * max(9 - ten_percent_count, 0),
                        )
                    else:
                        progress = get_short_size(downloaded)
                    print("\r{:49}{:>30}".format(name_getting, progress), end="")

            if md5hash.hexdigest() != md5:
                print("\r{:67}{:>12}".format(name, "MD5 MISMATCH"))
                logging.error("MD5 mismatch for %s", dest)
                return False

            # wget-like timestamping for downloaded files
            if lastmod:
                timestamp = time.mktime(
                    time.strptime(lastmod, "%a, %d %b %Y %H:%M:%S GMT")) - time.timezone
                try:
                    os.utime(dest, (timestamp, timestamp))
                except OSError:
                    pass

            # downloaded successfully
            print("\r{:67}{:>12}".format(name, "[    OK    ]"))

            # skip already downloaded files
            # when trying to download from URL.dlurlalt
            del files_to_download[0]

            file_count += 1
    except (OSError, http.client.HTTPException) as ex:
        logging.error("Failed to download https://%s%s: %s", host, path, ex)
        return False
    finally:
        conn.close()

    return True


def get_current_steam_user():
    """
    Get the current AccountName with saved login credentials.

    If successful this returns the AccountName of the user with saved credentials.
    Otherwise this returns None.

    This function depends on the package "vdf".
    """
    loginvdf_paths = File.loginusers_paths.copy()
    # try Wine Steam directory first when Wine is used
    if Args.wine:
        loginvdf_paths.insert(0, os.path.join(Args.wine_steam_dir, File.loginvdf_inner))
    for path in loginvdf_paths:
        try:
            with open(path) as f_in:
                login_vdf = vdf.parse(f_in)

            for info in login_vdf["users"].values():
                remember = "RememberPassword" in info and info["RememberPassword"] == "1"
                recent_uc = "MostRecent" in info and info["MostRecent"] == "1"
                recent_lc = "mostrecent" in info and info["mostrecent"] == "1"
                if remember and (recent_lc or recent_uc) and "AccountName" in info:
                    return info["AccountName"]
        except (KeyError, OSError, TypeError, ValueError):
            pass
    return None


def get_proton_version(protondir):
    """
    Get Proton version from "version" file.

    This function returns (major, minor) version pair.
    Examples:
      "xxxxxxxxxx proton-5.13-6" -> (5, 13)
      "xxxxxxxxxx 6.1-GE-2" -> (6, 1)

    protondir: Proton top directory that has "version" file
    """
    with open(os.path.join(protondir, "version")) as f_version:
        ver = f_version.read(128)
    ver = ver.replace("proton-", "")
    major, minor = ver[ver.index(" ") + 1:ver.index("-")].split(".")
    return int(major), int(minor)


def get_short_size(size_bytes):
    """
    Get a file size string in short format.

    This function returns:
        "B" size (e.g. 2) when size_bytes < 1KiB
        "KiB" size (e.g. 345.6K) when size_bytes >= 1KiB and size_bytes < 1MiB
        "MiB" size (e.g. 7.8M) when size_bytes >= 1MiB

    size_bytes: File size in bytes
    """
    if size_bytes < 1024:
        return str(size_bytes)
    if size_bytes < 1048576:
        return "{:.1f}K".format(size_bytes / 1024)
    return "{:.1f}M".format(size_bytes / 1048576)


def is_envar_enabled(envars, name):
    """
    Check whether the specified environment variable is enabled.

    This returns True if the specified environment variable is
    already defined and set to nonempty and nonzero value.
    Otherwise this returns False.

    envars: A dict of environment variables
    name: The name of environment variable to check
    """
    if name not in envars:
        return False
    value = envars[name]
    return len(value) > 0 and value != "0"


def perform_self_update():
    """
    Update files to latest release. Do nothing for Python package.

    This function checks the latest GitHub release first.
    If local version is not up-to-date, this function retrieves the latest
    GitHub release asset (.tar.xz) and replaces existing files with extracted files.
    """
    # get latest release
    logging.info("Retrieving RELEASE from master")
    try:
        with urllib.request.urlopen(URL.release) as f_in:
            release = f_in.readline().rstrip().decode("ascii")
    except OSError as ex:
        sys.exit("Failed to retrieve RELEASE file: {}".format(ex))

    # we don't update when Python package is used
    try:
        with open(os.path.join(os.path.dirname(Dir.scriptdir), "RELEASE")) as f_in:
            # do nothing if the installed version is latest
            if release == f_in.readline().rstrip():
                logging.info("Already up-to-date.")
                return
    except OSError:
        sys.exit("'RELEASE' file doesn't exist. Self update aborted.")

    # retrieve the release asset
    archive_url = URL.rel_tarxz_tmpl.format(release)
    logging.info("Retrieving release asset %s", archive_url)
    try:
        with urllib.request.urlopen(archive_url) as f_in:
            asset_archive = f_in.read()
    except OSError as ex:
        sys.exit("Failed to retrieve release asset file: {}".format(ex))

    # unpack the archive
    logging.info("Unpacking archive %s", archive_url)
    topdir = os.path.dirname(Dir.scriptdir)
    try:
        with tarfile.open(fileobj=io.BytesIO(asset_archive), mode="r:xz") as f_in:
            f_in.extractall(topdir)
    except (OSError, tarfile.TarError) as ex:
        sys.exit("Failed to unpack release asset file: {}".format(ex))

    # update files
    archive_dir = os.path.join(topdir, "truckersmp-cli-" + release)
    for root, _dirs, files in os.walk(archive_dir, topdown=False):
        inner_root = root[len(archive_dir):]
        destdir = topdir + inner_root
        logging.debug("Creating directory %s", destdir)
        os.makedirs(destdir, exist_ok=True)
        for fname in files:
            srcpath = os.path.join(root, fname)
            dstpath = os.path.join(destdir, fname)
            logging.info("Copying %s as %s", srcpath, dstpath)
            os.replace(srcpath, dstpath)
        os.rmdir(root)

    # done
    logging.info("Self update complete")


def setup_wine_discord_ipc_bridge():
    """
    Check and download wine-discord-ipc-bridge.

    This checks whether winediscordipcbridge.exe is already downloaded
    and download it only when it is not present.
    When ready, this function returns the path to wine-discord-ipc-bridge.
    """
    # check whether the file is already downloaded
    need_download = True
    try:
        if check_hash(File.ipcbridge, File.ipcbridge_md5, hashlib.md5()):
            logging.debug("winediscordipcbridge.exe is present, MD5 is OK.")
            need_download = False
    except OSError:
        pass

    if need_download:
        # download winediscordipcbridge.exe from official repo
        # https://github.com/0e4ef622/wine-discord-ipc-bridge
        logging.debug("Downloading winediscordipcbridge.exe")
        os.makedirs(Dir.ipcbrdir, exist_ok=True)
        if not download_files(
                URL.github, [(URL.ipcbrpath, File.ipcbridge, File.ipcbridge_md5), ]):
            sys.exit("Failed to download winediscordipcbridge.exe")

    return File.ipcbridge


def set_wine_desktop_registry(prefix, wine, enable):
    """
    Set Wine desktop registry.

    If the 3rd argument (enable) is True, this function enables Wine desktop
    for the given Wine prefix.
    Otherwise, this function disables Wine desktop.

    prefix: Path to Wine prefix to configure
    wine: A list used to run Wine executable
    enable: Whether to enable Wine desktop
    """
    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"
    env["WINEPREFIX"] = prefix
    if Args.proton:
        env["WINEESYNC"] = "0" if is_envar_enabled(env, "PROTON_NO_ESYNC") else "1"
    regkey_explorer = "HKCU\\Software\\Wine\\Explorer"
    regkey_desktops = "HKCU\\Software\\Wine\\Explorer\\Desktops"
    if enable:
        logging.info("Enabling Wine desktop (%s)", Args.wine_desktop)
        subproc.call(
            wine + [
                "reg", "add", regkey_explorer,
                "/v", "Desktop", "/t", "REG_SZ", "/d", "Default", "/f"],
            env=env)
        subproc.call(
            wine + [
                "reg", "add", regkey_desktops,
                "/v", "Default", "/t", "REG_SZ", "/d", Args.wine_desktop, "/f"],
            env=env)
    else:
        logging.info("Disabling Wine desktop")
        subproc.call(
            wine + [
                "reg", "delete", regkey_explorer, "/v", "Desktop", "/f"], env=env)
        subproc.call(
            wine + [
                "reg", "delete", regkey_desktops, "/v", "Default", "/f"], env=env)


def wait_for_steam(use_proton, loginvdf_paths, wine=None, env=None):
    """
    Wait for Steam to be running.

    If use_proton is True and the value of "--native-steam-dir" option is
    "auto" (default), this function also detects
    the Steam installation directory for Proton and returns it.

    On user login the timestamp in
    [steam installation directory]/config/loginusers.vdf gets updated.
    We can detect the timestamp update with comparing timestamps.

    use_proton: True if Proton is used, False if Wine is used
    loginvdf_paths: loginusers.vdf paths
    wine: Wine command (path or name)
         (can be None if use_proton is True)
    env: A dictionary that contains environment variables
         (can be None if use_proton is True)
    """
    # pylint: disable=too-many-branches,too-many-statements

    steamdir = None
    loginvdfs_checked = []
    loginusers_timestamps = []
    if use_proton and Args.native_steam_dir != "auto":
        # only check the specified vdf path
        loginvdfs_checked.append(os.path.join(Args.native_steam_dir, File.loginvdf_inner))
    else:
        # check all known vdf paths
        loginvdfs_checked += loginvdf_paths
    for path in loginvdfs_checked:
        try:
            stat = os.stat(path)
            loginusers_timestamps.append(stat.st_mtime)
        except OSError:
            loginusers_timestamps.append(0)
    if not check_steam_process(use_proton=use_proton, wine=wine, env=env):
        logging.debug("Starting Steam...")
        if use_proton:
            subproc.Popen(
                ("nohup", "steam"), stdout=subproc.DEVNULL, stderr=subproc.STDOUT)
        else:
            subproc.Popen(
                ("nohup",
                 wine, os.path.join(Args.wine_steam_dir, "steam.exe"), "-no-cef-sandbox"),
                env=env, stdout=subproc.DEVNULL, stderr=subproc.STDOUT)
        waittime = 99
        while waittime > 0:
            print(ngettext(
                "\rWaiting {} second for steam to start up. ",
                "\rWaiting {} seconds for steam to start up. ",
                waittime).format(waittime), end="")
            time.sleep(1)
            waittime -= 1
            for i, path in enumerate(loginvdfs_checked):
                try:
                    stat = os.stat(path)
                    if stat.st_mtime > loginusers_timestamps[i]:
                        print("\r{}".format(" " * 70))  # clear "Waiting..." line
                        logging.debug(
                            "Steam should now be up and running and the user logged in.")
                        steamdir = os.path.dirname(os.path.dirname(loginvdfs_checked[i]))
                        break
                except OSError:
                    pass
            else:
                continue
            break
        else:
            # waited 99 seconds without detecting timestamp change
            print("\r{}".format(" " * 70))
            logging.debug("Steam should be up now.")
            if use_proton:
                if Args.native_steam_dir == "auto":
                    # could not detect steam installation directory
                    # fallback to $XDG_DATA_HOME/Steam
                    steamdir = os.path.join(Dir.XDG_DATA_HOME, "Steam")
                else:
                    # use specified path
                    steamdir = Args.native_steam_dir
    else:
        # Steam is running
        logging.debug("Steam is running")
        if use_proton:
            if Args.native_steam_dir == "auto":
                # detect most recently updated "loginusers.vdf" file
                max_mtime = max(loginusers_timestamps)
                for i, path in enumerate(loginvdfs_checked):
                    if loginusers_timestamps[i] == max_mtime:
                        steamdir = os.path.dirname(os.path.dirname(loginvdfs_checked[i]))
                        break
            else:
                steamdir = Args.native_steam_dir
    return steamdir

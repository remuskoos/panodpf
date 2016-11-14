#!/usr/bin/env python
# encoding: utf-8
import os
import json
import time
import socket
import struct
import random
import argparse

plugin_mode = True

# This try/except for imports helps us to figure out if we are in plugin or standalone mode.
try:
    import xbmc
    import xbmcvfs
    import xbmcaddon

    __addon__      = xbmcaddon.Addon()
    log = xbmc.log
except ImportError:
    plugin_mode = False

    # Use 'level' here to match 'xbmc.log(...)' signature.
    def log(message, level=None):
        print message

ALLOWED_EXTENSIONS = (".jpg", ".png", ".tiff", ".gif")
MAX_REQUEST_ID = 100000


def get_random_file_path(pano_folder, recurse_into_subfolders=True):
    log("get_random_file_path({0}, {1})".format(pano_folder, recurse_into_subfolders))
    folder_list, file_list = xbmcvfs.listdir(xbmc.translatePath(pano_folder))

    # Filter our file list by the allowed extensions.
    file_list = [f for f in file_list if f.lower().endswith(ALLOWED_EXTENSIONS)]
    folder_list_len = len(folder_list)
    file_list_len = len(file_list)
    total_len = folder_list_len + file_list_len

    log("folder_list = {0}  file_list = {1}  folder_list_len = {2}  file_list_len = {3}".format(folder_list, file_list, folder_list_len, file_list_len))
    if total_len == 0:
        yield None

    if not recurse_into_subfolders:
        yield None if not file_list else os.path.join(pano_folder, random.choice(file_list))

    # At this point 'total_len' is at least 1 so we have at least a file or a folder.
    choice_idx = random.choice(xrange(total_len))
    log("choice_idx = {0}".format(choice_idx))

    # If this is the case it means that we have at least one file in the file list.
    if choice_idx >= folder_list_len:
        final_path = os.path.join(pano_folder, file_list[choice_idx - folder_list_len])
        log("Returning path: '{0}' ...".format(final_path))
        yield final_path

    # FIXME: Can this cause an infinite recursion ?
    get_random_file_path(os.path.join(pano_folder, folder_list[choice_idx]), recurse_into_subfolders)


def xbmcvfs_walk(pano_folder, recurse_into_subfolders=True):
    pending_folders = []
    pending_folders.append(pano_folder)
    while True:
        try:
            current_folder = pending_folders.pop()
            folder_list, file_list = xbmcvfs.listdir(xbmc.translatePath(current_folder))
            yield current_folder, folder_list, file_list

            if not recurse_into_subfolders:
                break

            # Add the full paths of folders from folder list to the pending folders so we can traverse them at a later time.
            pending_folders.extend([os.path.join(current_folder, f) for f in folder_list])
        except IndexError:
            break


def pano_paths(pano_folder, recurse_into_subfolders=True, randomize=True):
    log("pano_paths({0}, {1}, {2})".format(pano_folder, recurse_into_subfolders, randomize))
    if not pano_folder:
        return

    if randomize:
        for path in get_random_file_path(pano_folder, recurse_into_subfolders):
            yield path
    else:
        for folder, folder_list, file_list in xbmcvfs_walk(pano_folder, recurse_into_subfolders):
            for file in file_list:
                if file.lower().endswith(ALLOWED_EXTENSIONS):
                    # For each picture file we construct and yield the full path.
                    yield os.path.join(folder, file)


def received_all_replies(sock, nreplies_expected):
    nreplies = 0
    reply_set = set()

    # Look for responses from all recipients.
    while True:
        log("Waiting for replies from servers. Expecting {0} ACKs ...".format(nreplies_expected))
        reply = None
        try:
            json_reply, server = sock.recvfrom(1024)
            try:
                reply = json.loads(json_reply)
            except (TypeError, ValueError) as e:
                log("Could not decode JSON reply '{0}': {1}".format(json_reply, e))
        except socket.timeout:
            log("Timed out. Assuming no more replies (got {0} total).".format(nreplies))
            break
        else:
            if reply:
                log("Received '{0}' from {1}".format(reply, server))
                current_display = reply.get('current_display')
                if current_display not in reply_set:
                    reply_set.add(current_display)
                    nreplies += 1

        # Break out of the loop if we got all the replies we expected.
        if nreplies and nreplies == nreplies_expected:
            break

    format_str = "Got {0} out of {1} replies.{2}"
    log(format_str.format(nreplies, nreplies_expected, "" if nreplies != 0 and nreplies == nreplies_expected else " Retrying ..."))

    return nreplies != 0 and nreplies == nreplies_expected


def send_request_and_process_replies(sock, multicast_group, nreplies_expected,  method, params=None, request_id=1):
    request = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    try:
        json_request = json.dumps(request)
    except TypeError as e:
        log("Failed to JSON encode message '{0}': {1}".format(request, e))
        return False

    # Retry loop. Keep sending the same request until we get replies from all servers.
    while True:
        log("Sending request to servers: {0}".format(json_request))
        # Send data to the multicast group.
        sent = sock.sendto(json_request, multicast_group)

        if received_all_replies(sock, nreplies_expected):
            break

    return True


def set_up_networking(multicast_address, multicast_port, server_timeout_wait=5):
    multicast_group = (multicast_address, multicast_port)

    # Create the datagram socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Set a timeout so the socket does not block indefinitely when trying to receive data.
    sock.settimeout(server_timeout_wait)

    # Set the time-to-live for messages to 1 so they do not go past the local network segment.
    ttl = struct.pack('b', 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    return sock, multicast_group


def start_panodpf_client():
    # Instantiate a monitor object so we can check if we need to exit.
    monitor = xbmc.Monitor()

    # Get the configuration settings.
    multicast_address = __addon__.getSetting('multicast_address')
    multicast_port = int(__addon__.getSetting('multicast_port'))
    server_timeout_wait = int(__addon__.getSetting('server_timeout_wait'))

    sock, multicast_group = set_up_networking(multicast_address, multicast_port, server_timeout_wait)

    request_id = 0

    while not monitor.abortRequested():
        pano_folder = __addon__.getSetting('dpf_folder')
        recurse = True if __addon__.getSetting('recurse_into_subfolders').lower() == "true" else False
        randomize = True if __addon__.getSetting('randomize').lower() == "true" else False

        for pano_path in pano_paths(pano_folder, recurse_into_subfolders=recurse, randomize=randomize):
            if not pano_path:
                log("Got None path from 'pano_paths({0}, {1}, {2})' ...".format(pano_folder, recurse, randomize))
                # Sleep while the image is being displayed.
                time.sleep(int(__addon__.getSetting('slideshow_delay')))
                continue

            total_displays = int(__addon__.getSetting('total_displays')) + 1
            rotation = int(__addon__.getSetting('rotation'))
            display_pano_params = {"path": pano_path, "rotation": rotation, "total_displays": total_displays}
            send_request_and_process_replies(sock, multicast_group, total_displays, "display_pano", display_pano_params, request_id)
            request_id = 0 if request_id >= MAX_REQUEST_ID else request_id + 1

            # Sleep while the image is being displayed.
            time.sleep(int(__addon__.getSetting('slideshow_delay')))

if plugin_mode:
    log("Entering PanoDPFClient plugin mode ...")
    start_panodpf_client()
else:
    log("Entering PanoDPFClient standalone mode ...")
    parser = argparse.ArgumentParser(description='Filter panoramas by form factor.', epilog="At least one of '-l' or '-g' should be specified.")
    parser.add_argument("multicast_address", type=str, help="Multicast address to send the request to.")
    parser.add_argument("multicast_port", type=int, help="Multicast port to send the request to.")
    parser.add_argument("nreplies_expected", type=int, help="The number of replies expected as a result of our request. "
                                                            "We keep retying until we get the expected numbers of replies.")
    parser.add_argument("command", type=str, help="The command to send to the multicast group.")
    parser.add_argument("-t", "--timeout-wait", type=int, default=5, help="The amount of seconds to wait for the servers to reply before giving up.")
    args = parser.parse_args()

    sock, multicast_group = set_up_networking(args.multicast_address, args.multicast_port, server_timeout_wait=args.timeout_wait)
    send_request_and_process_replies(sock, multicast_group, args.nreplies_expected, args.command)

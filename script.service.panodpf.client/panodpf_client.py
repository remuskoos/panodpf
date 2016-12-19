#!/usr/bin/env python
# encoding: utf-8
"""
File that implements a panoramic display Digital Picture Frame (DPF) client.

Written by Remus Koos.
"""

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
PLAYLIST_FILE_NAME = "/tmp/PANODPF.playlist"
DISPLAY_SCHEDULE_TYPE_MAPPING = {0: 'Flat', 1: 'Any', 2: 'LR', 3: 'RL', 4: 'V', 5: 'Random'}
DELAY_INCREMENT_MAPPING = {0: 100, 1: 200, 2: 300, 3: 400, 4: 500, 5: 600, 6: 700, 7: 800, 8: 900, 9: 1000, 10: 1500, 11: 2000, 12: 2500, 13: 3000}


def display_notification(message, time_in_s=10):
    xbmc.executebuiltin("Notification(PanoDPFClient,{0},{1})".format(message, time_in_s))


def xbmc_file_exists(xbmc_file_name):
    return xbmcvfs.exists(xbmc.translatePath(xbmc_file_name))


def get_local_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 0))  # connecting to a UDP address doesn't send packets
    return s.getsockname()[0]


def get_display_schedule(schedule_type, total_displays, delay_increment):
    display_schedules = ('LR', 'RL', 'V', 'Random', 'Flat')
    if schedule_type == 'Any':
        schedule_type = random.choice(display_schedules)

    log("Using '{0}' schedule type.".format(schedule_type))

    if schedule_type == 'LR':
        return [i * delay_increment for i in xrange(total_displays)]
    elif schedule_type == 'RL':
        return [(total_displays - i - 1) * delay_increment for i in xrange(total_displays)]
    elif schedule_type == 'V':
        if total_displays <= 2:
            return [0 for i in xrange(total_displays)]
        left_list_len = int(round(float(total_displays)/2))
        display_schedule = [(left_list_len - i - 1) * delay_increment * 2 for i in xrange(left_list_len)]
        right_list = display_schedule[0:left_list_len - (total_displays % 2)]
        right_list.reverse()
        log("display_schedule: {0}  left_list_len: {1}  right_list: {2}".format(display_schedule, left_list_len, right_list))
        display_schedule.extend(right_list)
        return display_schedule
    elif schedule_type == 'Random':
        random_schedule = [i * delay_increment for i in xrange(total_displays)]
        random.shuffle(random_schedule)
        return random_schedule
    else:
        return [0 for i in xrange(total_displays)]


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


def generate_playlist(pano_folder, recurse_into_subfolders, playlist_file_name=PLAYLIST_FILE_NAME):
    nitems = 0

    with open(playlist_file_name, "w+b") as fd:
        for folder, folder_list, file_list in xbmcvfs_walk(pano_folder, recurse_into_subfolders):
            for file in file_list:
                if file.lower().endswith(ALLOWED_EXTENSIONS):
                    # For each picture file we construct and write the full path.
                    fd.write(os.path.join(folder, file) + os.linesep)
                    nitems += 1

    log("Generated playlist '{0}' with {1} items.".format(playlist_file_name, nitems))
    return playlist_file_name, nitems


def get_random_file_path_from_paylist(playlist_file_name, nitems):
    idx = random.randint(0, nitems - 1)
    current_idx = 0

    for line in open(playlist_file_name):
        if idx == current_idx:
            return line.strip()

        current_idx += 1

    log("Could not find index {0} in playlist '{1}'. Returning last item '{2}'.".format(idx, playlist_file_name, line), level=xbmc.LOGERROR)

    return line


def yield_random_pano_paths_from_palylist(playlist_file_name, nitems):
    nyielded_paths = 0

    while True:
        yield get_random_file_path_from_paylist(playlist_file_name, nitems)
        nyielded_paths += 1

        # Return if we generated nitems or more so the playlist has a chance to get rebuilt in case we added new files.
        if nyielded_paths >= nitems:
            log("Yielded {0} random pano paths. Returning to enable playlist rebuild ...".format(nyielded_paths))
            return


def pano_paths(pano_folder, recurse_into_subfolders=True, randomize=True):
    npano_paths = 0

    if not pano_folder:
        #display_notification("Pano folder is not configured")
        return

    playlist_file_name, nitems = generate_playlist(pano_folder, recurse_into_subfolders)
    if not nitems:
        #display_notification("Generated playlist has no items")
        return

    if randomize:
        for pano_file_path in yield_random_pano_paths_from_palylist(playlist_file_name, nitems):
            log("Returning random PANODPF playlist item '{0}' ...".format(pano_file_path))
            yield pano_file_path
    else:
        for pano_file_path in open(playlist_file_name):
            log("Returning sequential PANODPF playlist item '{0}' ...".format(pano_file_path))
            yield pano_file_path


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

        nreplies = len(reply_set)
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
                time.sleep(1)
                continue

            if not xbmc_file_exists(pano_path):
                log("Could not open pano '{0}'. Namespace might have changed. Rebuilding playlist ...".format(pano_path))
                break

            total_displays = int(__addon__.getSetting('total_displays')) + 1
            rotation = int(__addon__.getSetting('rotation'))
            display_schedule_type_idx = int(__addon__.getSetting('display_schedule_type'))
            delay_increment_idx = int(__addon__.getSetting('delay_increment'))
            #log("display_schedule_type_idx = {0}  delay_increment_idx = {1}".format(display_schedule_type_idx, delay_increment_idx))
            display_schedule_type = DISPLAY_SCHEDULE_TYPE_MAPPING[display_schedule_type_idx]
            delay_increment = DELAY_INCREMENT_MAPPING[delay_increment_idx]
            #log("display_schedule_type = {0}  delay_increment = {1}".format(display_schedule_type, delay_increment))

            process_pano_params = {"path": pano_path, "rotation": rotation, "total_displays": total_displays}
            send_request_and_process_replies(sock, multicast_group, total_displays, "process_pano", process_pano_params, request_id)

            request_id += 1
            display_pano_params = {"path": pano_path, "total_displays": total_displays,
                                   "display_schedule": get_display_schedule(display_schedule_type, total_displays, delay_increment)}
            send_request_and_process_replies(sock, multicast_group, total_displays, "display_pano", display_pano_params, request_id)

            # Sleep while the image is being displayed.
            time.sleep(int(__addon__.getSetting('slideshow_delay')))

            # Make sure the request ID does not overflow.
            request_id = 0 if request_id >= MAX_REQUEST_ID else request_id + 1

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

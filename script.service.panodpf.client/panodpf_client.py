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

from Queue import Queue

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

ANNOTATION_FONT_FILE_DEFAULT = "LiberationSans-Bold.ttf"

ALLOWED_EXTENSIONS = (".jpg", ".png", ".tiff", ".gif")
MAX_REQUEST_ID = 100000
PLAYLIST_FILE_NAME = "/tmp/PANODPF.playlist"
DISPLAY_SCHEDULE_TYPE_MAPPING = {0: 'Random', 1: 'Flat', 2: 'LR', 3: 'RL', 4: 'V', 5: 'ReverseV', 6: 'Shuffle'}
DISPLAY_SCHEDULES = ('Flat', 'LR', 'RL', 'V', 'ReverseV', 'Shuffle')

DELAY_INCREMENT_MAPPING = {0: 100, 1: 200, 2: 300, 3: 400, 4: 500, 5: 600, 6: 700, 7: 800, 8: 900, 9: 1000, 10: 1500, 11: 2000, 12: 2500, 13: 3000}


class LRURandomInt(object):
    """ Least Recently Used Random Int: Class that return a random int that hs not been returned recently. """
    MRU_PERCENT = 50

    def __init__(self, nints, mru_percent=MRU_PERCENT):
        nentries = int((float(nints) * mru_percent)/100)
        self.max_mru_entries = 1 if nentries <= 0 else nentries
        # The set provides membership functionality for the Most Recently Used (MRU) entries.
        self.mru_entries = set()
        # The Queue provides FIFO functionality for the Most Recently Used (MRU) entries.
        self.qmru_entries = Queue()
        self.nints = nints
        log("Created 'LRURandomInt(nints={0}, mru_percent={1})' object with {2} MRU entries ...".format(nints, mru_percent, self.max_mru_entries))

    def _purge_mru_entries(self):
        # If we exceeded the maximum number of allowed LRS entries remove one entry from the set.
        if len(self.mru_entries) >= self.max_mru_entries:
            value = self.qmru_entries.get()
            # Remove from the set the value that we got from Queue's 'get(...)' method.
            # This way we supply FIFO semantics while making use of the set's membership operator.
            self.mru_entries.remove(value)
            log("Number of allowed MRU entries exceeded ({0} >= {1}). Popped value = '{2}'.".format(len(self.mru_entries) + 1, self.max_mru_entries, value))

    def _add_mru_entry(self, value):
        self.mru_entries.add(value)
        self.qmru_entries.put(value)

    def get(self):
        # If we only have one entry we should always return that one.
        if self.nints <= 1:
            return 0

        # At this point 'self.nints >= 2' so we have a choice to return.
        new_random_int = random.randint(0, self.nints - 1)
        log("Generated value '{0}' is {1}in the MRU set: {2}".format(new_random_int, "" if new_random_int in self.mru_entries else "not ", self.mru_entries))

        if new_random_int in self.mru_entries:
            # The entry generated is in the LRU set. Search for the next value that is not in the LRU set.
            while True:
                # While handling overflows increment 'random_int' until we find a value not in 'self.mru_entries'.
                new_random_int += 1
                if new_random_int >= self.nints:
                    new_random_int = 0

                if new_random_int not in self.mru_entries:
                    break

        log("Returning LRU random int '{0}'.".format(new_random_int))
        self._purge_mru_entries()
        self._add_mru_entry(new_random_int)
        return new_random_int


display_schedule_random_int = LRURandomInt(len(DISPLAY_SCHEDULES))
playlist_random_int = None


def display_notification(message, time_in_s=10):
    xbmc.executebuiltin("Notification(PanoDPFClient,{0},{1})".format(message, time_in_s))


def xbmc_file_exists(xbmc_file_name):
    return xbmcvfs.exists(xbmc.translatePath(xbmc_file_name))


def get_local_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 0))  # connecting to a UDP address doesn't send packets
    return s.getsockname()[0]


def get_display_schedule(schedule_type, total_displays, delay_increment):
    global display_schedule_random_int
    if schedule_type == 'Random':
        # Use 'display_schedule_random_int' to guarantee that we do not get the same consecutive display schedules.
        schedule_type = DISPLAY_SCHEDULES[display_schedule_random_int.get()]

    log("Using '{0}' display schedule type ...".format(schedule_type))

    if schedule_type == 'LR':
        return [i * delay_increment for i in xrange(total_displays)]
    elif schedule_type == 'RL':
        return [(total_displays - i - 1) * delay_increment for i in xrange(total_displays)]
    elif schedule_type == 'V':
        # If the total number of displays is less than or equal to 2 we have a flat display schedule.
        if total_displays <= 2:
            return [0 for i in xrange(total_displays)]

        # Calculate the left part of the display schedule.
        left_list_len = int(round(float(total_displays)/2))
        display_schedule = [(left_list_len - i - 1) * delay_increment * 2 for i in xrange(left_list_len)]

        # Calculate the right side of the display schedule.
        right_list = display_schedule[0:left_list_len - (total_displays % 2)]
        right_list.reverse()

        # Append the right side of the display schedule to create the final one.
        display_schedule.extend(right_list)
        return display_schedule
    elif schedule_type == 'ReverseV':
        # If the total number of displays is less than or equal to 2 we have a flat display schedule.
        if total_displays <= 2:
            return [0 for i in xrange(total_displays)]

        # Calculate the left part of the display schedule.
        left_list_len = int(round(float(total_displays)/2))
        display_schedule = [i * delay_increment * 2 for i in xrange(left_list_len)]

        # Calculate the right side of the display schedule.
        right_list = display_schedule[0:left_list_len - (total_displays % 2)]
        right_list.reverse()

        # Append the right side of the display schedule to create the final one.
        display_schedule.extend(right_list)
        return display_schedule
    elif schedule_type == 'Shuffle':
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
    global playlist_random_int
    idx = playlist_random_int.get()
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
    global playlist_random_int
    npano_paths = 0

    if not pano_folder:
        #display_notification("Pano folder is not configured")
        return

    playlist_file_name, nitems = generate_playlist(pano_folder, recurse_into_subfolders)
    if not nitems:
        #display_notification("Generated playlist has no items")
        return

    # Create e new 'LRURandomInt' object based on the current number of items in the playlist.
    playlist_random_int = LRURandomInt(nitems)

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


def get_location_from_full_path(full_path):
    full_path_list = os.path.normpath(full_path).split(os.sep)
    if len(full_path_list) == 0 or len(full_path_list) == 1:
        return ""

    if len(full_path_list) == 2:
        return full_path_list[-2]

    return "{0}, {1}".format(full_path_list[-2], full_path_list[-3])


def get_annotation_info(pano_path):
    annotate = True if __addon__.getSetting('annotate_image').lower() == "true" else False
    if not annotate:
        return None

    text = get_location_from_full_path(pano_path)

    # Get annotation settings.
    x = int(__addon__.getSetting('annotation_horizontal_offset'))
    y = int(__addon__.getSetting('annotation_vertical_offset'))
    font_size = int(__addon__.getSetting('annotation_font_size'))
    font_opacity = int(__addon__.getSetting('annotation_font_opacity'))
    # Could be a setting in the future.
    font_file = ANNOTATION_FONT_FILE_DEFAULT

    return {"text": text,
            "text_offset": (x, y),
            "font_file": font_file,
            "font_size": font_size,
            "font_opacity": font_opacity}


def send_process_pano_request(sock, multicast_group, request_id, pano_path):
    # Get settings.
    total_displays = int(__addon__.getSetting('total_displays')) + 1
    rotation = int(__addon__.getSetting('rotation'))

    # Build, send request and wait for all replies.
    process_pano_params = {"path": pano_path, "rotation": rotation, "total_displays": total_displays, "annotate": get_annotation_info(pano_path)}
    send_request_and_process_replies(sock, multicast_group, total_displays, "process_pano", process_pano_params, request_id)


def send_display_pano_request(sock, multicast_group, request_id, pano_path):
    # Get settings.
    total_displays = int(__addon__.getSetting('total_displays')) + 1
    display_schedule_type_idx = int(__addon__.getSetting('display_schedule_type'))
    delay_increment_idx = int(__addon__.getSetting('delay_increment'))
    # log("display_schedule_type_idx = {0}  delay_increment_idx = {1}".format(display_schedule_type_idx, delay_increment_idx))
    display_schedule_type = DISPLAY_SCHEDULE_TYPE_MAPPING[display_schedule_type_idx]
    delay_increment = DELAY_INCREMENT_MAPPING[delay_increment_idx]
    # log("display_schedule_type = {0}  delay_increment = {1}".format(display_schedule_type, delay_increment))

    display_pano_params = {"path": pano_path, "total_displays": total_displays,
                           "display_schedule": get_display_schedule(display_schedule_type, total_displays, delay_increment)}
    send_request_and_process_replies(sock, multicast_group, total_displays, "display_pano", display_pano_params, request_id)


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

            send_process_pano_request(sock, multicast_group, request_id, pano_path)

            # Increment the request ID so servers don't think this request is a duplicate of the process pano request.
            request_id += 1
            send_display_pano_request(sock, multicast_group, request_id, pano_path)

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

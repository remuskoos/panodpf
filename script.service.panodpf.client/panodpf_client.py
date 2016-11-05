#!/usr/bin/env python
# encoding: utf-8
import os
import json
import xbmc
import time
import socket
import struct
import xbmcvfs
import xbmcaddon

__addon__      = xbmcaddon.Addon()

PANO_SUFFIXES = (".jpg", ".png", ".tiff", ".gif")
MAX_REQUEST_ID = 100000

# FIXME: Add a randomize option.
# FIXME: Recurse into subfolders.
def pano_paths(pano_folder, recurse_into_subfolders=True):
    if not pano_folder:
        return

    folder_list, file_list = xbmcvfs.listdir(xbmc.translatePath(pano_folder))

    folder = pano_folder
    for file in file_list:
        if file.lower().endswith(PANO_SUFFIXES):
            # For each picture file we construct and yield the full path.
            yield os.path.join(folder, file)


def received_all_replies(sock):
    nreplies = 0
    nreplies_expected = 0
    reply_set = set()

    # Look for responses from all recipients.
    while True:
        xbmc.log("Waiting for ACKs from servers ...")
        try:
            json_reply, server = sock.recvfrom(256)
            try:
                reply = json.loads(json_reply)
                nreplies_expected = reply.get('total_displays', 0)
            except (TypeError, ValueError) as e:
                xbmc.log("Could not decode JSON reply '{0}': {1}".format(json_reply, e))
        except socket.timeout:
            xbmc.log("Timed out. Assuming no more replies (got {0} total).".format(nreplies))
            break
        else:
            xbmc.log("Received '{0}' from {1}".format(reply, server))
            current_display = reply.get('current_display')
            if current_display not in reply_set:
                reply_set.add(current_display)
                nreplies += 1

    format_str = "Got {0} out of {1} replies.{2}"
    xbmc.log(format_str.format(nreplies, nreplies_expected, "" if nreplies != 0 and nreplies == nreplies_expected else " Retrying ..."))

    return nreplies != 0 and nreplies == nreplies_expected


def send_request_and_process_replies(sock, multicast_group, method, params=None, request_id=1):
    request = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    try:
        json_request = json.dumps(request)
    except TypeError as e:
        xbmc.log("Failed to JSON encode message '{0}': {1}".format(request, e))
        return False

    # Retry loop. Keep sending the same request until we get replies from all servers.
    while True:
        xbmc.log("Sending request to servers: {0}".format(json_request))
        # Send data to the multicast group.
        sent = sock.sendto(json_request, multicast_group)

        if received_all_replies(sock):
            break

    return True


def start_panodpf_client():
    # Instantiate a monitor object so we can check if we need to exit.
    monitor = xbmc.Monitor()

    multicast_address = __addon__.getSetting('multicast_address')
    multicast_port = int(__addon__.getSetting('multicast_port'))
    multicast_group = (multicast_address, multicast_port)

    # Create the datagram socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Set a timeout so the socket does not block indefinitely when trying to receive data.
    server_timeout_wait = int(__addon__.getSetting('server_timeout_wait'))
    sock.settimeout(server_timeout_wait)

    # Set the time-to-live for messages to 1 so they do not go past the local network segment.
    ttl = struct.pack('b', 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    pano_folder = __addon__.getSetting('dpf_folder')
    recurse = True if __addon__.getSetting('recurse_into_subfolders').lower() == "true" else False
    request_id = 0

    # Receive/respond loop.
    while not monitor.abortRequested():
        for pano_path in pano_paths(pano_folder, recurse_into_subfolders=recurse):
            send_request_and_process_replies(sock, multicast_group, "display_pano", {"path": pano_path}, request_id)
            request_id = 0 if request_id >= MAX_REQUEST_ID else request_id + 1

            # Sleep while the image is being displayed.
            time.sleep(int(__addon__.getSetting('slideshow_delay')))

start_panodpf_client()

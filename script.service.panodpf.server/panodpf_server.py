import io
import os
import json
import xbmc
import socket
import struct
import xbmcvfs
import xbmcaddon

from PIL import Image

PANO_TMP_FOLDER = "/tmp"

__addon__      = xbmcaddon.Addon()


def safe_remove_file(full_file_path):
    try:
        os.remove(full_file_path)
    except EnvironmentError:
        pass


def crop_pano(im, chunk, tchunks):
    w, h = im.size
    xbmc.log("Pic size: ({0}, {1})  Crop coordinates: ({2}, {3}, {4}, {5})".format(w, h, (chunk - 1)*w/tchunks, 0, chunk*w/tchunks, h))
    cim = im.crop(((chunk - 1)*w/tchunks, 0, chunk*w/tchunks, h))
    return cim


def build_cropped_pano_path(pano_path, cropped_pano_folder, current_display, total_displays):
    pano_filename = os.path.basename(pano_path)
    imgname, imgext = pano_filename.split('.')
    cropped_pano_name = "{0}{1}of{2}.{3}".format(imgname, current_display, total_displays, imgext)
    return os.path.join(cropped_pano_folder, cropped_pano_name)


def crop_and_save_pano(pano_path, cropped_pano_folder, current_display, total_displays):
    pano_file = xbmcvfs.File(xbmc.translatePath(pano_path))
    pano_bytes_file = io.BytesIO(pano_file.readBytes())
    im = Image.open(pano_bytes_file)

    cim = crop_pano(im, current_display, total_displays)
    cropped_pano_path = build_cropped_pano_path(pano_path, cropped_pano_folder, current_display, total_displays)
    xbmc.log("Saving cropped_pano_path '{0}' ...".format(cropped_pano_path))
    cim.save(cropped_pano_path)

    pano_bytes_file.close()
    pano_file.close()

    del im
    del pano_file
    del pano_bytes_file

    xbmc.log("Returning from crop_and_save_pano(...) (cropped_pano_path = '{0}') ...".format(cropped_pano_path))
    return cropped_pano_path


def process_and_display_pano(pano_name, current_display, total_displays):
    pic_folder = __addon__.getSetting('dpf_folder')

    if not pic_folder or not current_display or not total_displays:
        xbmc.log("PanoDPFServer plugin is not fully configured yet. Ignoring pano display request.", level=xbmc.LOGWARNING)
        format_str = "  pic_folder = '{0}'  pano_name = '{1}'  current_display = {2}  total_displays = {3}"
        xbmc.log(format_str.format(pic_folder, pano_name, current_display, total_displays), level=xbmc.LOGWARNING)
        return None, "PanoDPFServer is not fully configured."

    pano_path = os.path.join(pic_folder, pano_name)
    try:
        cropped_pano_path = crop_and_save_pano(pano_path, PANO_TMP_FOLDER, current_display, total_displays)
    except IOError as e:
        msg = "Failed to load and/or crop pano with path '{0}': {1}.".format(pano_path, e)
        xbmc.log(msg, level=xbmc.LOGWARNING)
        return None, msg

    #cropped_pano_bytes_file = io.BytesIO(open(cropped_pano_path, "rb").read())
    #xbmc.executebuiltin("ShowPicture({0})".format(cropped_pano_bytes_file))
    xbmc.log("Displaying pano slice {0} of {1} (path = '{2}')".format(current_display, total_displays, cropped_pano_path))
    xbmc.executebuiltin("ShowPicture({0})".format(cropped_pano_path))
    return cropped_pano_path, ""

########################################################################################################################
# JSON RPC methods and table.                                                                                          #
def display_pano(params, current_display, total_displays):
    if not params:
        msg = "Invalid 'display_pano' params: '{0}'".format(params)
        xbmc.log(msg)
        return None, msg

    try:
        pano_path = params.get('path')
    except AttributeError as e:
        msg = "Invalid 'display_pano' params: '{0}': {1}".format(params, e)
        xbmc.log(msg)
        return None, msg

    return process_and_display_pano(pano_path, current_display, total_displays)

def turn_off_screen(params, current_display, total_displays):
    return None, ""

def turn_on_screen(params, current_display, total_displays):
    return None, ""

METHOD_TABLE = {"display_pano": display_pano,
                "turn_off_screen": turn_off_screen,
                "turn_on_screen": turn_on_screen}
# End JSON RPC methods and table.                                                                                      #
########################################################################################################################

def process_request_and_send_reply(sock, current_pano_id):
    current_display = __addon__.getSetting('current_display')
    current_display = int(current_display) if current_display else current_display
    total_displays = __addon__.getSetting('total_displays')
    total_displays = int(total_displays) if total_displays else total_displays

    xbmc.log("Waiting to receive message ...")
    json_request, address = sock.recvfrom(1024)
    xbmc.log("Received '{0}' from {1}".format(json_request, address))
    reply = {"jsonrpc": "2.0", "result": "ERROR", "id": None, "current_display": current_display, "total_displays": total_displays}

    try:
        request = json.loads(json_request)
    except TypeError as e:
        xbmc.log("Could not decode JSON request {0}: {1}".format(json_request, e))
        reply['error'] = {"code": -1, "message": "Invalid Request"}
        sock.sendto(json.dumps(reply), address)
        return None, current_pano_id

    xbmc.log("Loaded JSON request: {0}".format(request))

    reply['id'] = request.get('id')
    method = request.get('method')
    params = request.get('params')

    xbmc.log("After getting method and params ... ")

    if method == 'display_pano' and reply.get('id') == current_pano_id:
        reply['result'] = 'Duplicate'
        xbmc.log("Sending reply {0} to '{1}' ...".format(reply, address))
        sock.sendto(json.dumps(reply), address)
        return None, current_pano_id

    xbmc.log("Calling METHOD_TABLE[{0}]({1}, {2}, {3})".format(method, params, current_display, total_displays))

    try:
        result, reason = METHOD_TABLE[method](params, current_display, total_displays)
    except KeyError:
        msg = "Invalid method '{0}'.".format(method)
        xbmc.log(msg)
        reply['error'] = {"code": -2, "message": msg}
        sock.sendto(json.dumps(reply), address)
        return None, current_pano_id

    if method == 'display_pano':
        current_pano_id = request.get('id')

    if not result:
        reply['error'] = {'code': -3, 'message': reason}
    else:
        reply['result'] = 'OK'
    xbmc.log("Sending reply {0} to '{1}' ...".format(reply, address))
    sock.sendto(json.dumps(reply), address)
    return result, current_pano_id


def start_panodpf_server():
    # Instantiate a monitor object so we can check if we need to exit.
    monitor = xbmc.Monitor()

    multicast_address = __addon__.getSetting('multicast_address')
    multicast_port = int(__addon__.getSetting('multicast_port'))

    # Create the socket.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind to the server address.
    sock.bind(('', multicast_port))
    xbmc.log("Started multicast Pano DPF UDP server on port {0} ...".format(multicast_port))

    # Tell the operating system to add the socket to the multicast group on all interfaces.
    group = socket.inet_aton(multicast_address)
    mreq = struct.pack('4sL', group, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    prev_pano_path = None
    current_pano_id = -1

    # Receive/respond loop.
    while not monitor.abortRequested():
        curr_pano_path, current_pano_id = process_request_and_send_reply(sock, current_pano_id)

        # Remove the previous cropped pano path so temporary files do not accumulate.
        if curr_pano_path and prev_pano_path and prev_pano_path != curr_pano_path:
            safe_remove_file(prev_pano_path)

        prev_pano_path = curr_pano_path

start_panodpf_server()

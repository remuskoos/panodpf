import io
import os
import json
import time
import xbmc
import socket
import struct
import xbmcvfs
import xbmcaddon

from PIL import Image

PANO_TMP_FOLDER = "/tmp"

__addon__      = xbmcaddon.Addon()

full_pano_path_to_pano_slice_path = {}

def safe_remove_file(full_file_path):
    if not full_file_path:
        return

    try:
        os.remove(full_file_path)
    except EnvironmentError:
        pass


def crop_pano(im, chunk, tchunks):
    w, h = im.size
    xbmc.log("Pic size: ({0}, {1})  Crop coordinates: ({2}, {3}, {4}, {5})".format(w, h, (chunk - 1)*w/tchunks, 0, chunk*w/tchunks, h))
    cim = im.crop(((chunk - 1)*w/tchunks, 0, chunk*w/tchunks, h))
    return cim


def build_cropped_pano_path(full_pano_path, current_display, total_displays, cropped_pano_folder=PANO_TMP_FOLDER):
    pano_filename = os.path.basename(full_pano_path)
    imgname, imgext = pano_filename.split('.')
    cropped_pano_name = "{0}{1}of{2}.{3}".format(imgname, current_display, total_displays, imgext)
    return os.path.join(cropped_pano_folder, cropped_pano_name)


def crop_and_save_pano(full_pano_path, rotation, current_display, total_displays, cropped_pano_folder=PANO_TMP_FOLDER):
    pano_file = xbmcvfs.File(xbmc.translatePath(full_pano_path))
    pano_bytes_file = io.BytesIO(pano_file.readBytes())

    im = Image.open(pano_bytes_file)
    cim = crop_pano(im, current_display, total_displays)

    # Release unneeded memory right away to keep memory consumption down.
    del im
    pano_file.close()
    del pano_file
    pano_bytes_file.close()
    del pano_bytes_file

    if rotation != 1:
        rotation_angle = 90 if rotation == 0 else -90
        xbmc.log("Rotating image with size {0} 90 degrees {1}CW ...".format(cim.size, "C" if rotation == 0 else ""))
        rotated_cim = cim.rotate(rotation_angle, expand=1)
        del cim
        cim = rotated_cim

    cropped_pano_path = build_cropped_pano_path(full_pano_path, current_display, total_displays, cropped_pano_folder)
    cim.save(cropped_pano_path)

    return cropped_pano_path


def create_pano_slice(full_pano_path, rotation, current_display, total_displays):
    global full_pano_path_to_pano_slice_path

    try:
        pano_slice_path = crop_and_save_pano(full_pano_path, rotation, current_display, total_displays)
    except IOError as e:
        xbmc.log("Failed to load and/or crop pano with path '{0}': {1}.".format(full_pano_path, e), level=xbmc.LOGWARNING)
        return None, "Failed to load and/or crop pano with path '{0}'.".format(full_pano_path)

    # Save the mapping to pano_slice_path so we can retrieve it in 'display_pano'.
    full_pano_path_to_pano_slice_path = {full_pano_path: pano_slice_path}

    return pano_slice_path, ""


def get_full_pano_path_from_params(params):
    if not params:
        msg = "Invalid 'display_pano' params: '{0}'".format(params)
        xbmc.log(msg)
        return None, msg

    try:
        full_pano_path = params.get('path')
    except AttributeError as e:
        msg = "Invalid 'display_pano' params: '{0}': {1}".format(params, e)
        xbmc.log(msg)
        return None, msg

    return full_pano_path, ""


def apply_display_schedule(params, current_display, full_pano_path):
    try:
        display_schedule = params['display_schedule']
        try:
            sleep_time = display_schedule[current_display - 1]
            time.sleep(sleep_time/1000.0)
        except KeyError:
            xbmc.log("Could not get sleep time from display schedule '{0}' for display {1}. Using 0 sleep time.".format(display_schedule, current_display))
    except KeyError:
        xbmc.log("Did not get display schedule for pano '{0}'. Using 0 sleep time.".format(full_pano_path))


########################################################################################################################
# JSON RPC methods and table.                                                                                          #
def process_pano(params, current_display, total_displays):
    #xbmc.log("process_pano(params = {0}, current_display = {1}, total_displays = {2})".format(params, current_display, total_displays))
    full_pano_path, msg = get_full_pano_path_from_params(params)
    if not full_pano_path:
        return full_pano_path, msg

    rotation = params.get('rotation', 1)

    return create_pano_slice(full_pano_path, rotation, current_display, total_displays)


def display_pano(params, current_display, total_displays):
    global full_pano_path_to_pano_slice_path
    sleep_time = 0

    full_pano_path, msg = get_full_pano_path_from_params(params)
    if not full_pano_path:
        return full_pano_path, msg

    try:
        pano_slice_path = full_pano_path_to_pano_slice_path[full_pano_path]
    except KeyError:
        return None, "Could not map full pano path '{0}' to pano slice path. You need to send 'process_pano' command first.".format(full_pano_path)

    apply_display_schedule(params, current_display, full_pano_path)
    xbmc.log("Displaying pano slice {0} of {1} (path = '{2}')".format(current_display, total_displays, pano_slice_path))
    xbmc.executebuiltin("ShowPicture({0})".format(pano_slice_path))

    return pano_slice_path, ""


def turn_off_display(params, current_display, total_displays):
    os.system("vcgencmd display_power 0")
    return None, ""


def turn_on_display(params, current_display, total_displays):
    os.system("vcgencmd display_power 1")
    return None, ""


def restart(params, current_display, total_displays):
    xbmc.executebuiltin("RestartApp")
    return None, ""


def reboot(params, current_display, total_displays):
    xbmc.executebuiltin("Reboot")
    return None, ""


METHOD_TABLE = {"process_pano": process_pano,
                "display_pano": display_pano,
                "off": turn_off_display,
                "on": turn_on_display,
                "restart": restart,
                "reboot": reboot}
# End JSON RPC methods and table.                                                                                      #
########################################################################################################################


def send_reply(sock, address, reply, reply_patch=None):
    if reply_patch:
        reply.update(reply_patch)
    xbmc.log("Sending reply {0} to '{1}' ...".format(reply, address))
    sock.sendto(json.dumps(reply), address)


def process_request_and_send_reply(sock, current_pano_id):
    current_display = int(__addon__.getSetting('current_display')) + 1
    total_displays = None

    xbmc.log("Waiting to receive message ...")
    json_request, address = sock.recvfrom(2048)
    xbmc.log("Received '{0}' from {1}".format(json_request, address))
    reply = {"jsonrpc": "2.0", "result": "ERROR", "id": None, "current_display": current_display, "total_displays": None}

    try:
        request = json.loads(json_request)
    except TypeError as e:
        xbmc.log("Could not decode JSON request {0}: {1}".format(json_request, e))
        send_reply(sock, address, reply, {'error': {"code": -1, "message": "Could not decode JSON request."}})
        return None, current_pano_id

    reply['id'] = request.get('id')
    method = request.get('method')
    params = request.get('params')

    if method in ('process_pano', 'display_pano'):
        try:
            total_displays = params['total_displays']
        except KeyError:
            xbmc.log("Request did not specify the total number of displays. ")
            send_reply(sock, address, reply, {'error': {"code": -5, "message": "Request did not specify the total number of displays."}})
            return None, current_pano_id

        reply['total_displays'] = total_displays

        if request.get('id') == current_pano_id:
            send_reply(sock, address, reply, {'result': 'Duplicate'})
            return None, current_pano_id

        if current_display > total_displays:
            xbmc.log("Current display number {0} is bigger than the total number of displays {1}.".format(current_display, total_displays))
            send_reply(sock, address, reply, {'error': {"code": -6, "message": "Current display number is bigger than the total number of displays."}})
            return None, current_pano_id

    try:
        result, reason = METHOD_TABLE[method](params, current_display, total_displays)
    except KeyError:
        msg = "Invalid method '{0}'.".format(method)
        xbmc.log(msg)
        send_reply(sock, address, reply, {'error': {"code": -2, "message": msg}})
        return None, current_pano_id
    except Exception as e:
        msg = "Failed to execute method '{0}' with params '{1}': {2}".format(method, params, e)
        xbmc.log(msg)
        send_reply(sock, address, reply, {'error': {"code": -4, "message": msg}})
        return None, current_pano_id

    if method in ('process_pano', 'display_pano'):
        current_pano_id = request.get('id')

    if not result and method in ('process_pano', 'display_pano'):
        reply['error'] = {'code': -3, 'message': reason}
    else:
        reply['result'] = 'OK'

    send_reply(sock, address, reply)

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
    xbmc.log("Started multicast Pano DPF UDP server on multicast address {0} and port {1} ...".format(multicast_address, multicast_port))

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

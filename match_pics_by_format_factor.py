#!/usr/bin/python
import os
import time
import shutil
import argparse

from PIL import Image

PICTURE_EXTENSIONS = (".jpg", ".jpeg", ".tiff", ".png")

def matches_ff_rules(ff, le, ge):
    if ge > 0 and le > 0:
        return ge <= ff <= le

    if ge > 0:
        return ge <= ff

    if le:
        return ff <= le

    return False


def copy_file(full_file_path, final_folder, w, h):
    try:
        print "    Copying image '{0}' with size ({1}, {2}) to folder '{3}' ...".format(full_file_path, w, h, final_folder)
        shutil.copy(full_file_path, final_folder)
    except EnvironmentError as e:
        print "    Could not copy image '{0}' to folder '{1}': {2}".format(full_file_path, final_folder, e)


def match_pics_by_form_factor(folder, recursive, le, ge, copy_to_folder, resize_to_height):
    total_pictures = 0
    matched_pictures = 0
    start = time.time()
    for current_folder, folder_list, file_list in os.walk(folder):
        for f in file_list:
            # Check that it's a picture.
            if f.lower().endswith(PICTURE_EXTENSIONS):
                total_pictures += 1
                image_path = os.path.join(current_folder, f)
                image_object = Image.open(image_path)
                w, h = image_object.size
                ff = float(w)/h
                if matches_ff_rules(ff, le, ge):
                    print "'{0}': {1:.3}".format(image_path, ff)
                    matched_pictures += 1
                    if copy_to_folder:
                        final_folder = os.path.join(copy_to_folder, current_folder[len(folder):])
                        # Create target folders if they don't exist.
                        if not os.path.exists(final_folder):
                            os.makedirs(final_folder)

                        # If the current height of the image is less than the resize height just copy the image file.
                        if h <= resize_to_height:
                            copy_file(image_path, final_folder, w, h)
                        else:
                            resize_to_width = int(float(w * resize_to_height)/h)
                            print "    Resizing image from ({0}, {1}) to ({2}, {3}) ...".format(w, h, resize_to_width, resize_to_height)
                            resized_image_object = image_object.resize((resize_to_width, resize_to_height), resample=Image.LANCZOS)
                            final_image_path = os.path.join(final_folder, os.path.basename(image_path))
                            print "    Saving resized image to path '{0}' ...".format(final_image_path)
                            resized_image_object.save(final_image_path)

        if not recursive:
            break

    return total_pictures, matched_pictures, int(time.time() - start)


def main():
    parser = argparse.ArgumentParser(description='Filter panoramas by form factor.', epilog="At least one of '-l' or '-g' should be specified.")
    parser.add_argument("folder", type=str, help="Folder to start looking for pictures.")
    parser.add_argument("-r", "--recursive", action="store_true", default=True, help="Recurse into subfolders.")
    parser.add_argument("-l", "--less-than-or-equal", "--le", type=float, default=0, help="Form factor should be less than or equal to this valuse.")
    parser.add_argument("-g", "--greater-than-or-equal", "--ge", type=float, default=0, help="Form factor should be more than or equal to this valuse.")
    parser.add_argument("-c", "--copy-to-folder", type=str, help="Copy matched pictures to the specified folder maintaining the original folder structure.")
    parser.add_argument("-e", "--resize-to-height", type=int, help="Resize matched pictures to the specified height if current height is bigger than the specified height.")
    args = parser.parse_args()

    if args.less_than_or_equal == 0 and args.greater_than_or_equal == 0:
        parser.print_help()
        return 1

    total, matched, total_time = match_pics_by_form_factor(args.folder, args.recursive, args.less_than_or_equal, args.greater_than_or_equal, args.copy_to_folder, args.resize_to_height)
    print "Total pictures: {0}  {1} pictures: {2}  Total time: {3} s".format(total, "Copied" if args.copy_to_folder else "Matched", matched, total_time)

main()

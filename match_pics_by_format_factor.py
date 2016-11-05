#!/usr/bin/python
import os
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


def copy_file(full_file_path, target_folder, destination_folder):
    final_folder = os.path.join(target_folder, destination_folder)
    if not os.path.exists(final_folder):
        os.makedirs(final_folder)

    try:
        print "  Copying file '{0}' to folder '{1}' ...".format(full_file_path, final_folder)
        shutil.copy(full_file_path, final_folder)
    except EnvironmentError as e:
        print "Could not copy file '{0}' to folder '{1}'".format(full_file_path, final_folder)


def match_pics_by_form_factor(folder, recursive, le, ge, copy_to_folder):
    total_pictures = 0
    matched_pictures = 0
    for current_folder, folder_list, file_list in os.walk(folder):
        for f in file_list:
            # Check that it's a picture.
            if f.lower().endswith(PICTURE_EXTENSIONS):
                total_pictures += 1
                ipath = os.path.join(current_folder, f)
                w, h = Image.open(ipath).size
                ff = float(w)/h
                if matches_ff_rules(ff, le, ge):
                    print "'{0}': {1:.3}".format(ipath, ff)
                    matched_pictures += 1
                    if copy_to_folder:
                        copy_file(ipath, copy_to_folder, current_folder[len(folder):])

        if not recursive:
            break

    return total_pictures, matched_pictures


def main():
    parser = argparse.ArgumentParser(description='Filter panoramas by form factor.', epilog="At least one of '-l' or '-g' should be specified.")
    parser.add_argument("folder", type=str, help="Folder to start looking for pictures.")
    parser.add_argument("-r", "--recursive", action="store_true", default=True, help="Recurse into subfolders.")
    parser.add_argument("-l", "--less-than-or-equal", "--le", type=float, default=0, help="Form factor should be less than or equal to this valuse.")
    parser.add_argument("-g", "--greater-than-or-equal", "--ge", type=float, default=0, help="Form factor should be more than or equal to this valuse.")
    parser.add_argument("-c", "--copy-to-folder", type=str, help="Copy matched pictures to the specified folder maintaining the original folder structure.")
    args = parser.parse_args()

    if args.less_than_or_equal == 0 and args.greater_than_or_equal == 0:
        parser.print_help()
        return 1

    total, matched = match_pics_by_form_factor(args.folder, args.recursive, args.less_than_or_equal, args.greater_than_or_equal, args.copy_to_folder)
    print "Total pictures: {0}  {1} pictures: {2}".format(total, "Copied" if args.copy_to_folder else "Matched", matched)

main()

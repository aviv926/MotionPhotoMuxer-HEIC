import logging
import os
import shutil
import sys
import pyexiv2
import piexif
from os.path import exists, basename, isdir, join, splitext
from PIL import Image
from tqdm import tqdm  # for progress bar
from multiprocessing import Pool, cpu_count
import time
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

problematic_files = []
processed_files = []

problematic_files = []
processed_files = []

def validate_directory(dir):
    if not dir:
        logging.error("No directory path provided.")
        return False
    if not exists(dir):
        logging.error("Directory does not exist: {}".format(dir))
        return False
    if not isdir(dir):
        logging.error("Path is not a directory: {}".format(dir))
        return False
    return True

def validate_file(file_path):
    if not file_path:
        logging.error("No file path provided.")
        return False
    if not exists(file_path):
        logging.error("File does not exist: {}".format(file_path))
        return False
    return True

def convert_heic_to_jpeg(heic_path):
    """Converts a HEIC file to a JPEG file while copying the EXIF data."""
    logging.info("Converting HEIC file to JPEG: {}".format(heic_path))
    try:
        im = Image.open(heic_path)
        jpeg_path = splitext(heic_path)[0] + ".jpg"
        im.convert("RGB").save(jpeg_path, "JPEG")
        logging.info("HEIC file converted to JPEG: {}".format(jpeg_path))

        # Copy EXIF data from HEIC to JPEG
        exif_dict = piexif.load(heic_path)
        if exif_dict:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, jpeg_path)
            logging.info("EXIF data copied from HEIC to JPEG.")
        else:
            logging.warning("No EXIF data found in HEIC file.")

        processed_files.append(heic_path)
        return jpeg_path
    except Exception as e:
        logging.warning("Error converting HEIC file: {}: {}".format(heic_path, str(e)))
        problematic_files.append(heic_path)
        return None

def validate_media(photo_path, video_path):
    """Checks if the provided paths are valid."""
    if not validate_file(photo_path):
        logging.error("Invalid photo path.")
        return False
    if not validate_file(video_path):
        logging.error("Invalid video path.")
        return False
    if not photo_path.lower().endswith(('.jpg', '.jpeg')):
        logging.error("Photo isn't a JPEG: {}".format(photo_path))
        return False
    if not video_path.lower().endswith(('.mov', '.mp4')):
        logging.error("Video isn't a MOV or MP4: {}".format(video_path))
        return False
    return True

def merge_files(photo_path, video_path, output_path):
    """Merges the photo and video files together."""
    logging.info("Merging {} and {}.".format(photo_path, video_path))
    out_path = os.path.join(output_path, "{}".format(basename(photo_path)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as outfile, open(photo_path, "rb") as photo, open(video_path, "rb") as video:
        outfile.write(photo.read())
        outfile.write(video.read())
    logging.info("Merged photo and video.")
    processed_files.extend([photo_path, video_path])
    return out_path

def add_xmp_metadata(merged_file, offset):
    """Adds XMP metadata to the merged image."""
    metadata = pyexiv2.ImageMetadata(merged_file)
    logging.info("Reading existing metadata from file.")
    metadata.read()
    if len(metadata.xmp_keys) > 0:
        logging.warning("Found existing XMP keys. They *may* be affected after this process.")
    try:
        pyexiv2.xmp.register_namespace('http://ns.google.com/photos/1.0/camera/', 'GCamera')
    except KeyError:
        logging.warning("exiv2 detected that the GCamera namespace already exists.")
    metadata['Xmp.GCamera.MicroVideo'] = pyexiv2.XmpTag('Xmp.GCamera.MicroVideo', 1)
    metadata['Xmp.GCamera.MicroVideoVersion'] = pyexiv2.XmpTag('Xmp.GCamera.MicroVideoVersion', 1)
    metadata['Xmp.GCamera.MicroVideoOffset'] = pyexiv2.XmpTag('Xmp.GCamera.MicroVideoOffset', offset)
    metadata['Xmp.GCamera.MicroVideoPresentationTimestampUs'] = pyexiv2.XmpTag(
        'Xmp.GCamera.MicroVideoPresentationTimestampUs',
        1500000)  # in Apple Live Photos, the chosen photo is 1.5s after the start of the video
    metadata.write()

def matching_video(photo_path, video_dir):
    """Finds a matching MOV/MP4 video file for a given photo."""
    base = os.path.splitext(basename(photo_path))[0]  # Get the base name of the photo without extension
    for root, dirs, files in os.walk(video_dir):
        for file in files:
            video_base, video_ext = os.path.splitext(file)
            if video_base == base and video_ext.lower() in ['.mov', '.mp4']:
                return os.path.join(root, file)
    return None

def unique_path(destination, filename):
    """Generate a unique file path to avoid overwriting existing files."""
    base, extension = os.path.splitext(filename)
    counter = 1
    new_filename = filename
    while os.path.exists(os.path.join(destination, new_filename)):
        new_filename = f"{base}({counter}){extension}"
        counter += 1
    return os.path.join(destination, new_filename)

# New folder setup
def setup_folders(output_dir):
    """Creates necessary folders."""
    converted_heic_dir = os.path.join(output_dir, "converted HEIC")
    saved_heic_dir = os.path.join(output_dir, "saved HEIC")
    error_dir = os.path.join(output_dir, "files with errors")
    os.makedirs(converted_heic_dir, exist_ok=True)
    os.makedirs(saved_heic_dir, exist_ok=True)
    os.makedirs(error_dir, exist_ok=True)
    return converted_heic_dir, saved_heic_dir, error_dir

# Modified convert_heic_to_jpeg to save to specific folder
def convert_heic_to_jpeg(heic_path, converted_heic_dir, error_dir):
    """Converts a HEIC file to a JPEG file while copying the EXIF data."""
    logging.info("Converting HEIC file to JPEG: {}".format(heic_path))
    try:
        im = Image.open(heic_path)
        jpeg_path = os.path.join(converted_heic_dir, splitext(basename(heic_path))[0] + ".jpg")
        im.convert("RGB").save(jpeg_path, "JPEG")
        logging.info("HEIC file converted to JPEG: {}".format(jpeg_path))

        # Copy EXIF data from HEIC to JPEG
        exif_dict = piexif.load(heic_path)
        if exif_dict:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, jpeg_path)
            logging.info("EXIF data copied from HEIC to JPEG.")
        else:
            logging.warning("No EXIF data found in HEIC file.")

        processed_files.append(heic_path)
        return jpeg_path
    except Exception as e:
        logging.warning("Error converting HEIC file: {}: {}".format(heic_path, str(e)))
        problematic_files.append(heic_path)
        error_file_path = os.path.join(error_dir, basename(heic_path))
        shutil.move(heic_path, error_file_path)
        return None

def process_file(file_path, output_dir, move_other_images, convert_all_heic, delete_converted, converted_heic_dir, error_dir, saved_heic_dir):
    # Similar logic as before, now with multiprocessing support
    if file_path.lower().endswith('.heic'):
        jpeg_path = convert_heic_to_jpeg(file_path, converted_heic_dir, error_dir)
        if jpeg_path:
            video_path = matching_video(jpeg_path, output_dir)
            if video_path:
                convert(jpeg_path, video_path, output_dir)
            if delete_converted:
                os.remove(file_path)
            else:
                shutil.move(file_path, saved_heic_dir)

def process_file_wrapper(args):
    """Unpack the tuple of arguments and call process_file."""
    file, output_dir, move_other_images, convert_all_heic, delete_converted, converted_heic_dir, error_dir, saved_heic_dir = args
    return process_file(file, output_dir, move_other_images, convert_all_heic, delete_converted, converted_heic_dir, error_dir, saved_heic_dir)

def process_directory(input_dir, output_dir, move_other_images, convert_all_heic, delete_converted):
    logging.info("Processing files in: {}".format(input_dir))

    if not validate_directory(input_dir):
        logging.error("Invalid input directory.")
        sys.exit(1)

    # Set up the folders
    converted_heic_dir, saved_heic_dir, error_dir = setup_folders(output_dir)

    # Collect all files to process
    files_to_process = []
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            file_path = os.path.join(root, file)
            files_to_process.append(file_path)

    # Prepare arguments for multiprocessing
    process_args = [(file, output_dir, move_other_images, convert_all_heic, delete_converted, converted_heic_dir, error_dir, saved_heic_dir) for file in files_to_process]

    # Use multiprocessing with progress bar
    with Pool(cpu_count()) as pool:
        for _ in tqdm(pool.imap_unordered(process_file_wrapper, process_args), total=len(files_to_process)):
            pass

    logging.info("Processing complete. {} files processed.".format(len(processed_files)))

def delete_files(files):
    """Deletes a list of files."""
    for file in files:
        if exists(file):
            try:
                os.remove(file)
                logging.info(f"Deleted file: {file}")
            except Exception as e:
                logging.warning(f"Failed to delete file {file}: {str(e)}")

def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logging.info("Welcome to the Apple Live Photos to Google Motion Photos converter.")

    input_dir = input("Enter the directory path containing HEIC/JPEG/MOV/MP4 files: ").strip()
    output_dir = input("Enter the output directory path (default is 'output'): ").strip() or "output"
    move_other_images_str = input("Do you want to move non-matching files? (y/n, default is 'n'): ").strip().lower()
    convert_all_heic_str = input("Do you want to convert all HEIC files to JPEG? (y/n, default is 'n'): ").strip().lower()
    delete_converted_str = input("Do you want to delete converted HEIC files? (y/n, default is 'n'): ").strip().lower()

    move_other_images = move_other_images_str == 'y'
    convert_all_heic = convert_all_heic_str == 'y'
    delete_converted = delete_converted_str == 'y'

    process_directory(input_dir, output_dir, move_other_images, convert_all_heic, delete_converted)

if __name__ == '__main__':
    main()

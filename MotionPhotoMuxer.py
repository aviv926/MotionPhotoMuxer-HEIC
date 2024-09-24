import logging
import os
import shutil
import sys
import pyexiv2
import piexif
from os.path import exists, basename, isdir, join, splitext
from PIL import Image

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

def convert(photo_path, video_path, output_path):
    """Performs the conversion process."""
    if not validate_media(photo_path, video_path):
        logging.error("Invalid photo or video path.")
        return
    merged = merge_files(photo_path, video_path, output_path)
    photo_filesize = os.path.getsize(photo_path)
    merged_filesize = os.path.getsize(merged)
    offset = merged_filesize - photo_filesize
    add_xmp_metadata(merged, offset)

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

paired_files = []  # New list to track files with matching video pairs
converted_files = []  # Track HEIC files that were converted but don't have a matching video

def process_directory(input_dir, output_dir, move_other_images, convert_all_heic, delete_converted):
    logging.info("Processing files in: {}".format(input_dir))

    if not validate_directory(input_dir):
        logging.error("Invalid input directory.")
        sys.exit(1)

    # Ensure the output directory exists
    if not exists(output_dir):
        os.makedirs(output_dir)
        logging.info(f"Created output directory: {output_dir}")

    matching_pairs = 0
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file.lower().endswith('.heic'):
                # Convert HEIC if we are converting all or if there's a matching video
                jpeg_path = None
                if convert_all_heic or matching_video(file_path, input_dir):
                    jpeg_path = convert_heic_to_jpeg(file_path)
                
                if jpeg_path:
                    video_path = matching_video(jpeg_path, input_dir)
                    if video_path:
                        # Only merge and delete if a matching video exists
                        convert(jpeg_path, video_path, output_dir)
                        matching_pairs += 1
                        # Track paired files only
                        paired_files.extend([file_path, jpeg_path, video_path])
                    else:
                        # Track converted HEIC files that do not have a video
                        converted_files.append(file_path)
                        # **Move HEIC to other_files if no matching video exists and user opted to move them**
                        if move_other_images:
                            move_to_other_files(file_path, output_dir)

                if delete_converted and not matching_video(file_path, input_dir):
                    try:
                        os.remove(file_path)
                        logging.info(f"Deleted converted HEIC file without video: {file_path}")
                    except Exception as e:
                        logging.warning(f"Failed to delete file {file_path}: {str(e)}")

            elif file.lower().endswith(('.jpg', '.jpeg')):
                video_path = matching_video(file_path, input_dir)
                if video_path:
                    # Only merge and delete JPEG if a matching video exists
                    convert(file_path, video_path, output_dir)
                    matching_pairs += 1
                    paired_files.extend([file_path, video_path])
                    if delete_converted:
                        delete_files([file_path, video_path])

    logging.info("Conversion complete.")
    logging.info("Found {} matching HEIC/JPEG and MOV/MP4 pairs.".format(matching_pairs))

    # Move non-matching files to 'other_files' folder
    if move_other_images:
        other_files_dir = os.path.join(output_dir, "other_files")
        os.makedirs(other_files_dir, exist_ok=True)
        for root, dirs, files in os.walk(input_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if file_path not in processed_files and file_path not in paired_files:
                    unique_file_path = unique_path(other_files_dir, basename(file_path))
                    shutil.move(file_path, unique_file_path)
                    logging.info(f"Moved {file_path} to {unique_file_path}")

    logging.info("Cleanup complete.")
    
def move_to_other_files(file_path, output_dir):
    """Move HEIC file to 'other_files' folder in the output directory."""
    other_files_dir = os.path.join(output_dir, "other_files")
    os.makedirs(other_files_dir, exist_ok=True)
    unique_file_path = unique_path(other_files_dir, basename(file_path))
    shutil.move(file_path, unique_file_path)
    logging.info(f"Moved {file_path} to {unique_file_path}")


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

    # Prompt for directories
    input_dir = input("Enter the directory path containing HEIC/JPEG/MOV/MP4 files in the same folder or subfolders: ").strip()

    if not validate_directory(input_dir):
        logging.error("Invalid directory path.")
        sys.exit(1)

    # Prompt for output directory
    output_dir = input("Enter the output directory path (default is 'output'): ").strip() or "output"

    # Prompt for moving other images
    move_other_images_str = input("Do you want to move non-matching files to the 'other_files' folder in the output directory? (y/n, default is 'n'): ").strip().lower()
    move_other_images = move_other_images_str == 'y'

    # Prompt for converting all HEIC files to JPEG
    convert_all_heic_str = input("Do you want to convert all HEIC files to JPEG, regardless of whether they have a matching MOV/MP4 file? (y/n, default is 'n'): ").strip().lower()
    convert_all_heic = convert_all_heic_str == 'y'

    # Prompt for deleting converted files
    delete_converted_str = input("Do you want to delete converted HEIC files whether they have a matching MOV/MP4 file or not? (y/n, default is 'n'): ").strip().lower()
    delete_converted = delete_converted_str == 'y'

    # Perform the conversion
    process_directory(input_dir, output_dir, move_other_images, convert_all_heic, delete_converted)

    # Output summary of problematic files
    if problematic_files:
        logging.warning("The following files encountered errors during conversion:")
        for file_path in problematic_files:
            logging.warning(file_path)

        # Write summary to a file
        with open("problematic_files.txt", "w") as f:
            f.write("The following files encountered errors during conversion:\n")
            for file_path in problematic_files:
                f.write(file_path + "\n")

    # Prompt for deleting original files
    delete_original_str = input("Do you want to delete the original HEIC and MOV/MP4 files? If not, they will be saved. (y/n, default is 'n'): ").strip().lower()
    delete_original = delete_original_str == 'y'

    if delete_original:
        delete_files(paired_files)  # Only delete paired files
    else:
        logging.info("Original HEIC and MOV/MP4 files will be saved.")


if __name__ == '__main__':
    main()

import logging
import math
import os

import ffmpeg
from PIL import Image
from src.video_processor.google_generative_ai import generate_video_tags

logging.basicConfig(level=logging.DEBUG)


output_dir = "compressed_videos"  # Local directory when not in Docker
merged_output_dir = "merged_videos"  # Local directory when not in Docker


# Create the output directories
os.makedirs(output_dir, exist_ok=True)
os.makedirs(merged_output_dir, exist_ok=True)


class VideoProcessor:

    def cleanup_files(files):
        """Delete the specified files."""
        for file in files:
            try:
                os.remove(file)
                logging.info(f"Deleted file: {file}")
            except Exception as e:
                logging.error(f"Error deleting file {file}: {e}")


    async def create_image_grid(images, output_path):
        """Create a grid of images with an automatically adjusted size and save the result."""
        try:
            num_images = len(images)
            grid_size = VideoProcessor.calculate_grid_size(num_images)

            # Open the first image to get dimensions
            with Image.open(images[0]) as img:
                width, height = img.size

            # Calculate grid dimensions
            grid_width = grid_size[0] * width
            grid_height = grid_size[1] * height

            # Create a blank image with grid dimensions
            grid_image = Image.new("RGB", (grid_width, grid_height))

            for index, image_path in enumerate(images):
                with Image.open(image_path) as img:
                    x = (index % grid_size[0]) * width
                    y = (index // grid_size[0]) * height
                    grid_image.paste(img, (x, y))

            grid_image.save(output_path)
            logging.info(f"Grid image saved at: {output_path}")
            return output_path
        except Exception as e:
            logging.error(f"Error creating image grid: {e}")
            return None


    def calculate_grid_size(num_images):
        """Calculate the optimal grid size (columns, rows) for a given number of images."""
        columns = math.ceil(math.sqrt(num_images))  # Number of columns in the grid
        rows = math.ceil(num_images / columns)  # Number of rows in the grid
        return columns, rows


    async def resize_images(input_files, target_size=(640, 480)):
        """Resize images to the target size and save them to the specified directory."""
        resized_files = []
        os.makedirs(
            merged_output_dir, exist_ok=True
        )  # Create the output directory if it doesn't exist

        for file in input_files:
            try:
                with Image.open(file) as img:
                    img = img.resize(target_size, Image.Resampling.LANCZOS)
                    # Create a new filename in the output directory
                    resized_file = os.path.join(
                        merged_output_dir,
                        f"{os.path.basename(file).replace('.jpg', '_resized.jpg').replace('.png', '_resized.png')}",
                    )
                    img.save(resized_file)
                    resized_files.append(resized_file)
                    logging.info(f"Resized image saved at: {resized_file}")
            except Exception as e:
                logging.error(f"Error resizing image {file}: {e}")
        return resized_files


    async def process_videos(data):
        try:
            job_id = data.get("data", {}).get("jobId", "unknown")
            files = data.get("data", {}).get("files", [])
            compressed_files = []

            if not files:
                logging.error("No files to process")
                return {"error": "No valid files found in the data"}

            for file in files:
                file_url = file.get("lite", "")
                if file["fileType"] == "video" and file_url:
                    compressed_file_path = os.path.join(
                        output_dir, f"{file['name']}_compressed.mp4"
                    )
                    try:
                        ffmpeg.input(file_url).output(
                            compressed_file_path,
                            vf="scale=640:-1,fps=15",
                            video_bitrate="400k",
                            audio_bitrate="64k",
                            vcodec="libx265",
                        ).overwrite_output().run(quiet=True)
                        compressed_files.append(compressed_file_path)
                    except ffmpeg.Error as e:
                        logging.error(
                            f"Error compressing video {file['name']}: {e.stderr.decode()}"
                        )

                elif file["fileType"] == "image" and file_url:
                    compressed_file_path = os.path.join(
                        output_dir, f"{file['name']}_compressed.jpg"
                    )
                    try:
                        ffmpeg.input(file_url).output(
                            compressed_file_path, vf="scale=640:-1", qscale=2
                        ).overwrite_output().run(quiet=True)
                        compressed_files.append(compressed_file_path)
                    except ffmpeg.Error as e:
                        logging.error(
                            f"Error compressing image {file['name']}: {e.stderr.decode()}"
                        )

            # Check the number of compressed files
            if not compressed_files:
                return {"error": "No valid video or image files to process."}

            # Handle case with one file
            if len(compressed_files) == 1:
                try:
                    tags = generate_video_tags(compressed_files[0], data)
                    return {
                        "jobId": job_id,
                        "tags": tags,
                        "compressed_file_path": compressed_files[0],
                    }
                except Exception as e:
                    logging.error(
                        f"Error generating tags for {compressed_files[0]}: {str(e)}"
                    )
                    return {"error": str(e)}
            elif len(compressed_files) >= 2:
                print(len(compressed_files))

                if all(file.endswith(".mp4") for file in compressed_files):
                    merged_file_path = os.path.join(
                        merged_output_dir, f"{job_id}_merged.mp4"
                    )
                    # Create a temporary file to list the input videos
                    concat_file_path = os.path.join(merged_output_dir, "concat_files.txt")

                    try:
                        # Write the list of files to a temporary text file
                        with open(concat_file_path, "w") as f:
                            for video in compressed_files:
                                f.write(
                                    f"file '{video}'\n"
                                )  # Use single quotes for the file paths

                        # Use the concat demuxer to merge the videos
                        ffmpeg.input(
                            concat_file_path.replace(merged_output_dir + "/", ""),
                            format="concat",
                        ).output(
                            merged_file_path, vcodec="libx265", acodec="aac"
                        ).overwrite_output().run(
                            quiet=True
                        )

                        # Generate tags after merging
                        tags = generate_video_tags(merged_file_path, data)
                        return {
                            "jobId": job_id,
                            "tags": tags,
                            "merged_video_path": merged_file_path,
                        }
                    except ffmpeg.Error as e:
                        logging.error(f"Error merging videos: {e.stderr.decode()}")
                        return {"error": str(e.stderr.decode())}
                    finally:
                        if os.path.exists(concat_file_path):
                            os.remove(concat_file_path)
                            os.remove(merged_file_path)
                elif all(
                    file.endswith(tuple([".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"]))
                    for file in compressed_files
                ):
                    grid_output_path = os.path.join(merged_output_dir, f"{job_id}_grid.jpg")

                    resized_files = await VideoProcessor.resize_images(compressed_files)

                    # Create a grid of images automatically based on the number of images
                    grid_image_path = await VideoProcessor.create_image_grid(
                        resized_files, grid_output_path
                    )

                    if grid_image_path:
                        try:
                            tags = generate_video_tags(grid_image_path, data)
                            return {
                                "jobId": job_id,
                                "tags": tags,
                                "compressed_file_path": grid_image_path,
                            }
                        except Exception as e:
                            logging.error(
                                f"Error generating tags for {grid_image_path}: {str(e)}"
                            )
                            return {"error": str(e)}
                        finally:
                            if os.path.exists(grid_image_path):
                                os.remove(grid_image_path)
                    else:
                        return {"error": "Failed to create image grid."}

            else:
                return {"error": "Mixed file types found; cannot process."}

        except Exception as e:
            logging.error(f"Error processing video data: {str(e)}")
            return {"error": str(e)}
        finally:
            # Cleanup: delete all compressed files
            VideoProcessor.cleanup_files(compressed_files)

            # If there were resized images, clean them up as well
            if "resized_files" in locals():
                VideoProcessor.cleanup_files(resized_files)

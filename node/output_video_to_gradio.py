import os
import numpy as np
from PIL import Image, PngImagePlugin
import folder_paths
from .hua_icons import icons
import json
import imageio  # used for GIF/WebP encoding
import subprocess
import sys
import datetime
import re
import torch
import itertools
# Try to import LoraLoader for potential VAE inputs; ignore if unavailable
try:
    from nodes import LoraLoader
except ImportError:
    print("Unable to import nodes.LoraLoader; VAE-related features (if added later) may be limited.")

# Try to import VideoHelperSuite's LazyAudioMap; fall back gracefully if missing
try:
    from comfyui_videohelpersuite.videohelpersuite.utils import LazyAudioMap
    print("Imported LazyAudioMap from comfyui_videohelpersuite.")
    HAS_LAZY_AUDIO_MAP = True
except ImportError:
    print("Unable to import LazyAudioMap from comfyui_videohelpersuite. Only dict-based audio will be supported.")
    LazyAudioMap = None  # define as None so isinstance checks fail safely
    HAS_LAZY_AUDIO_MAP = False

# --- Constants and Setup ---
OUTPUT_DIR = folder_paths.get_output_directory()
TEMP_DIR = folder_paths.get_temp_directory()
os.makedirs(TEMP_DIR, exist_ok=True) # ensure temp directory exists

# --- FFMPEG Path ---
ffmpeg_path = "ffmpeg" # default to system ffmpeg
try:
    # Try FFMPEG_PATH environment variable
    ffmpeg_path_env = os.getenv("FFMPEG_PATH")
    if ffmpeg_path_env and os.path.exists(ffmpeg_path_env):
        ffmpeg_path = ffmpeg_path_env
        print(f"Using FFMPEG_PATH: {ffmpeg_path}")
    else:
        # Fallback to imageio_ffmpeg if env var invalid or unset
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"Found FFmpeg via imageio_ffmpeg: {ffmpeg_path}")
except Exception as e:
    print(f"Failed to resolve FFmpeg via env or imageio_ffmpeg ({e}); trying system 'ffmpeg'.")
    # Check whether ffmpeg is available on the system PATH
    try:
        result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
        print(f"'ffmpeg' is available on PATH. Version snippet:\n{result.stdout[:100]}...")
    except FileNotFoundError:
        print("Error: 'ffmpeg' not found on PATH. Non-GIF/WebP video and audio merge unavailable.")
        print("Install ffmpeg (PATH), set FFMPEG_PATH, or `pip install 'imageio[ffmpeg]'`.")
        ffmpeg_path = None  # explicitly mark as unavailable
    except Exception as check_e:
         print(f"Error checking system 'ffmpeg': {check_e}")
         ffmpeg_path = None  # also mark as unavailable on error


# --- Helper Functions (Simplified from VHS) ---

def tensor_to_bytes(tensor):
    """Converts a torch tensor (H, W, C) to a numpy uint8 array."""
    if tensor.dim() > 3: # handle B,H,W,C -> H,W,C
        tensor = tensor[0]
    # Ensure CPU float for scaling
    if tensor.is_cuda:
        tensor = tensor.cpu()
    if tensor.dtype != torch.float32 and tensor.dtype != torch.float64:
         # try float32
         try:
             tensor = tensor.float()
         except Exception as e:
             print(f"Warning: tensor->float conversion failed: {e}. Trying direct numpy conversion.")

    # Convert to numpy array
    try:
        i = 255. * tensor.numpy()
    except TypeError as e:
         print(f"Error: tensor->numpy conversion failed: {e}. Tensor dtype: {tensor.dtype}")
         # Fallback to black pixel array; assume (H,W,C) else (1,1,3)
         shape = tensor.shape if len(tensor.shape) == 3 else (1, 1, 3)
         return np.zeros(shape, dtype=np.uint8)

    img = np.clip(i, 0, 255).astype(np.uint8)
    return img

def to_pingpong(images_iterator):
    """Creates a ping-pong (forward and backward) sequence from an image iterator."""
    images_list = list(images_iterator) # materialize iterator
    if len(images_list) > 1:
        # Exclude the first and last frames from the reversed part to avoid duplication
        return itertools.chain(images_list, reversed(images_list[1:-1]))
    else:
        return iter(images_list)

# --- Main Node Class ---

class Hua_Video_Output:
    def __init__(self):
        self.output_dir = OUTPUT_DIR
        self.temp_dir = TEMP_DIR
        self.type = "output"

    @classmethod
    def INPUT_TYPES(cls):
        # Provide additional encoder options, including H.265 (HEVC)
        supported_formats = [
            "image/gif", "image/webp", "video/mp4", "video/webm", "video/mp4-hevc", "video/avi", "video/mkv"
        ]
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The image frames to save as video/animated image."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI_Video", "tooltip": "Prefix for the saved file."}),
                "frame_rate": ("FLOAT", {"default": 24.0, "min": 0, "step": 1}),
                "format": (supported_formats, {"default": "video/mp4", "tooltip": "Output format."}),
                "unique_id": ("STRING", {"default": "default_video_id", "multiline": False, "tooltip": "Unique ID for this execution provided by Gradio."}),
                "name": ("STRING", {"multiline": False, "default": "Hua_Video_Output", "tooltip": "Node name"}),
            },
            "optional": {
                "loop_count": ("INT", {"default": 0, "min": 0, "max": 100, "step": 1, "tooltip": "Number of loops (0 for infinite loop). GIF/WebP only."}),
                "pingpong": ("BOOLEAN", {"default": False, "tooltip": "Enable ping-pong playback (forward then backward)."}),
                "save_output": ("BOOLEAN", {"default": True, "tooltip": "Save the file in the output directory (True) or temp directory (False)."}),
                "audio": ("AUDIO", {"tooltip": "Optional audio to combine with the video (requires ffmpeg)."}),
                "crf": ("INT", {"default": 23, "min": 0, "max": 51, "step": 1, "tooltip": "Constant Rate Factor (lower value means higher quality, larger file). For MP4/WebM/HEVC."}),
                "preset": (["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"], {"default": "fast", "tooltip": "Encoding preset (faster presets mean lower quality/compression). For MP4/HEVC."}),
                # "save_metadata_png": ("BOOLEAN", {"default": True, "tooltip": "Save a PNG file containing the metadata alongside the video/gif."}), # Removed based on user feedback
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ()

    FUNCTION = "output_video_gradio"
    OUTPUT_NODE = True
    CATEGORY = icons.get("hua_boy_one")

    def output_video_gradio(self, images, filename_prefix, frame_rate, format, unique_id,
                             loop_count=0, pingpong=False, save_output=True, audio=None, crf=23,
                             preset="fast", prompt=None, extra_pnginfo=None): # Removed save_metadata_png parameter

        num_frames = 0
        if images is not None:
            if isinstance(images, torch.Tensor):
                num_frames = images.size(0)
            elif isinstance(images, list):
                if all(isinstance(img, torch.Tensor) for img in images):
                    num_frames = len(images)
                else:
                    print("Error: 'images' list contains non-Tensor elements.")
                    self._write_error_to_json(unique_id, "Input list contains non-Tensor elements.")
                    return ()
            else:
                print(f"Warning: Unknown 'images' type: {type(images)}; treating as empty input.")

        if num_frames == 0:
            print("Error: No image frames provided.")
            self._write_error_to_json(unique_id, "No input frames.")
            return self._create_error_result("No input frames.")

        # --- Determine Output Path ---
        output_dir = self.output_dir if save_output else self.temp_dir
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            full_output_folder = output_dir
            filename_pattern = f"{filename_prefix}_{timestamp}"

        except Exception as e:
            print(f"Error: Failed to configure save path: {e}")
            self._write_error_to_json(unique_id, f"Error setting save path: {e}")
            return self._create_error_result(f"Error setting save path: {e}")

        # --- Prepare Frames ---
        try:
            # Iterator approach to reduce memory; num_frames computed above
            frames_iterator = (tensor_to_bytes(images[i]) for i in range(num_frames))

            # Get first frame to determine size and alpha
            first_frame_np = tensor_to_bytes(images[0])
            height, width, channels = first_frame_np.shape
            has_alpha = channels == 4
            print(f"Video frame size: {width}x{height}, Alpha: {has_alpha}, Total frames: {num_frames}")
        except Exception as e:
            print(f"Error: preparing image frames failed: {e}")
            self._write_error_to_json(unique_id, f"Error preparing image frames: {e}")
            return self._create_error_result(f"Error preparing image frames: {e}")

        # --- Prepare Metadata (Similar to VHS) ---
        metadata = PngImagePlugin.PngInfo()
        video_metadata_dict = {} # for ffmpeg -metadata
        if prompt is not None:
            try:
                prompt_str = json.dumps(prompt)
                metadata.add_text("prompt", prompt_str)
                video_metadata_dict["prompt"] = prompt_str
            except Exception as e:
                 print(f"Warning: cannot serialize prompt to metadata: {e}")
        if extra_pnginfo is not None:
            for k, v in extra_pnginfo.items():
                try:
                    # Convert values to string to avoid ffmpeg issues
                    v_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    metadata.add_text(k, v_str)
                    clean_k = re.sub(r'[^\w.-]', '_', str(k))
                    clean_v = v_str.replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\\', '\\\\').replace('\n', ' ')
                    if len(clean_k) > 0 and len(clean_v) < 256:
                        video_metadata_dict[clean_k] = clean_v
                except Exception as e:
                    print(f"Warning: cannot serialize extra_pnginfo '{k}' to metadata: {e}")
        metadata.add_text("CreationTime", datetime.datetime.now().isoformat(" ")[:19])
        video_metadata_dict["creation_time"] = datetime.datetime.now().isoformat(" ")[:19]


        # --- Save Metadata PNG (Optional) --- # Removed based on user feedback
        # png_filepath = None
        # if save_metadata_png:
        #     png_filename = f"{filename_pattern}_metadata.png"
        #     png_filepath = os.path.join(full_output_folder, png_filename)
        #     try:
        #         Image.fromarray(first_frame_np).save(
        #             png_filepath,
        #             pnginfo=metadata,
        #             compress_level=4,
        #         )
        #     except Exception as e:
        #         print(f"Warning: Failed to save metadata PNG: {e}")

        # --- Process Based on Format ---
        output_filepath = None
        final_paths_for_json = []
        #      final_paths_for_json.append(png_filepath)

        format_type, format_ext = format.split("/")

        # --- Apply Pingpong if needed (before iterator consumed) ---
        if pingpong:
            print("Applying pingpong...")
            frames_list_for_pingpong = [tensor_to_bytes(images[i]) for i in range(num_frames)]
            if len(frames_list_for_pingpong) > 1:
                frames_iterator = itertools.chain(frames_list_for_pingpong, reversed(frames_list_for_pingpong[1:-1]))
                num_frames = len(frames_list_for_pingpong) + max(0, len(frames_list_for_pingpong) - 2)
                print(f"Pingpong effective frames: {num_frames}")
            else:
                frames_iterator = iter(frames_list_for_pingpong)
        else:
            # If not pingpong, recreate original iterator
            frames_iterator = (tensor_to_bytes(images[i]) for i in range(num_frames))


        if format_type == "image" and format_ext in ["gif", "webp"]:
            # --- Save Animated Image using imageio ---
            ext = format_ext
            output_filename = f"{filename_pattern}.{ext}"
            output_filepath = os.path.join(full_output_folder, output_filename)

            try:
                # imageio requires a frame list
                frames_list = list(frames_iterator)
                if not frames_list:
                     raise ValueError("Frame list is empty; cannot create animation.")

                print(f"Saving {ext.upper()} to: {output_filepath}")
                duration_sec = 1.0 / frame_rate
                kwargs = {'duration': duration_sec, 'loop': loop_count}
                if ext == 'webp':
                    kwargs['lossless'] = True
                    kwargs['quality'] = 100
                elif ext == 'gif':
                    kwargs['palettesize'] = 256

                imageio.mimsave(output_filepath, frames_list, format=ext.upper(), **kwargs)
                print(f"{ext.upper()} saved successfully.")
                final_paths_for_json.append(output_filepath)

            except Exception as e:
                print(f"Error: saving {ext.upper()} via imageio failed: {e}")
                self._write_error_to_json(unique_id, f"Error saving {ext.upper()}: {e}", final_paths_for_json)
                return self._create_error_result(f"Error saving {ext.upper()}: {e}", final_paths_for_json)

        elif format_type == "video" and ffmpeg_path:
            # --- Save Video using FFmpeg ---
            ext = format_ext # mp4, webm, etc.
            output_filename = f"{filename_pattern}.{ext}"
            output_filepath = os.path.join(full_output_folder, output_filename)
            temp_audio_path = None

            # --- Basic FFmpeg Command ---
            input_args = [
                "-f", "rawvideo",
                "-pix_fmt", "rgba" if has_alpha else "rgb24",
                "-s", f"{width}x{height}",
                "-r", str(frame_rate),
                "-i", "-",
            ]

            output_args = []

            if ext == "mp4":
                output_args.extend(["-c:v", "libx264"])
                output_args.extend(["-crf", str(crf)]) # H.264 CRF
                if has_alpha:
                    print("Warning: MP4 does not support native alpha; using yuv420p (alpha discarded).")
                    output_args.extend(["-vf", "format=pix_fmts=yuv420p"])
                    output_args.extend(["-pix_fmt", "yuv420p"])
                else:
                    output_args.extend(["-pix_fmt", "yuv420p"])
                output_args.extend(["-preset", preset])
                output_args.extend(["-c:a", "aac", "-b:a", "192k"])
            elif ext == "webm":
                output_args.extend(["-c:v", "libvpx-vp9"])
                output_args.extend(["-crf", str(crf)]) # VP9 CRF
                output_args.extend(["-b:v", "0"])
                if has_alpha:
                    output_args.extend(["-pix_fmt", "yuva420p"])
                    output_args.extend(["-auto-alt-ref", "0"])
                    print("WebM format selected; alpha channel will be preserved.")
                else:
                    output_args.extend(["-pix_fmt", "yuv420p"])
                output_args.extend(["-c:a", "libopus", "-b:a", "128k"])
            elif ext == "mp4-hevc":
                print("Using HEVC (H.265) encoder.")
                output_args.extend(["-c:v", "libx265"])
                output_args.extend(["-crf", str(crf)]) # H.265 CRF
                output_args.extend(["-preset", preset])
                output_args.extend(["-tag:v", "hvc1"])
                if has_alpha:
                    print("Warning: HEVC (H.265) has limited alpha support; using yuv420p (alpha discarded).")
                    output_args.extend(["-pix_fmt", "yuv420p"])
                else:
                    output_args.extend(["-pix_fmt", "yuv420p"])
                output_args.extend(["-c:a", "aac", "-b:a", "192k"])
            else:
                print(f"Warning: Unknown video format '{format}'. Falling back to H.264.")
                ext = "mp4"
                output_filename = f"{filename_pattern}.{ext}"
                output_filepath = os.path.join(full_output_folder, output_filename)
                output_args.extend(["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p"])
                output_args.extend(["-c:a", "aac", "-b:a", "192k"])


            audio_input_args = []
            audio_map_args = []
            a_waveform = None
            sample_rate = None
            temp_audio_path = None

            if audio is not None:
                print(f"Received audio input of type: {type(audio)}")
                try:
                    print("Attempting dictionary access to audio['waveform'] and audio['sample_rate']...")
                    if hasattr(audio, '__getitem__'):
                        a_waveform = audio['waveform']
                        sample_rate = audio['sample_rate']
                        print(f"Successfully extracted waveform (type: {type(a_waveform)}) and sample_rate ({sample_rate}) from dict.")
                    else:
                         print(f"Audio input object (type: {type(audio)}) does not support dict access; ignoring audio.")
                         a_waveform = None
                         sample_rate = None


                    if a_waveform is not None and sample_rate is not None:
                        if a_waveform.nelement() > 0:
                            print(f"Validated audio: sample_rate {sample_rate}, waveform shape {a_waveform.shape}, dtype {a_waveform.dtype}")
                            channels = a_waveform.size(1)
                            temp_audio_filename = f"temp_audio_{unique_id}.raw"
                            temp_audio_path = os.path.join(self.temp_dir, temp_audio_filename)
                            print(f"Preparing to write temporary audio file: {temp_audio_path}")
                            try:
                                # waveform shape is (1, channels, samples), squeeze to (channels, samples)
                                # transpose to (samples, channels), then flatten and convert to bytes
                                waveform_cpu = a_waveform.squeeze(0).transpose(0, 1).contiguous().cpu()
                                if waveform_cpu.dtype != torch.float32:
                                    print(f"Warning: Audio waveform dtype is {waveform_cpu.dtype}; attempting float32 conversion.")
                                    waveform_cpu = waveform_cpu.float()
                                audio_data_bytes = waveform_cpu.numpy().tobytes()
                                with open(temp_audio_path, 'wb') as f_audio:
                                    f_audio.write(audio_data_bytes)
                                print(f"Temporary audio file written successfully, size: {len(audio_data_bytes)} bytes")
                            except Exception as write_e:
                                print(f"Error: Failed to write temporary audio file: {write_e}")
                                temp_audio_path = None
                                a_waveform = None

                            if temp_audio_path and a_waveform is not None:
                                audio_input_args = [
                                    "-f", "f32le",
                                    "-ar", str(sample_rate),
                                    "-ac", str(channels),
                                    "-i", temp_audio_path,
                                ]
                                audio_map_args = ["-map", "0:v", "-map", "1:a"]
                        else: # a_waveform.nelement() == 0
                            print("Provided audio waveform is empty; ignoring audio.")
                            a_waveform = None

                except (KeyError, TypeError) as e:
                    print(f"Error accessing audio data (type: {type(audio)}): {e}. Missing keys or incompatible type; ignoring audio.")
                    a_waveform = None
                    sample_rate = None
                except Exception as e:
                    print(f"Unexpected error while handling audio; ignoring audio: {e}")
                    a_waveform = None
                    sample_rate = None
                    if temp_audio_path and os.path.exists(temp_audio_path):
                        try:
                            os.remove(temp_audio_path)
                            print(f"Removed partially written temp audio file: {temp_audio_path}")
                        except OSError: pass
                    temp_audio_path = None

            if a_waveform is not None and temp_audio_path is not None and os.path.exists(temp_audio_path):
                print("Audio validated; configuring audio/video stream mapping.")
            else:
                audio_map_args = ["-map", "0:v"]
                if audio is not None:
                    print("Audio will be ignored; outputting video only.")

            command = [ffmpeg_path, "-y"]
            command.extend(input_args)

            print("Diagnostics: temporarily disabling audio processing to test video stability.")
            # if audio_input_args:
            command.extend(output_args)
            command.extend(["-map", "0:v"])

            for k, v in video_metadata_dict.items():
                 command.extend(["-metadata", f"{k}={v}"])

            # if a_waveform is not None:

            command.append(output_filepath)

            full_command_str = ' '.join(command)
            print(f"Executing FFmpeg command: {full_command_str}")

            process = None
            try:
                print("Launching FFmpeg subprocess...")
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
                print(f"FFmpeg subprocess started (PID: {process.pid}); streaming frames...")

                frame_count = 0
                for frame_bytes in frames_iterator:
                    try:
                        process.stdin.write(frame_bytes.tobytes())
                        frame_count += 1
                    except (IOError, BrokenPipeError) as e:
                        print(f"Warning: Error writing to ffmpeg stdin at frame {frame_count} (process may have exited early): {e}")
                        break

                print(f"Wrote {frame_count} frame(s) to ffmpeg.")

                print("All frames written; waiting for FFmpeg via communicate().")

                timeout_seconds = 300
                try:
                    stdout, stderr = process.communicate(input=None, timeout=timeout_seconds)
                    return_code = process.returncode
                    print(f"FFmpeg communicate() finished with return code {return_code}.")
                except subprocess.TimeoutExpired:
                    print(f"Error: FFmpeg did not finish within {timeout_seconds} seconds; terminating.")
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        print("Error: communicate() timed out even after termination.")
                        stdout, stderr = b"", b""
                    except Exception as comm_err_after_term:
                        print(f"Error: communicate() failed after termination: {comm_err_after_term}")
                        stdout, stderr = b"", b""
                    return_code = -999
                    self._write_error_to_json(unique_id, f"FFmpeg timed out after {timeout_seconds} seconds.", final_paths_for_json)
                    if temp_audio_path and os.path.exists(temp_audio_path):
                        try: os.remove(temp_audio_path)
                        except OSError as e_clean: print(f"Warning: Failed to clean up temporary audio file: {e_clean}")
                    return self._create_error_result(f"FFmpeg timed out after {timeout_seconds} seconds.", final_paths_for_json)

                stdout_str = stdout.decode('utf-8', errors='ignore')
                stderr_str = stderr.decode('utf-8', errors='ignore')

                print(f"FFmpeg process finished. Return code: {return_code}")
                print("--- FFmpeg stderr ---")
                print(stderr_str if stderr_str else "[no stderr output]")
                print("---------------------")
                if stdout_str:
                    print("--- FFmpeg stdout ---")
                    print(stdout_str)
                    print("---------------------")


                if return_code == 0:
                    print(f"FFmpeg succeeded; video saved to: {output_filepath}")
                    final_paths_for_json.append(output_filepath)
                    if not os.path.exists(output_filepath) or os.path.getsize(output_filepath) == 0:
                         print(f"Warning: FFmpeg returned 0 but output file '{output_filepath}' missing or empty.")
                         self._write_error_to_json(unique_id, f"FFmpeg reported success but output file is missing or empty.", final_paths_for_json)
                         if temp_audio_path and os.path.exists(temp_audio_path):
                             try: os.remove(temp_audio_path)
                             except OSError as e_clean: print(f"Warning: Failed to clean up temporary audio file: {e_clean}")
                         return self._create_error_result(f"FFmpeg reported success but output file is missing or empty.", final_paths_for_json)
                else:
                    print(f"Error: FFmpeg failed (return code: {return_code})")
                    self._write_error_to_json(unique_id, f"FFmpeg execution failed (code {return_code}). Check logs for details.", final_paths_for_json)
                    if temp_audio_path and os.path.exists(temp_audio_path):
                        try: os.remove(temp_audio_path)
                        except OSError as e_clean: print(f"Warning: failed to cleanup temp audio: {e_clean}")
                    return self._create_error_result(f"FFmpeg execution failed (code {return_code}). Check logs for details.", final_paths_for_json)

            except Exception as e:
                print(f"Error: Python exception while executing FFmpeg: {e}")
                if process and process.poll() is None:
                    process.terminate()
                self._write_error_to_json(unique_id, f"FFmpeg execution error: {e}", final_paths_for_json)
                if temp_audio_path and os.path.exists(temp_audio_path):
                    try:
                        os.remove(temp_audio_path)
                    except OSError as e_clean:
                        print(f"Warning: failed to cleanup temp audio: {e_clean}")
                return self._create_error_result(f"FFmpeg execution error: {e}", final_paths_for_json)
            finally:
                 # Ensure final cleanup of temp audio
                 if temp_audio_path and os.path.exists(temp_audio_path):
                     try:
                         os.remove(temp_audio_path)
                         print(f"Cleaned temp audio file: {temp_audio_path}")
                     except OSError as e_clean:
                         print(f"Warning: failed to cleanup temp audio: {e_clean}")


        elif not ffmpeg_path and format_type == "video":
            print(f"Error: ffmpeg required to create {format} video but not found.")
            self._write_error_to_json(unique_id, "FFmpeg not found, cannot create video format.", final_paths_for_json)
            return self._create_error_result("FFmpeg not found, cannot create video format.", final_paths_for_json)
        else:
            print(f"Error: unsupported format '{format}'.")
            self._write_error_to_json(unique_id, f"Unsupported format: {format}", final_paths_for_json)
            return self._create_error_result(f"Unsupported format: {format}", final_paths_for_json)

        # --- Write JSON and return result to frontend ---
        if output_filepath and os.path.exists(output_filepath):
            # --- Write success JSON ---
            temp_json_path = os.path.join(self.temp_dir, f"{unique_id}.json")
            try:
                # Write generated files list to JSON
                success_data = {"generated_files": final_paths_for_json}
                with open(temp_json_path, 'w', encoding='utf-8') as f:
                    json.dump(success_data, f, indent=4)
                print(f"Final file paths written to temp JSON (for Gradio): {temp_json_path}")
                print(f"Paths: {final_paths_for_json}")

                # Validate that files exist
                all_exist = True
                for path in final_paths_for_json:
                    if not os.path.exists(path):
                        print(f"Error: output file missing: {path}")
                        all_exist = False
                if not all_exist:
                     # Report missing files even if JSON write succeeded
                     self._write_error_to_json(unique_id, "One or more output files missing after generation.", final_paths_for_json)
                     return self._create_error_result("One or more output files missing after generation.", final_paths_for_json)

            except Exception as e:
                print(f"Error: failed to write temp JSON ({temp_json_path}): {e}")
                self._write_error_to_json(unique_id, f"Failed to write result JSON: {e}", final_paths_for_json)
                return self._create_error_result(f"Failed to write result JSON: {e}", final_paths_for_json)

            # --- Prepare result dict for ComfyUI frontend ---
            file_type = "output" if save_output else "temp"
            filename = os.path.basename(output_filepath)
            subfolder = ""

            print(f"Preparing frontend result: filename={filename}, subfolder={subfolder}, type={file_type}")

            result = {
                "ui": {
                    "videos": [{
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": file_type
                    }]
                }
            }
            return result
            # --- End prepare frontend result ---
        else:
            # If no valid output file, write error JSON and return error
            print("No valid output file generated; writing error JSON and returning error.")
            error_msg = "Failed to generate output file."
            if not final_paths_for_json:
                error_msg = "No valid output files generated (check previous errors)."
            elif output_filepath and not os.path.exists(output_filepath):
                 error_msg = f"Output file missing after generation: {output_filepath}"

            self._write_error_to_json(unique_id, error_msg, final_paths_for_json)
            return self._create_error_result(error_msg, final_paths_for_json)


    def _write_error_to_json(self, unique_id, error_message, existing_paths=None):
        """Helper to write an error structure to the JSON file for Gradio."""
        if existing_paths is None:
            existing_paths = []
        temp_json_path = os.path.join(self.temp_dir, f"{unique_id}.json")
        error_data = {
            "error": error_message,
            "generated_files": existing_paths
        }
        try:
            with open(temp_json_path, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, indent=4)
            print(f"Error info written to temp file (for Gradio): {temp_json_path}")
        except Exception as e:
            print(f"Critical error: failed to write error JSON ({temp_json_path}): {e}")

    def _create_error_result(self, error_message, existing_paths=None):
        """Helper to create an error structure for the ComfyUI UI."""
        if existing_paths is None:
            existing_paths = []
        print(f"Creating UI error result: {error_message}")
        return {
            "ui": {
                "error": [error_message],
                "generated_files": existing_paths
            }
        }

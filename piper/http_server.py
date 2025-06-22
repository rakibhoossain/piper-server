#!/usr/bin/env python3
import argparse
import io
import logging
import wave
import os
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
import logging.config
import tempfile
import hashlib

from flask import Flask, request, jsonify, send_file, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import json

from .placeholder_stretcher import PlaceholderStretcher
from .file_storage import FileStorage
from . import PiperVoice
from .download import ensure_voice_exists, find_voice, get_voices

_LOGGER = logging.getLogger()


def configure_logging(debug=False):
    """Configure logging for the application."""
    log_level = "DEBUG" if debug else "INFO"
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["console"],
                "level": log_level,
                "propagate": True
            },
            "werkzeug": {
                "level": "WARNING" if not debug else "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
        },
    }
    logging.config.dictConfig(logging_config)


def main() -> Flask:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0", help="HTTP server host")
    parser.add_argument("--port", type=int, default=5000, help="HTTP server port")
    #
    parser.add_argument("-m", "--model", required=True, help="Path to Onnx model file")
    parser.add_argument("-c", "--config", help="Path to model config file")
    #
    parser.add_argument("-s", "--speaker", type=int, help="Id of speaker (default: 0)")
    parser.add_argument(
        "--length-scale", "--length_scale", type=float, help="Phoneme length"
    )
    parser.add_argument(
        "--noise-scale", "--noise_scale", type=float, help="Generator noise"
    )
    parser.add_argument(
        "--noise-w", "--noise_w", type=float, help="Phoneme width noise"
    )
    #
    parser.add_argument("--cuda", action="store_true", help="Use GPU")
    #
    parser.add_argument(
        "--sentence-silence",
        "--sentence_silence",
        type=float,
        default=0.0,
        help="Seconds of silence after each sentence",
    )
    #
    parser.add_argument(
        "--data-dir",
        "--data_dir",
        action="append",
        default=[str(Path.cwd())],
        help="Data directory to check for downloaded models (default: current directory)",
    )
    parser.add_argument(
        "--download-dir",
        "--download_dir",
        help="Directory to download voices into (default: first data dir)",
    )
    #
    parser.add_argument(
        "--update-voices",
        action="store_true",
        help="Download latest voices.json during startup",
    )
    #
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to console"
    )
    parser.add_argument(
        "--storage-dir", 
        "--storage_dir",
        default="./audio_storage", 
        help="Directory to store processed audio files"
    )
    parser.add_argument(
        "--file-expiry",
        "--file_expiry",
        type=int,
        default=20,
        help="Minutes after which files are automatically deleted"
    )
    parser.add_argument(
        "--base-url",
        "--base_url",
        default=os.environ.get("PIPER_BASE_URL", ""),
        help="Base URL for file access (default: from PIPER_BASE_URL env var)"
    )
    parser.add_argument(
        "--behind-proxy",
        "--behind_proxy",
        action="store_true",
        help="Enable if running behind a proxy like Nginx"
    )
    args = parser.parse_args()
    
    # Configure proper logging
    configure_logging(args.debug)
    _LOGGER.debug(f"Starting with args: {args}")

    if not args.download_dir:
        # Download to first data directory by default
        args.download_dir = args.data_dir[0]

    # Download voice if file doesn't exist
    model_path = Path(args.model)
    if not model_path.exists():
        # Load voice info
        voices_info = get_voices(args.download_dir, update_voices=args.update_voices)

        # Resolve aliases for backwards compatibility with old voice names
        aliases_info: Dict[str, Any] = {}
        for voice_info in voices_info.values():
            for voice_alias in voice_info.get("aliases", []):
                aliases_info[voice_alias] = {"_is_alias": True, **voice_info}

        voices_info.update(aliases_info)
        ensure_voice_exists(args.model, args.data_dir, args.download_dir, voices_info)
        args.model, args.config = find_voice(args.model, args.data_dir)

    # Load voice
    voice = PiperVoice.load(args.model, config_path=args.config, use_cuda=args.cuda)
    synthesize_args = {
        "speaker_id": args.speaker,
        "length_scale": args.length_scale,
        "noise_scale": args.noise_scale,
        "noise_w": args.noise_w,
        "sentence_silence": args.sentence_silence,
    }

    # Create web server
    app = Flask(__name__)
    
    # Configure app for production use
    if args.behind_proxy:
        # Fix for running behind reverse proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        _LOGGER.info("Configured for use behind a proxy")
    
    # Initialize file storage with base_url from args or env
    storage_dir = os.path.abspath(args.storage_dir)
    base_url = args.base_url
    
    file_storage = FileStorage(
        storage_dir=storage_dir,
        expiry_minutes=args.file_expiry,
        base_url=base_url
    )
    _LOGGER.info(f"File storage initialized at {storage_dir} with {args.file_expiry}min expiry")
    if base_url:
        _LOGGER.info(f"Using base URL: {base_url}")

    # Helper function for transcription
    async def _transcribe_audio_data(audio_data, model_name='base', language=None):
        """Transcribe audio data using OpenAI's Whisper model.

        Args:
            audio_data: Raw audio data bytes
            model_name: Whisper model to use (tiny, base, small, medium, large)
            language: Optional language code for transcription

        Returns:
            Dictionary with transcription results or error information
        """
        try:
            # Check if Whisper is installed
            try:
                import whisper
            except ImportError:
                _LOGGER.error("OpenAI Whisper not installed. Install with: pip install openai-whisper")
                return {"error": "OpenAI Whisper not installed on the server",
                        "install_command": "pip install openai-whisper"}

            # Validate model name
            valid_models = ['tiny', 'base', 'small', 'medium', 'large']
            if model_name not in valid_models:
                _LOGGER.error(f"Invalid Whisper model: {model_name}")
                return {"error": f"Invalid model. Choose from: {', '.join(valid_models)}"}

            # Save audio to temporary file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

                try:
                    # Load model
                    _LOGGER.info(f"Loading Whisper {model_name} model...")

                    # Set custom download directory to avoid permission issues
                    download_root = os.path.join(os.path.dirname(__file__), "models", "whisper")
                    os.makedirs(download_root, exist_ok=True)

                    # Create a custom SSL context that ignores certificate verification
                    import ssl
                    original_context = ssl._create_default_https_context
                    ssl._create_default_https_context = ssl._create_unverified_context

                    try:
                        model = whisper.load_model(model_name, download_root=download_root)
                    finally:
                        # Restore original SSL context
                        ssl._create_default_https_context = original_context

                    # Transcribe audio
                    _LOGGER.info(f"Transcribing audio data")

                    transcribe_options = {}
                    if language:
                        transcribe_options["language"] = language

                    result = model.transcribe(temp_path, **transcribe_options)

                    # Return transcription result
                    return {
                        "text": result["text"],
                        "segments": result["segments"],
                        "language": result.get("language", ""),
                    }

                finally:
                    # Clean up temp file
                    os.unlink(temp_path)

        except Exception as e:
            _LOGGER.exception("Error transcribing audio with Whisper")
            return {"error": str(e)}




    @app.route("/", methods=["GET", "POST"])
    async def app_synthesize() -> bytes:
        if request.method == "POST":
            text = request.data.decode("utf-8")
        else:
            text = request.args.get("text", "")

        text = text.strip()
        if not text:
            raise ValueError("No text provided")

        _LOGGER.debug("Synthesizing text: %s", text)
        with io.BytesIO() as wav_io:
            with wave.open(wav_io, "wb") as wav_file:
                voice.synthesize(text, wav_file, **synthesize_args)

            return wav_io.getvalue()


    # Initialize placeholder stretcher
    stretcher = PlaceholderStretcher(voice, synthesize_args)

    @app.route("/stretch", methods=["POST"])
    async def app_stretch_audio():
        """Handle audio stretching with placeholders.
        
        Expected JSON format for placeholders:
        [
            {
                "start_time": float,  # in seconds
                "end_time": float,    # in seconds
                "text_value": str     # text to be converted to speech
            },
            ...
        ]
        """
        _LOGGER.debug("Request files: %s", request.files)
        _LOGGER.debug("Request form: %s", request.form)
        _LOGGER.debug("Request JSON: %s", request.get_json(silent=True))

        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        try:
            # Get audio file
            audio_file = request.files['audio']
            audio_data = audio_file.read()

            # Get placeholders from JSON
            placeholders = request.form.get('placeholders')
            if not placeholders:
                return jsonify({"error": "No placeholders provided"}), 400

            try:
                placeholders = json.loads(placeholders)

                print(placeholders)
                if not isinstance(placeholders, list):
                    return jsonify({"error": "Placeholders must be a list of objects"}), 400
                
                # Validate each placeholder
                for i, ph in enumerate(placeholders):
                    if not isinstance(ph, dict):
                        return jsonify({"error": f"Placeholder at index {i} is not an object"}), 400
                    
                    required_fields = ['start_time', 'end_time', 'text_value']
                    for field in required_fields:
                        if field not in ph:
                            return jsonify({"error": f"Missing required field '{field}' in placeholder at index {i}"}), 400
                    
                    if not isinstance(ph['text_value'], str):
                        return jsonify({"error": f"text_value must be a string in placeholder at index {i}"}), 400
                    
                    try:
                        ph['start_time'] = float(ph['start_time'])
                        ph['end_time'] = float(ph['end_time'])
                    except (ValueError, TypeError):
                        return jsonify({"error": f"start_time and end_time must be numbers in placeholder at index {i}"}), 400
                    
            except json.JSONDecodeError as e:
                _LOGGER.error("JSON decode error: %s", str(e))
                return jsonify({"error": f"Invalid JSON in placeholders: {str(e)}"}), 400

            # Process placeholders
            result_audio = await stretcher.process_placeholders(
                audio_data=audio_data,
                placeholders=placeholders,
                audio_format=audio_file.filename.split('.')[-1].lower()
            )

            # Check if the client wants JSON response or direct file download
            if request.args.get('format') == 'json':
                # Save the processed audio file and get a URL
                file_id = file_storage.save_file(result_audio)
                
                # Generate file URL using either the base_url or the request host
                if args.base_url:
                    file_url = f"{args.base_url.rstrip('/')}/file/{file_id}"
                else:
                    file_url = request.host_url.rstrip('/') + url_for('serve_file', file_id=file_id)

                # Return both the file URL and the raw audio
                response_data = {
                    "file_id": file_id,
                    "file_url": file_url,
                    "expires_at": datetime.now().timestamp() + (args.file_expiry * 60)
                }

                return jsonify(response_data)
            else:
                # Return the processed audio directly
                return result_audio, 200, {
                    'Content-Type': 'audio/wav',
                    'Content-Disposition': 'attachment; filename=processed.wav'
                }

        except Exception as e:
            _LOGGER.exception("Error processing placeholders")
            return jsonify({"error": str(e)}), 500
            
    @app.route("/file/<file_id>", methods=["GET"])
    def serve_file(file_id):
        """Serve a processed audio file by ID."""
        try:
            file_path = file_storage.get_file_path(file_id)
            if file_path is None:
                return jsonify({"error": "File not found"}), 404
                
            return send_file(
                file_path,
                mimetype="audio/wav",
                as_attachment=request.args.get('download') == 'true',
                download_name=f"audio_{file_id}"
            )
        except Exception as e:
            _LOGGER.exception(f"Error serving file {file_id}")
            return jsonify({"error": str(e)}), 500
            
    @app.route("/file/<file_id>/info", methods=["GET"])
    def get_file_info(file_id):
        """Get information about a file."""
        try:
            file_path = file_storage.get_file_path(file_id)
            if file_path is None:
                return jsonify({"error": "File not found"}), 404
                
            # Get file info
            file_stats = os.stat(file_path)
            creation_time = file_stats.st_ctime
            expiry_time = creation_time + (args.file_expiry * 60)
            
            return jsonify({
                "file_id": file_id,
                "created_at": creation_time,
                "expires_at": expiry_time,
                "size_bytes": file_stats.st_size,
                "file_url": args.base_url.rstrip('/') + f"/file/{file_id}" if args.base_url else request.host_url.rstrip('/') + url_for('serve_file', file_id=file_id)
            })
        except Exception as e:
            _LOGGER.exception(f"Error getting file info for {file_id}")
            return jsonify({"error": str(e)}), 500

    @app.route("/join", methods=["POST"])
    async def app_join_audio():
        """Join multiple audio files and text content in serial.
        
        Expected format:
        - multipart/form-data with:
          - items[]: Array of JSON objects with:
            - type: "audio" or "text"
            - content: For audio, a file reference; for text, the text to synthesize
        
        Query parameters:
          - format: "json" to return file URL instead of direct audio
          - transcribe: If present, also transcribe the final audio
        
        Returns:
            Combined audio file or JSON with file URL and optional transcription
        """
        try:
            # Get items data
            items_json = request.form.get('items')
            if not items_json:
                return jsonify({"error": "No items provided"}), 400
            
            try:
                items = json.loads(items_json)
                if not isinstance(items, list):
                    return jsonify({"error": "Items must be a list"}), 400
                
                # Validate items
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        return jsonify({"error": f"Item at index {i} is not an object"}), 400
                    
                    if 'type' not in item:
                        return jsonify({"error": f"Missing 'type' in item at index {i}"}), 400
                    
                    if item['type'] not in ['audio', 'text']:
                        return jsonify({"error": f"Invalid type '{item['type']}' in item at index {i}"}), 400
                    
                    if 'content' not in item:
                        return jsonify({"error": f"Missing 'content' in item at index {i}"}), 400
                    
            except json.JSONDecodeError as e:
                _LOGGER.error("JSON decode error: %s", str(e))
                return jsonify({"error": f"Invalid JSON in items: {str(e)}"}), 400

            
            # Process each item and collect audio segments
            from pydub import AudioSegment
            segments = []
            
            for item in items:
                if item['type'] == 'audio':
                    # Get audio file by reference name
                    file_key = item['content']
                    if file_key not in request.files:
                        return jsonify({"error": f"Audio file '{file_key}' not found in request"}), 400
                    
                    audio_file = request.files[file_key]
                    audio_format = audio_file.filename.split('.')[-1].lower()
                    
                    # Convert to AudioSegment
                    segment = AudioSegment.from_file(
                        io.BytesIO(audio_file.read()),
                        format=audio_format
                    )
                    segments.append(segment)
                    
                elif item['type'] == 'text':
                    # Generate TTS for text
                    text = item['content']
                    if not text:
                        continue  # Skip empty text
                    
                    with io.BytesIO() as wav_io:
                        with wave.open(wav_io, "wb") as wav_file:
                            voice.synthesize(text, wav_file, **synthesize_args)
                        
                        tts_segment = AudioSegment.from_file(
                            io.BytesIO(wav_io.getvalue()),
                            format='wav'
                        )
                        segments.append(tts_segment)
        
            # Combine all segments
            if not segments:
                return jsonify({"error": "No valid audio segments to join"}), 400
            
            final_audio = segments[0]
            for segment in segments[1:]:
                final_audio += segment
            
            # Convert to WAV and return
            with io.BytesIO() as wav_io:
                final_audio.export(wav_io, format='wav')
                result_audio = wav_io.getvalue()
            
            # Check if transcription is requested
            transcription_result = None
            if request.args.get('transcribe'):
                # Get transcription parameters from query string
                model_name = request.args.get('model', 'base')
                language = request.args.get('language')
                
                # Transcribe the audio
                transcription_result = await _transcribe_audio_data(
                    audio_data=result_audio,
                    model_name=model_name,
                    language=language
                )
            
            # Check if the client wants JSON response or direct file download
            if request.args.get('format') == 'json':
                # Save the processed audio file and get a URL
                file_id = file_storage.save_file(result_audio)
                
                # Generate file URL
                if args.base_url:
                    file_url = f"{args.base_url.rstrip('/')}/file/{file_id}"
                else:
                    file_url = request.host_url.rstrip('/') + url_for('serve_file', file_id=file_id)
                
                # Return file information
                response_data = {
                    "file_id": file_id,
                    "file_url": file_url,
                    "expires_at": datetime.now().timestamp() + (args.file_expiry * 60),
                    "duration_seconds": len(final_audio) / 1000
                }
                
                # Add transcription if available
                if transcription_result:
                    response_data["transcription"] = transcription_result
                
                return jsonify(response_data)
            else:
                # Return the processed audio directly
                return result_audio, 200, {
                    'Content-Type': 'audio/wav',
                    'Content-Disposition': 'attachment; filename=joined.wav'
                }
            
        except Exception as e:
            _LOGGER.exception("Error joining audio and text")
            return jsonify({"error": str(e)}), 500

    @app.route("/whisper", methods=["POST"])
    async def app_whisper_speech():
        """Generate speech using WhisperSpeech model.
        
        Expected format:
        - multipart/form-data with:
          - text: Text to synthesize
          - voice: (optional) Voice reference audio file
          - model: (optional) WhisperSpeech model to use
        
        Returns:
            Generated audio file or JSON with file URL
        """
        try:
            # Check if WhisperSpeech is installed
            try:
                import whisperspeech
                from whisperspeech.pipeline import Pipeline
            except ImportError:
                _LOGGER.error("WhisperSpeech not installed. Install with: pip install whisperspeech")
                return jsonify({"error": "WhisperSpeech not installed on the server"}), 500

            # Get text to synthesize
            text = request.form.get('text')
            if not text:
                return jsonify({"error": "No text provided"}), 400
            
            # Get model name (default to english_v1)
            model_name = request.form.get('model', 'english_v1')
            
            # Initialize pipeline
            _LOGGER.info(f"Initializing WhisperSpeech pipeline with model {model_name}")
            pipeline = Pipeline(model_name)
            
            # Check if voice reference is provided
            voice_audio = None
            if 'voice' in request.files:
                voice_file = request.files['voice']
                voice_audio = voice_file.read()
                _LOGGER.info(f"Using custom voice reference from uploaded file")
            
            # Generate speech
            _LOGGER.info(f"Generating speech for text: {text[:50]}...")
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_path = temp_file.name
                
                if voice_audio:
                    # Save voice reference to temp file
                    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as voice_temp:
                        voice_temp.write(voice_audio)
                        voice_temp_path = voice_temp.name
                    
                    # Generate with voice cloning
                    pipeline.generate_to_file(text, temp_path, voice_temp_path)
                    # Clean up voice temp file
                    os.unlink(voice_temp_path)
                else:
                    # Generate with default voice
                    pipeline.generate_to_file(text, temp_path)
                
                # Read the generated audio
                with open(temp_path, 'rb') as f:
                    result_audio = f.read()
                
                # Clean up temp file
                os.unlink(temp_path)
            
            # Check if the client wants JSON response or direct file download
            if request.args.get('format') == 'json':
                # Save the processed audio file and get a URL
                file_id = file_storage.save_file(result_audio)
                
                # Generate file URL
                if args.base_url:
                    file_url = f"{args.base_url.rstrip('/')}/file/{file_id}"
                else:
                    file_url = request.host_url.rstrip('/') + url_for('serve_file', file_id=file_id)
                
                # Return file information
                response_data = {
                    "file_id": file_id,
                    "file_url": file_url,
                    "expires_at": datetime.now().timestamp() + (args.file_expiry * 60),
                    "text": text
                }
                
                return jsonify(response_data)
            else:
                # Return the processed audio directly
                return result_audio, 200, {
                    'Content-Type': 'audio/wav',
                    'Content-Disposition': 'attachment; filename=whisper_speech.wav'
                }
                
        except Exception as e:
            _LOGGER.exception("Error generating speech with WhisperSpeech")
            return jsonify({"error": str(e)}), 500

    @app.route("/static/<path:filename>")
    def serve_static(filename):
        """Serve static files."""
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        return send_file(os.path.join(static_dir, filename))

    @app.route("/whisper-ui")
    def whisper_ui():
        """Serve the WhisperSpeech UI page."""
        html_path = os.path.join(os.path.dirname(__file__), "static", "whisper.html")
        return send_file(html_path)

    @app.route("/transcribe", methods=["POST"])
    async def app_transcribe_audio():
        """Transcribe audio using OpenAI's Whisper model."""
        try:
            # Check if audio file is provided
            if 'audio' not in request.files:
                return jsonify({"error": "No audio file provided"}), 400
            
            audio_file = request.files['audio']
            if not audio_file.filename:
                return jsonify({"error": "No audio file selected"}), 400
            
            # Get model name (default to base)
            model_name = request.form.get('model', 'base')
            
            # Get language (optional)
            language = request.form.get('language')
            
            # Read audio data
            audio_data = audio_file.read()
            
            # Use the common transcription function
            transcription_result = await _transcribe_audio_data(
                audio_data=audio_data,
                model_name=model_name,
                language=language
            )
            
            # Check for errors
            if "error" in transcription_result:
                error_msg = transcription_result["error"]
                if "install_command" in transcription_result:
                    return jsonify({"error": error_msg, "install_command": transcription_result["install_command"]}), 500
                else:
                    return jsonify({"error": error_msg}), 400
            
            # Return transcription result
            return jsonify(transcription_result)
                    
        except Exception as e:
            _LOGGER.exception("Error transcribing audio with Whisper")
            return jsonify({"error": str(e)}), 500

    @app.route("/transcribe-ui")
    def transcribe_ui():
        """Serve the Whisper transcription UI page."""
        html_path = os.path.join(os.path.dirname(__file__), "static", "transcribe.html")
        return send_file(html_path)

    # Only run the development server if executed directly
    # For production, use a WSGI server like Gunicorn
    app.run(host=args.host, port=args.port, debug=args.debug)
    
    return app  # Return the app for WSGI servers

if __name__ == "__main__":
    main()
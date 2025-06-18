#!/usr/bin/env python3
import argparse
import io
import logging
import wave
import os
from pathlib import Path
from typing import Any, Dict
from datetime import datetime

from flask import Flask, request, jsonify, send_file, url_for
import json

from .placeholder_stretcher import PlaceholderStretcher
from .file_storage import FileStorage
from . import PiperVoice
from .download import ensure_voice_exists, find_voice, get_voices

_LOGGER = logging.getLogger()


def main() -> None:
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _LOGGER.debug(args)

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
    
    # Initialize file storage
    storage_dir = os.path.abspath(args.storage_dir)
    file_storage = FileStorage(
        storage_dir=storage_dir,
        expiry_minutes=args.file_expiry,
        base_url=""
    )
    _LOGGER.info(f"File storage initialized at {storage_dir} with {args.file_expiry}min expiry")

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
                "file_url": request.host_url.rstrip('/') + url_for('serve_file', file_id=file_id)
            })
        except Exception as e:
            _LOGGER.exception(f"Error getting file info for {file_id}")
            return jsonify({"error": str(e)}), 500

    app.run(host=args.host, port=args.port)

if __name__ == "__main__":
    main()

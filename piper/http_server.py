#!/usr/bin/env python3
import argparse
import io
import logging
import wave
from pathlib import Path
from typing import Any, Dict

from flask import Flask, request, jsonify, json

from piper.placeholder_stretcher import PlaceholderStretcher
from . import PiperVoice, placeholder_stretcher
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
    stretcher = PlaceholderStretcher(voice)

    @app.route("/stretch", methods=["POST"])
    async def app_stretch_audio():
        """Handle audio stretching with placeholders."""

        _LOGGER.debug("Request files: %s", request.files)
        _LOGGER.debug("Request form: %s", request.form)

        print(request.files)
        print(request.form)

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

            placeholders = json.loads(placeholders)

            # Process placeholders
            result_audio = await stretcher.process_placeholders(
                audio_data=audio_data,
                placeholders=placeholders,
                audio_format=audio_file.filename.split('.')[-1].lower()
            )

            # Return the processed audio
            return result_audio, 200, {
                'Content-Type': 'audio/wav',
                'Content-Disposition': 'attachment; filename=processed.wav'
            }

        except Exception as e:
            _LOGGER.exception("Error processing placeholders")
            return jsonify({"error": str(e)}), 500

    app.run(host=args.host, port=args.port)

if __name__ == "__main__":
    main()

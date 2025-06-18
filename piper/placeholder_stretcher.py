"""Module for stretching audio with TTS placeholders."""
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union
import wave
import numpy as np
import soundfile as sf
from pydub import AudioSegment

@dataclass
class Placeholder:
    """Represents a text placeholder in the audio."""
    start_time: float  # in seconds
    end_time: float    # in seconds
    text_value: str    # text to be converted to speech
    audio_data: Optional[bytes] = None  # generated TTS audio

class PlaceholderStretcher:
    """Handles stretching audio with TTS placeholders."""
    
    def __init__(self, voice, synthesize_args):
        """Initialize with a Piper voice instance.
        
        Args:
            voice: Initialized Piper voice instance
            synthesize_args: synthesize args
        """
        self.synthesize_args = synthesize_args
        self.voice = voice
    
    async def process_placeholders(
        self,
        audio_data: bytes,
        placeholders: List[dict],
        audio_format: str = 'wav'
    ) -> bytes:
        """Process audio with placeholders and return new audio.
        
        Args:
            audio_data: Original audio data (WAV or MP3)
            placeholders: List of placeholder dictionaries with start_time, end_time, text_value
            audio_format: Format of input audio ('wav' or 'mp3')
            
        Returns:
            bytes: Processed audio data in WAV format
        """
        # Convert input audio to AudioSegment
        input_audio = AudioSegment.from_file(
            io.BytesIO(audio_data), 
            format=audio_format
        )
        
        # Sort placeholders by start time (just in case)
        placeholders_sorted = sorted(
            [Placeholder(**p) for p in placeholders],
            key=lambda x: x.start_time
        )

        # Create a list of audio segments
        segments = []
        last_end = 0

        # Generate TTS for each placeholder
        for placeholder in placeholders_sorted:
            # Add the segment before the placeholder
            if placeholder.start_time > last_end:
                segment = input_audio[last_end * 1000:placeholder.start_time * 1000]
                segments.append(segment)

            if not placeholder.text_value:
                continue

            # Generate TTS for placeholder
            with io.BytesIO() as wav_io:
                with wave.open(wav_io, "wb") as wav_file:
                    self.voice.synthesize(placeholder.text_value, wav_file, **self.synthesize_args)

                tts_audio = AudioSegment.from_file(
                    io.BytesIO(wav_io.getvalue()),
                    format='wav'
                )

                if tts_audio:
                    segments.append(tts_audio)

            last_end = placeholder.end_time

        # Add the final segment after the last placeholder
        if last_end < len(input_audio) / 1000:
            segments.append(input_audio[last_end * 1000:])

        # Combine all segments
        final_audio = segments[0]
        for segment in segments[1:]:
            final_audio += segment

        # Convert to target sample rate and return as WAV
        with io.BytesIO() as wav_io:
            final_audio.export(
                wav_io, 
                format='wav'
            )
            return wav_io.getvalue()
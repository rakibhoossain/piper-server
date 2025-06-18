"""Module for stretching audio with TTS placeholders."""
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

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
    
    def __init__(self, voice, output_sample_rate: int = 22050):
        """Initialize with a Piper voice instance.
        
        Args:
            voice: Initialized Piper voice instance
            output_sample_rate: Sample rate for output audio
        """
        self.voice = voice
        self.output_sample_rate = output_sample_rate
    
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
        audio_segment = AudioSegment.from_file(
            io.BytesIO(audio_data), 
            format=audio_format
        )
        
        # Sort placeholders by start time (just in case)
        placeholders_sorted = sorted(
            [Placeholder(**p) for p in placeholders],
            key=lambda x: x.start_time
        )
        
        # Generate TTS for each placeholder
        for placeholder in placeholders_sorted:
            # Generate TTS audio
            with tempfile.NamedTemporaryFile(suffix='.wav') as temp_file:
                self.voice.synthesize(
                    placeholder.text_value,
                    temp_file.name,
                    length_scale=1.0,
                    noise_scale=0.667,
                    noise_w=0.8
                )
                with open(temp_file.name, 'rb') as f:
                    placeholder.audio_data = f.read()
        
        # Build the final audio
        final_audio = AudioSegment.silent(duration=0)
        last_end = 0
        
        for placeholder in placeholders_sorted:
            # Add audio before this placeholder
            before_segment = audio_segment[last_end * 1000:placeholder.start_time * 1000]
            final_audio += before_segment
            
            # Add TTS audio
            tts_audio = AudioSegment.from_file(
                io.BytesIO(placeholder.audio_data),
                format='wav'
            )
            final_audio += tts_audio
            
            last_end = placeholder.end_time
        
        # Add remaining audio after last placeholder
        final_audio += audio_segment[last_end * 1000:]
        
        # Convert to target sample rate and return as WAV
        with io.BytesIO() as wav_io:
            final_audio.set_frame_rate(self.output_sample_rate).export(
                wav_io, 
                format='wav'
            )
            return wav_io.getvalue()

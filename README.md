# Piper Server

An enhanced Piper text-to-speech server with advanced features including audio placeholder processing and automatic file storage management.

## Features

- **Text-to-Speech**: Convert text to high-quality speech using the Piper TTS engine
- **Audio Placeholder Processing**: Replace placeholders in audio files with dynamically generated speech
- **Temporary File Storage**: Automatically store processed audio files with configurable expiration
- **File Management**: Auto-cleanup of old files via background scheduler

## Installation

### Prerequisites

- Python 3.7+
- Virtual environment (recommended)

### Setup

1. Clone the repository:
```sh
git clone https://github.com/rakibhoossain/piper_server.git
cd piper_server
```

2. Create and activate a virtual environment:
```sh
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```sh
pip install -r requirements_http.txt
pip install schedule  # For automated file cleanup
```

4. Download a voice model (if you don't have one already):
```sh
# The server can automatically download voices
# You'll specify the voice when running the server
```

## Usage

### Starting the Server

Basic usage:
```sh
python -m piper.http_server --model en_US-amy-medium --host 0.0.0.0 --port 5000
```

With file storage options:
```sh
python -m piper.http_server \
  --model en_US-amy-medium \
  --host 0.0.0.0 \
  --port 5000 \
  --storage-dir ./audio_storage \
  --file-expiry 20
```

Options:
- `--model`: Path to the model or voice name to use
- `--host`: Host to bind the server to (default: 0.0.0.0)
- `--port`: Port for the HTTP server (default: 5000)
- `--storage-dir`: Directory to store processed audio (default: ./audio_storage)
- `--file-expiry`: Minutes until files are deleted (default: 20)
- `--debug`: Enable debug logging

### Text-to-Speech API

**GET Request**:
```sh
curl -G --data-urlencode 'text=This is a test.' -o output.wav 'http://localhost:5000'
```

**POST Request**:
```sh
curl -X POST -H 'Content-Type: text/plain' --data 'This is a test.' -o output.wav 'http://localhost:5000'
```

### Audio Placeholder Processing

Process audio with dynamic text placeholders:

```sh
curl -X POST \
  -F "audio=@input.wav" \
  -F 'placeholders=[{"start_time": 1.5, "end_time": 3.0, "text_value": "100 dollars"}]' \
  -o processed.wav \
  'http://localhost:5000/stretch'
```

To get a JSON response with a URL to the file (valid for the expiry period):

```sh
curl -X POST \
  -F "audio=@input.wav" \
  -F 'placeholders=[{"start_time": 1.5, "end_time": 3.0, "text_value": "100 dollars"}]' \
  'http://localhost:5000/stretch?format=json'
```

The response will include a file URL that can be used to access the audio for up to the configured expiry time.

### File Access

Get a processed file by ID:
```
GET http://localhost:5000/file/{file_id}
```

Get file information:
```
GET http://localhost:5000/file/{file_id}/info
```

## How It Works

### Placeholder Processing

The system takes an audio file with "gaps" where dynamic content should be placed. You provide:

1. The original audio file
2. A list of placeholders with:
   - `start_time`: When the placeholder begins (seconds)
   - `end_time`: When the placeholder ends (seconds)
   - `text_value`: The text to convert to speech

The system:
1. Keeps the original audio before each placeholder
2. Generates TTS for each placeholder text
3. Skips the original audio during placeholder periods
4. Returns the processed audio with the dynamic speech inserted

### File Storage and Cleanup

Processed files are:
1. Saved to the configured storage directory with unique IDs
2. Automatically deleted after the configured expiry time (default: 20 minutes)
3. Accessible via URL during their lifetime

The cleanup scheduler runs in a background thread and checks files every minute.

## License

[Add license information here]

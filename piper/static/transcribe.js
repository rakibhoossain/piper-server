document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const audioFile = document.getElementById('audio-file');
    const modelSelect = document.getElementById('model-select');
    const languageInput = document.getElementById('language-input');
    const audioPreview = document.getElementById('audio-preview');
    const transcribeBtn = document.getElementById('transcribe-btn');
    const clearBtn = document.getElementById('clear-btn');
    const resultCard = document.getElementById('result-card');
    const transcriptText = document.getElementById('transcript-text');
    const segmentsContainer = document.getElementById('segments-container');
    const copyBtn = document.getElementById('copy-btn');
    const downloadBtn = document.getElementById('download-btn');
    const loading = document.getElementById('loading');
    
    // Event listeners
    audioFile.addEventListener('change', updateAudioPreview);
    transcribeBtn.addEventListener('click', transcribeAudio);
    clearBtn.addEventListener('click', clearForm);
    copyBtn.addEventListener('click', copyText);
    downloadBtn.addEventListener('click', downloadTranscript);
    
    // Update audio preview when file is selected
    function updateAudioPreview() {
        if (audioFile.files.length > 0) {
            const file = audioFile.files[0];
            const url = URL.createObjectURL(file);
            audioPreview.src = url;
            audioPreview.style.display = 'block';
        } else {
            audioPreview.src = '';
            audioPreview.style.display = 'none';
        }
    }
    
    // Transcribe audio function
    async function transcribeAudio() {
        if (audioFile.files.length === 0) {
            alert('Please select an audio file to transcribe');
            return;
        }
        
        // Show loading
        loading.style.display = 'flex';
        
        // Create form data
        const formData = new FormData();
        formData.append('audio', audioFile.files[0]);
        formData.append('model', modelSelect.value);
        
        // Add language if provided
        const language = languageInput.value.trim();
        if (language) {
            formData.append('language', language);
        }
        
        try {
            // Send request to API
            const response = await fetch('/transcribe', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                
                // Check if this is a missing dependency error
                if (errorData.install_command) {
                    alert(`Error: ${errorData.error}\n\nPlease ask the server administrator to run: ${errorData.install_command}`);
                } else {
                    throw new Error(errorData.error || 'Failed to transcribe audio');
                }
                return;
            }
            
            const data = await response.json();
            
            // Update transcript text
            transcriptText.textContent = data.text;
            
            // Clear previous segments
            segmentsContainer.innerHTML = '';
            
            // Add segments
            if (data.segments && data.segments.length > 0) {
                data.segments.forEach(segment => {
                    const segmentDiv = document.createElement('div');
                    segmentDiv.className = 'segment-item';
                    
                    const timeDiv = document.createElement('div');
                    timeDiv.className = 'segment-time';
                    timeDiv.textContent = `${formatTime(segment.start)} → ${formatTime(segment.end)}`;
                    
                    const textDiv = document.createElement('div');
                    textDiv.className = 'segment-text';
                    textDiv.textContent = segment.text;
                    
                    segmentDiv.appendChild(timeDiv);
                    segmentDiv.appendChild(textDiv);
                    segmentsContainer.appendChild(segmentDiv);
                });
            }
            
            // Show result card
            resultCard.style.display = 'block';
            
            // Scroll to result
            resultCard.scrollIntoView({ behavior: 'smooth' });
        } catch (error) {
            alert('Error: ' + error.message);
            console.error(error);
        } finally {
            // Hide loading
            loading.style.display = 'none';
        }
    }
    
    // Format time in seconds to MM:SS.ms format
    function formatTime(seconds) {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = (seconds % 60).toFixed(2);
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.padStart(5, '0')}`;
    }
    
    // Clear form function
    function clearForm() {
        audioFile.value = '';
        modelSelect.value = 'base';
        languageInput.value = '';
        audioPreview.src = '';
        audioPreview.style.display = 'none';
        resultCard.style.display = 'none';
    }
    
    // Copy text function
    function copyText() {
        const text = transcriptText.textContent;
        if (!text) return;
        
        navigator.clipboard.writeText(text)
            .then(() => {
                // Show copied notification
                const originalText = copyBtn.textContent;
                copyBtn.textContent = 'Copied!';
                setTimeout(() => {
                    copyBtn.textContent = originalText;
                }, 2000);
            })
            .catch(err => {
                console.error('Failed to copy text: ', err);
            });
    }
    
    // Download transcript function
    function downloadTranscript() {
        const text = transcriptText.textContent;
        if (!text) return;
        
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = 'transcript.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
});
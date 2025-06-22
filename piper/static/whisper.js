document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const textInput = document.getElementById('text-input');
    const modelSelect = document.getElementById('model-select');
    const voiceFile = document.getElementById('voice-file');
    const generateBtn = document.getElementById('generate-btn');
    const clearBtn = document.getElementById('clear-btn');
    const resultCard = document.getElementById('result-card');
    const audioPlayer = document.getElementById('audio-player');
    const transcriptText = document.getElementById('transcript-text');
    const downloadBtn = document.getElementById('download-btn');
    const copyBtn = document.getElementById('copy-btn');
    const loading = document.getElementById('loading');
    
    // Event listeners
    generateBtn.addEventListener('click', generateSpeech);
    clearBtn.addEventListener('click', clearForm);
    downloadBtn.addEventListener('click', downloadAudio);
    copyBtn.addEventListener('click', copyText);
    
    // Generate speech function
    async function generateSpeech() {
        const text = textInput.value.trim();
        if (!text) {
            alert('Please enter some text to synthesize');
            return;
        }
        
        // Show loading
        loading.style.display = 'flex';
        
        // Create form data
        const formData = new FormData();
        formData.append('text', text);
        formData.append('model', modelSelect.value);
        
        // Add voice file if selected
        if (voiceFile.files.length > 0) {
            formData.append('voice', voiceFile.files[0]);
        }
        
        try {
            // Send request to API
            const response = await fetch('/whisper?format=json', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to generate speech');
            }
            
            const data = await response.json();
            
            // Update audio player
            audioPlayer.src = data.file_url;
            
            // Update transcript
            transcriptText.textContent = text;
            
            // Show result card
            resultCard.style.display = 'block';
            
            // Store file URL for download
            downloadBtn.dataset.fileUrl = data.file_url;
            
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
    
    // Clear form function
    function clearForm() {
        textInput.value = '';
        modelSelect.value = 'english_v1';
        voiceFile.value = '';
        resultCard.style.display = 'none';
    }
    
    // Download audio function
    function downloadAudio() {
        const fileUrl = downloadBtn.dataset.fileUrl;
        if (!fileUrl) return;
        
        const a = document.createElement('a');
        a.href = fileUrl + '?download=true';
        a.download = 'whisper_speech.wav';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
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
});
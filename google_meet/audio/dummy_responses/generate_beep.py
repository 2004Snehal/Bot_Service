import wave
import math
import struct

def generate_beep(filepath, duration=1.0, frequency=440.0, sample_rate=16000):
    n_samples = int(sample_rate * duration)
    amplitude = 16000 # Max 32767
    
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for i in range(n_samples):
            value = int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
            data = struct.pack('<h', value)
            wav_file.writeframesraw(data)

if __name__ == "__main__":
    generate_beep("reply.wav")

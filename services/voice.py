import io
import wave
import base64
from langchain_google_genai import ChatGoogleGenerativeAI
import openai
import io

# ── 헬퍼: Raw PCM을 Gemini가 인식 가능한 WAV로 변환 ──
def _pcm_to_wav(raw_pcm: bytes, sample_rate: int = 16000) -> bytes:
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(raw_pcm)
        return wav_io.getvalue()

# ── STT: Gemini 1.5 Flash ──
async def speech_to_text_gemini(raw_pcm: bytes, sample_rate: int = 16000) -> str:
    model = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
    wav_data = _pcm_to_wav(raw_pcm, sample_rate)
    audio_b64 = base64.b64encode(wav_data).decode("utf-8")
    
    response = model.invoke([
        {"text": "Transcribe the following audio exactly into Korean text. Return ONLY the text."},
        {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}}
    ])
    return response.content.strip()


async def text_to_speech_openai(text: str) -> bytes:
    client = openai.AsyncOpenAI() # API 키 설정 필요
    response = await client.audio.speech.create(
        model="tts-1",
        voice="alloy", # 원하는 목소리 선택
        input=text,
        response_format="wav" # 여기서 wav로 지정
    )
    return response.content

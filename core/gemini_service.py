"""
Multilingual AI & Translation Engine powered by Google Gemini (google-genai SDK).
Handles English, Telugu, and Hindi processing with structured JSON outputs.
Supports native multimodal audio input directly into gemini-2.5-flash.
"""

import json
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

import config

logger = logging.getLogger("easibot.gemini")


class RobotResponse(BaseModel):
    detected_language: str = Field(
        description="Detected language code: 'en' for English, 'te' for Telugu, or 'hi' for Hindi."
    )
    reply_native: str = Field(
        description="Response written in native script (Telugu script for Telugu, Devanagari for Hindi, Latin for English)."
    )
    reply_english: str = Field(
        description="Accurate English translation of the reply for system logs and dashboard."
    )
    reply_romanized: str = Field(
        description="English/Latin phonetic transliteration for Telugu/Hindi to display reliably on TFT screens."
    )
    emotion: str = Field(
        description="Robot facial emotion: 'happy', 'thinking', 'listening', 'speaking', or 'neutral'."
    )


SYSTEM_PROMPT = """You are Easibot, a warm, highly intelligent, interactive multilingual assistant robot built on a Raspberry Pi Zero 2 W with a 2.8-inch TFT LCD and Bluetooth speaker.

Your task:
1. Understand queries in English, Telugu, and Hindi (including code-mixed speech like "weather ela undi?", "kya haal hai?", "robot battery level entha?").
2. Detect the user's primary language (en, te, hi) or respect any requested override.
3. Keep responses conversational, concise, and helpful (typically 1 to 2 clear sentences suitable for a 320x240 screen and fast voice synthesis).
4. Select a fitting facial emotion:
   - 'happy': friendly greetings, compliments, humor, positive answers.
   - 'thinking': factual lookups, calculations, complex questions.
   - 'speaking': general answers, explanations.
   - 'listening': follow-up questions, confirmations.
   - 'neutral': simple direct confirmations.
5. Provide:
   - detected_language: 'en', 'te', or 'hi'
   - reply_native: Exact response in native script (Telugu script for 'te', Devanagari script for 'hi', English for 'en').
   - reply_english: Accurate English translation.
   - reply_romanized: Romanized transliteration in standard Latin letters (for Telugu/Hindi so it can be read phonetically if screen lacks Indic fonts).
"""


class GeminiService:
    """Service wrapper for Google Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model_name = model_name or config.GEMINI_MODEL
        self.client: Optional[Any] = None

        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            logger.warning("No valid GEMINI_API_KEY provided. GeminiService will run in mock/fallback mode.")
        elif not GENAI_AVAILABLE:
            logger.warning("google-genai SDK not installed. Running in mock/fallback mode.")
        else:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Initialized Google GenAI client successfully with model: %s", self.model_name)
            except Exception as e:
                logger.error("Failed to initialize Google GenAI client: %s", e)
                self.client = None

    def _build_content_config(self, language_preference: str = "auto") -> Any:
        """Constructs GenerateContentConfig with structured JSON schema."""
        instruction = SYSTEM_PROMPT
        if language_preference in ("en", "te", "hi"):
            instruction += f"\n\nIMPORTANT: The user has selected '{language_preference}' as their preferred language. " \
                           f"You MUST formulate your reply in this language ({language_preference})."

        return types.GenerateContentConfig(
            system_instruction=instruction,
            response_mime_type="application/json",
            response_schema=RobotResponse,
            temperature=0.7,
        )

    def process_text_query(self, user_query: str, language_preference: str = "auto") -> RobotResponse:
        """Processes a text query and returns structured RobotResponse."""
        if not self.client:
            return self._generate_fallback_response(user_query, language_preference)

        models_to_try = [self.model_name]
        for fallback_m in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_error = None
        for model in models_to_try:
            try:
                prompt = f"User query: {user_query.strip()}"
                if language_preference != "auto":
                    prompt += f" (Preferred language: {language_preference})"

                config_obj = self._build_content_config(language_preference)
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config_obj
                )
                return self._parse_gemini_response(response, language_preference)
            except Exception as e:
                last_error = e
                logger.warning("Gemini text query error with model %s: %s. Trying next model...", model, e)

        logger.error("All Gemini model attempts failed: %s", last_error)
        return self._generate_fallback_response(user_query, language_preference, error_msg=str(last_error))

    def process_audio_query(self, audio_bytes: bytes, mime_type: str = "audio/wav", language_preference: str = "auto") -> RobotResponse:
        """
        Sends recorded audio directly to Gemini 2.5 Flash for native multimodal recognition.
        Eliminates the need for heavy local STT models on Raspberry Pi Zero 2 W.
        """
        if not self.client:
            return self._generate_fallback_response("Voice Query", language_preference)

        models_to_try = [self.model_name]
        for fallback_m in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_error = None
        for model in models_to_try:
            try:
                audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
                prompt = "Listen to this user audio recording. Accurately transcribe it, detect whether it is in " \
                         "English, Telugu, or Hindi (or code-mixed), and reply following your system instructions."
                if language_preference != "auto":
                    prompt += f" Respond in the preferred language: {language_preference}."

                config_obj = self._build_content_config(language_preference)
                response = self.client.models.generate_content(
                    model=model,
                    contents=[audio_part, prompt],
                    config=config_obj
                )
                return self._parse_gemini_response(response, language_preference)
            except Exception as e:
                last_error = e
                logger.warning("Gemini audio query error with model %s: %s. Trying next model...", model, e)

        logger.error("All Gemini model audio attempts failed: %s", last_error)
        return self._generate_fallback_response("Voice input", language_preference, error_msg=str(last_error))

    def _parse_gemini_response(self, response: Any, language_preference: str) -> RobotResponse:
        """Extracts and validates structured response from Gemini."""
        try:
            # If response.parsed is available from Pydantic schema
            if hasattr(response, "parsed") and response.parsed is not None:
                if isinstance(response.parsed, RobotResponse):
                    return response.parsed
                if isinstance(response.parsed, dict):
                    return RobotResponse(**response.parsed)

            # Otherwise parse response text as JSON
            raw_text = response.text or "{}"
            # Strip markdown fences if present
            clean_text = raw_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]

            data = json.loads(clean_text.strip())
            return RobotResponse(
                detected_language=data.get("detected_language", "en"),
                reply_native=data.get("reply_native", "Hello, I am Easibot!"),
                reply_english=data.get("reply_english", "Hello, I am Easibot!"),
                reply_romanized=data.get("reply_romanized", "Hello, I am Easibot!"),
                emotion=data.get("emotion", "happy")
            )
        except Exception as e:
            logger.warning("Failed to parse Gemini response as JSON (%s), fallback triggered", e)
            raw = getattr(response, "text", "") or "Hello!"
            return RobotResponse(
                detected_language="en",
                reply_native=raw[:120],
                reply_english=raw[:120],
                reply_romanized=raw[:120],
                emotion="neutral"
            )

    def _generate_fallback_response(
        self, query: str, language_preference: str = "auto", error_msg: Optional[str] = None
    ) -> RobotResponse:
        """Generates smart canned response when offline or before API key is configured."""
        target_lang = language_preference if language_preference in ("en", "te", "hi") else "en"
        
        # Simple detection heuristic for offline mode
        query_lower = query.lower()
        if any(w in query_lower for w in ["namaste", "kaise", "kya", "namaskar", "kripya", "hindi"]):
            target_lang = "hi"
        elif any(w in query_lower for w in ["namaskaram", "ela", "enti", "cheppu", "telugu"]):
            target_lang = "te"

        if target_lang == "te":
            return RobotResponse(
                detected_language="te",
                reply_native="నమస్కారం! నేను ఈసీబాట్. మీ సహాయం కోసం సిద్ధంగా ఉన్నాను.",
                reply_english="Hello! I am Easibot. I am ready to help you.",
                reply_romanized="Namaskaram! Nenu Easibot. Mee sahayam kosam siddhamga unnanu.",
                emotion="happy"
            )
        elif target_lang == "hi":
            return RobotResponse(
                detected_language="hi",
                reply_native="नमस्ते! मैं ईसीबॉट हूँ। मैं आपकी सहायता के लिए तैयार हूँ।",
                reply_english="Hello! I am Easibot. I am ready to assist you.",
                reply_romanized="Namaste! Main Easibot hoon. Main aapki sahayata ke liye taiyar hoon.",
                emotion="happy"
            )
        else:
            return RobotResponse(
                detected_language="en",
                reply_native="Hello! I am Easibot, your multilingual assistant. How can I help?",
                reply_english="Hello! I am Easibot, your multilingual assistant. How can I help?",
                reply_romanized="Hello! I am Easibot, your multilingual assistant. How can I help?",
                emotion="happy"
            )

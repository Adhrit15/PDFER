"""Thin wrapper around the Gemini API (free tier) with model fallback."""
import asyncio
import re
from functools import lru_cache
from typing import AsyncIterator

from google import genai
from google.genai import errors, types

from . import config, prompts


class LLMError(Exception):
    """Message is safe to show to the user."""


@lru_cache(maxsize=64)
def _client(key: str) -> genai.Client:
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=config.AI_TIMEOUT * 1000))


def _key(api_key: str | None) -> str:
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise LLMError("No Gemini API key is configured. Add GEMINI_API_KEY to the .env file "
                       "(free at aistudio.google.com/apikey).")
    return key


def _friendly(e: errors.APIError) -> str:
    code = getattr(e, "code", None)
    if code == 429:
        return "The free AI quota is used up for the moment. Wait a minute and try again."
    if code in (400, 401, 403) and "api key" in str(e).lower():
        return "The Gemini API key was rejected. Check the key and try again."
    if code in (500, 503, 504):
        return "The AI model is overloaded right now. Try again in a few seconds."
    return f"The AI request failed ({code}). Try again."


def turn(role: str, text: str) -> types.Content:
    return types.Content(role=role, parts=[types.Part.from_text(text=text)])


RETRY = (404, 429, 500, 503, 504)  # worth trying the next model


async def stream(system: str, contents: list[types.Content], api_key: str | None = None) -> AsyncIterator[str]:
    client = _client(_key(api_key))
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.3)
    problem = "The AI did not answer in time. Try again in a moment."
    for model in config.MODELS:
        sent = False
        try:
            # Free-tier models sometimes hang; give each one a fair wait for its first words.
            chunks = (await asyncio.wait_for(
                client.aio.models.generate_content_stream(model=model, contents=contents, config=cfg),
                config.FIRST_TOKEN_TIMEOUT)).__aiter__()
            while True:
                try:
                    chunk = await (chunks.__anext__() if sent else
                                   asyncio.wait_for(chunks.__anext__(), config.FIRST_TOKEN_TIMEOUT))
                except StopAsyncIteration:
                    break
                if chunk.text:
                    sent = True
                    yield chunk.text
            if sent:
                return
            problem = "The AI returned an empty answer. Try rephrasing the question."
        except asyncio.TimeoutError:
            continue
        except errors.APIError as e:
            problem = _friendly(e)
            if sent or getattr(e, "code", None) not in RETRY:
                break
        except Exception:  # network trouble or a client-side timeout
            if sent:
                problem = "The connection to the AI dropped mid-answer. Try again."
                break
    raise LLMError(problem)


def ocr(data: bytes, pages: int, api_key: str | None = None) -> list[str]:
    """Transcribe a scanned PDF with Gemini's vision. Returns one string per page."""
    client = _client(_key(api_key))
    contents = [types.Part.from_bytes(data=data, mime_type="application/pdf"), prompts.OCR_PROMPT]
    problem = "The AI did not answer in time. Try again in a moment."
    for model in config.MODELS:
        try:
            text = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0, http_options=types.HttpOptions(timeout=config.OCR_TIMEOUT * 1000))).text or ""
            break
        except errors.APIError as e:
            if getattr(e, "code", None) not in RETRY:
                raise LLMError(_friendly(e)) from e
            problem = _friendly(e)
        except Exception:  # network trouble or a client-side timeout
            pass
    else:
        raise LLMError(problem)

    out = [""] * pages
    parts = re.split(r"<<<PAGE\s+(\d+)>>>", text)
    for num, body in zip(parts[1::2], parts[2::2]):
        i = int(num) - 1
        if 0 <= i < pages:
            out[i] = body.strip()
    return out

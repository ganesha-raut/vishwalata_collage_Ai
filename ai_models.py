"""
AI Models Configuration - Easy Switch between Gemini & Ollama
Supports: Google Gemini, Ollama (Phi3, Llama, etc)
"""

import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

ACTIVE_MODEL = "groq"  # Options: "gemini", "ollama", "sarvam", or "groq"

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

GEMINI_API_KEYS = [
    os.getenv("GEMINI_API_KEY_1", ""),
    os.getenv("GEMINI_API_KEY_2", ""),
    os.getenv("GEMINI_API_KEY_3", ""),
    os.getenv("GEMINI_API_KEY_4", ""),
    os.getenv("GEMINI_API_KEY_5", ""),
]

# Filter out any empty keys just in case
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

current_key_index = 0

OLLAMA_BASE_URL = "http://localhost:11434"  # Ollama server URL
OLLAMA_MODEL = "vishwalata-chat"  # Custom model with embedded system prompt (faster!)
OLLAMA_TEMPERATURE = 0.6  # Lower = faster
OLLAMA_TOP_P = 0.85  # Reduced for speed

MODEL_CONFIG = {
    "gemini": {
        "name": "gemini-3-flash-preview",  # Working model
        "temperature": 0.7,
        "top_p": 0.95,
        "max_output_tokens": 2048,
        "streaming": True
    },
    "ollama": {
        "name": OLLAMA_MODEL,
        "temperature": OLLAMA_TEMPERATURE,
        "top_p": OLLAMA_TOP_P,
        "num_predict": 1024,  # Reduced from 2048 for faster generation
        "num_ctx": 2048,  # Reduced from 4096 for speed
        "repeat_penalty": 1.1,
        "top_k": 30,  # Reduced from 40
    },
    "sarvam": {
        "name": "sarvam-m",
        "streaming": True
    },
    "groq": {
        "name": "llama-3.1-8b-instant",
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 1024,
        "streaming": True
    }
}


class GeminiModel:
    # intialize app reqs
    def __init__(self):
        global current_key_index
        try:
            from google import genai
            self.genai = genai
            self.current_key_index = current_key_index
            self.client = genai.Client(api_key=GEMINI_API_KEYS[self.current_key_index])
            self.model_name = MODEL_CONFIG["gemini"]["name"]
            self.config = MODEL_CONFIG["gemini"]
            print(f"✅ Gemini ready with {self.model_name} (Using API Key #{self.current_key_index + 1})")
        except ImportError:
            print("⚠️  Google Genai library not installed!")
            print("   Install it: pip install google-genai")
            raise
    
    # wrkng on _switch_to_next_key
    def _switch_to_next_key(self):
        """Switch to next API key in the list"""
        self.current_key_index = (self.current_key_index + 1) % len(GEMINI_API_KEYS)
        new_key = GEMINI_API_KEYS[self.current_key_index]
        self.client = self.genai.Client(api_key=new_key)
        print(f"🔄 Switched to API Key #{self.current_key_index + 1}")
        return self.current_key_index
    
    # run ai gernate msg
    def generate_stream(self, prompt, system_instruction=""):
        """Stream response from Gemini with auto-retry on quota errors"""
        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        
        attempts = 0
        max_attempts = len(GEMINI_API_KEYS)
        
        while attempts < max_attempts:
            try:
                response = self.client.models.generate_content_stream(
                    model=self.model_name,
                    contents=full_prompt
                )
                
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
                
                return
                
            except Exception as e:
                error_msg = str(e)
                
                if "429" in error_msg or "quota" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                    attempts += 1
                    print(f"⚠️  API Key #{self.current_key_index + 1} quota exceeded")
                    
                    if attempts < max_attempts:
                        self._switch_to_next_key()
                        print(f"🔄 Retrying with API Key #{self.current_key_index + 1}...")
                        continue  # Retry with new key
                    else:
                        print(f"❌ All {max_attempts} API keys exhausted")
                        yield "⚠️ All API keys have reached their quota limit. Please try again later or add more API keys."
                        return
                else:
                    print(f"Gemini Error: {error_msg}")
                    yield f"Error: {error_msg}"
                    return

class OllamaModel:
    # intialize app reqs
    def __init__(self):
        try:
            import ollama
            self.ollama = ollama
            self.client = ollama.Client(host=OLLAMA_BASE_URL)
        except ImportError:
            print("⚠️  Ollama Python library not installed!")
            print("   Install it: pip install ollama")
            raise
        
        self.model = OLLAMA_MODEL
        self.config = MODEL_CONFIG["ollama"]
        
        try:
            models = self.client.list()
            available_models = [m['name'].split(':')[0] for m in models.get('models', [])]
            
            if self.model not in available_models:
                print(f"⚠️  Warning: {self.model} not found in Ollama")
                print(f"   Available: {available_models}")
                print(f"   Run: ollama pull {self.model}")
            else:
                print(f"✅ Ollama ready with {self.model}")
        except Exception as e:
            print(f"⚠️  Ollama server not running at {OLLAMA_BASE_URL}")
            print(f"   Please start: ollama serve")
            print(f"   Then pull model: ollama pull {self.model}")
    
    # run ai gernate msg
    def generate_stream(self, prompt, system_instruction=""):
        """Stream response from Ollama with high-speed generation using official SDK"""
        try:
            stream = self.client.generate(
                model=self.model,
                prompt=prompt,
                system=system_instruction if system_instruction else None,
                stream=True,
                options={
                    'temperature': self.config['temperature'],
                    'top_p': self.config['top_p'],
                    'top_k': self.config['top_k'],
                    'repeat_penalty': self.config['repeat_penalty'],
                    'num_predict': self.config['num_predict'],
                    'num_ctx': self.config['num_ctx'],
                }
            )
            
            for chunk in stream:
                if 'response' in chunk:
                    yield chunk['response']
                    
        except Exception as e:
            error_msg = str(e)
            if "connection" in error_msg.lower():
                yield "Error: Cannot connect to Ollama. Please make sure Ollama is running (ollama serve)"
            else:
                print(f"Ollama Error: {e}")
                yield f"Error: {error_msg}"

class SarvamModel:
    # intialize app reqs
    def __init__(self):
        try:
            from sarvamai import SarvamAI
            self.client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
            self.model_name = MODEL_CONFIG["sarvam"]["name"]
            print(f"✅ SarvamAI ready with {self.model_name}")
        except ImportError:
            print("⚠️  SarvamAI library not installed!")
            print("   Install it: pip install sarvamai")
            raise

    # run ai gernate msg
    def generate_stream(self, prompt, system_instruction=""):
        """Stream response from SarvamAI"""
        try:
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            
            messages.append({"role": "user", "content": prompt})
                
            stream = self.client.chat.completions(
                messages=messages,
                model=self.model_name,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    if hasattr(chunk.choices[0], 'delta') and chunk.choices[0].delta:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
        except Exception as e:
            error_msg = str(e)
            print(f"SarvamAI Error: {error_msg}")
            yield f"Error: {error_msg}"


class GroqModel:
    # intialize app reqs
    def __init__(self):
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is missing. Set it in your environment.")

        try:
            from groq import Groq
            self.client = Groq(api_key=GROQ_API_KEY)
            self.model_name = MODEL_CONFIG["groq"]["name"]
            self.config = MODEL_CONFIG["groq"]
            print(f"✅ Groq ready with {self.model_name}")
        except ImportError:
            print("⚠️  Groq Python library not installed!")
            print("   Install it: pip install groq")
            raise

    # run ai gernate msg
    def generate_stream(self, prompt, system_instruction=""):
        """Stream response from Groq using llama-3.1-8b-instant"""
        try:
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})

            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.config["temperature"],
                top_p=self.config["top_p"],
                max_tokens=self.config["max_tokens"],
                stream=True,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            error_msg = str(e)
            print(f"Groq Error: {error_msg}")
            yield f"Error: {error_msg}"


# get chck mdel
def get_ai_model():
    """Factory function to get the active AI model"""
    if ACTIVE_MODEL == "gemini":
        return GeminiModel()
    elif ACTIVE_MODEL == "ollama":
        return OllamaModel()
    elif ACTIVE_MODEL == "sarvam":
        return SarvamModel()
    elif ACTIVE_MODEL == "groq":
        return GroqModel()
    else:
        raise ValueError(f"Unknown model: {ACTIVE_MODEL}. Use 'gemini', 'ollama', 'sarvam', or 'groq'")

# get chck mdel
def switch_model(model_name):
    """Switch active model (call this from app.py if needed)"""
    global ACTIVE_MODEL
    if model_name in ["gemini", "ollama", "sarvam", "groq"]:
        ACTIVE_MODEL = model_name
        print(f"✅ Switched to {model_name.upper()}")
        return True
    else:
        print(f"❌ Invalid model: {model_name}")
        return False

# get chck mdel
def get_active_model_info():
    """Get information about active model"""
    return {
        "active_model": ACTIVE_MODEL,
        "model_name": MODEL_CONFIG[ACTIVE_MODEL]["name"],
        "config": MODEL_CONFIG[ACTIVE_MODEL]
    }

if __name__ == "__main__":
    print("Testing AI Model...")
    model = get_ai_model()
    
    print("\n🧪 Streaming test:")
    for token in model.generate_stream("Say hello in 10 words", "You are a helpful assistant"):
        print(token, end='', flush=True)
    print("\n\n✅ Test complete!")

# 🎓 Vishwalata College AI Assistant

![Vishwalata College AI](static/logo.png)

A highly responsive, real-time AI-powered admission counselor and chat assistant built exclusively for **Vishwalata College**. This intelligent web application guides students, provides course details, showcases campus facilities, and seamlessly generates admission inquiry leads.

## 🌟 Key Features

*   **⚡ Real-time Streaming AI Response:** Powered by WebSockets (`Flask-SocketIO`), ensuring users see the AI typing its responses instantly.
*   **🤖 Multi-LLM Support Engine:** Easily switch between top-tier AI models including Google Gemini, Groq, and Sarvam AI directly via the backend configuration.
*   **🏫 Intelligent Data Contextualization:** Automatically fetches information from a robust SQLite database carrying accurate details regarding college fees, facilities, and placements.
*   **🌐 Multi-Lingual Context:** Automatically tailors the AI personality to switch intuitively between English, Marathi, and Hindi, accommodating local students seamlessly.
*   **📸 Dynamic Visual Gallery Integration:** Auto-matches user queries regarding "campus", "library", or "hostels" and effortlessly displays corresponding visuals within the chat UI.
*   **🔐 Bulletproof API Security:** 100% Secure implementation. Employs strictly HttpOnly session cookies for state authorization—hiding internal logic completely from client vectors.
*   **👨‍💻 Comprehensive Admin Panel:** A secure interface strictly available to authorized admins to manually update/add course fees, new gallery images, and view actively collected inbound student inquiry leads.

## 🚀 Tech Stack

*   **Backend Developer:** Python `Flask`
*   **Real-time Communication:** `Flask-SocketIO` & `Eventlet`
*   **Database Management:** Serverless `SQLite3`
*   **Security & Encryption:** `bcrypt`, HttpOnly Session State
*   **Frontend UI Engine:** Custom HTML5, Responsive Vanilla CSS3, JS Vanilla (No Framework Overhead)
*   **AI Integration:** `google.generativeai`, `groq`, `sarvamai`

---

## 🛠️ Quick Installation Guide

### Prerequisites
1. Python 3.9+ installed on your system.
2. An active API key from the supported LLM providers (Gemini / Groq / Sarvam).

### 1. Clone the repository
```bash
git clone https://github.com/ganesha-raut/vishwalata_collage_Ai.git
cd vishwalata_collage_Ai
```

### 2. Setup the Virtual Environment
```bash
python -m venv .venv
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Setup API Keys
Open `ai_models.py` and input your respective API Key.
```python
ACTIVE_MODEL = "sarvam" # or "gemini", "groq"
```

### 5. Run the Server
```bash
python app.py
```
> The application will safely initialize and serve the app synchronously via WebSockets on `http://127.0.0.1:5000`.

---

## 🔒 Security Posture

*   All database interactions utilize parameterized executions, neutralizing `SQL-Injection`.
*   Frontend completely abstracted away from third-party Application keys. 
*   Passed comprehensive Black-Box UI Analysis. (See `SECURITY_TEST_REPORT.md` for full breakdown).

<br/>

> **Developed & Maintained by Ganesha Raut.**

# Scheme Setu 🌾

**AI-powered government scheme discovery for Indian farmers.**

Scheme Setu ("Bridge to Schemes") is a multilingual AI assistant that helps rural Indian farmers discover government schemes they're eligible for. It uses voice input in native languages, an intelligent conversational agent, and text-to-speech to make government benefits accessible to everyone.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Next.js     │────▶│  FastAPI      │────▶│  LangGraph Agent │
│  Frontend    │◀────│  Backend      │◀────│  (Groq + Tavily) │
└─────────────┘     └──────────────┘     └──────────────────┘
                           │
                    ┌──────┴──────┐
                    │  Sarvam AI  │  (ASR / TTS)
                    │  Neon DB    │  (PostgreSQL)
                    └─────────────┘
```

## Tech Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| Frontend  | Next.js, TypeScript, Tailwind CSS   |
| Backend   | FastAPI, Python                     |
| AI Agent  | LangGraph, Groq LLM, Tavily Search |
| Voice     | Sarvam AI (Speech-to-Text, TTS)     |
| Database  | Neon (Serverless PostgreSQL)         |
| Deploy    | Docker Compose                      |

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (optional)

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/scheme_setu.git
cd scheme_setu
```

### 2. Backend setup

```bash
cd backend
cp .env.example .env
# Fill in your API keys in .env

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

### 4. Docker (alternative)

```bash
docker-compose up --build
```

## API Endpoints

| Method | Endpoint  | Description                          |
|--------|-----------|--------------------------------------|
| POST   | `/chat`   | Text-based conversation with agent   |
| POST   | `/voice`  | Voice input → AI response            |
| POST   | `/tts`    | Text-to-speech conversion            |
| GET    | `/health` | Health check with DB connectivity    |
| GET    | `/`       | API status                           |

## Environment Variables

See [`backend/.env.example`](backend/.env.example) for required configuration.

## License

MIT

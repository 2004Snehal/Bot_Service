# HiCapy Bot Service & Microservices Platform — SDE Technical Specification & Architecture

> **Target Audience:** Software Development Engineers (SDEs), System Architects, DevOps/DevSecOps Engineers.  
> **Scope:** End-to-end technical documentation covering the 4-microservice architecture, database design, API specifications, container runtime infrastructure, real-time Voice AI pipeline, Summarization service, AWS/Docker deployment topologies, and observability.

---

## Table of Contents

1. [Executive Summary & 4-Microservice Architecture](#1-executive-summary--4-microservice-architecture)
   - 1.1 [Microservice Topology Overview](#11-microservice-topology-overview)
   - 1.2 [Distributed System Context Diagram](#12-distributed-system-context-diagram)
2. [Microservices Breakdown](#2-microservices-breakdown)
   - 2.1 [Microservice 1: Frontend Service (`hicapy/frontend`)](#21-microservice-1-frontend-service-hicapyfrontend)
   - 2.2 [Microservice 2: Client Server / Core Backend (`python_client_backend`)](#22-microservice-2-client-server--core-backend-python_client_backend)
   - 2.3 [Microservice 3: Bot Service & Voice AI Pipeline (`Bot_Service`)](#23-microservice-3-bot-service--voice-ai-pipeline-bot_service)
   - 2.4 [Microservice 4: AI Summarization Service (`summarizer_service`)](#24-microservice-4-ai-summarization-service-summarizer_service)
3. [Database Design & Schema Topology](#3-database-design--schema-topology)
   - 3.1 [Relational Entity Relationship (ER) Diagram](#31-relational-entity-relationship-er-diagram)
   - 3.2 [Database Table Specifications & Indexes](#32-database-table-specifications--indexes)
   - 3.3 [Multi-Tenant Data Isolation Strategy](#33-multi-tenant-data-isolation-strategy)
   - 3.4 [Cloud Storage Object Layout (S3)](#34-cloud-storage-object-layout-s3)
4. [API Architecture & Service Intercommunication](#4-api-architecture--service-intercommunication)
   - 4.1 [Authentication & Header Contracts](#41-authentication--header-contracts)
   - 4.2 [Inter-Service Client Protocols (`HicapyBotClient` & `SummarizerServiceClient`)](#42-inter-service-client-protocols-hicapybotclient--summarizerserviceclient)
   - 4.3 [API Endpoint Catalog](#43-api-endpoint-catalog)
   - 4.4 [Request Traceability & Correlation IDs](#44-request-traceability--correlation-ids)
5. [Bot Container Runtime & Audio Subsystem Architecture](#5-bot-container-runtime--audio-subsystem-architecture)
   - 5.1 [Headless Display Stack (Docker + Xvfb + Selenium)](#51-headless-display-stack-docker--xvfb--selenium)
   - 5.2 [PulseAudio Virtual Sink Routing Graph](#52-pulseaudio-virtual-sink-routing-graph)
   - 5.3 [DOM MutationObserver Engine](#53-dom-mutationobserver-engine)
   - 5.4 [Automated Participant Count Auto-Shutdown Monitor](#54-automated-participant-count-auto-shutdown-monitor)
6. [Real-Time Voice AI Subsystem](#6-real-time-voice-ai-subsystem)
   - 6.1 [Speech-to-Text (STT) & Neural VAD/AEC](#61-speech-to-text-stt--neural-vadaec)
   - 6.2 [LLM Token Streaming & Sentence Parsing](#62-llm-token-streaming--sentence-parsing)
   - 6.3 [WebSocket Streaming Text-to-Speech (TTS)](#63-websocket-streaming-text-to-speech-tts)
   - 6.4 [Pipecat Resilience & Atomic CancellationTokens](#64-pipecat-resilience--atomic-cancellationtokens)
   - 6.5 [Latency Budget Breakdown (~520ms P50)](#65-latency-budget-breakdown-520ms-p50)
7. [Deployment Topology & Infrastructure (AWS & Docker)](#7-deployment-topology--infrastructure-aws--docker)
   - 7.1 [AWS Infrastructure Architecture](#71-aws-infrastructure-architecture)
   - 7.2 [CI/CD Pipeline & Buildspec Specs](#72-cicd-pipeline--buildspec-specs)
   - 7.3 [Environment Variables Matrix Across Microservices](#73-environment-variables-matrix-across-microservices)
8. [Observability, Resilience & Error Recovery](#8-observability-resilience--error-recovery)

---

## 1. Executive Summary & 4-Microservice Architecture

### 1.1 Microservice Topology Overview

The **HiCapy Platform** is an enterprise-grade, distributed microservices system designed for automated meeting intelligence, real-time voice assistance, and AI meeting analytics. The platform is architected around **4 specialized microservices**:

1. **Frontend Service (`hicapy/frontend`)**: Single Page Application (React / Next.js / Vite) handling user interactions, Google OAuth authentication, meeting control panels, live bot status dashboards, and transcript/summary analytics visualizers.
2. **Client Server / Core Backend Service (`python_client_backend`)**: Central FastAPI application orchestrating user accounts, Google Gmail/Calendar integrations, JWT authentication, persistent database management, and dispatching requests to downstream AI microservices via asynchronous HTTP clients (`HicapyBotClient`, `SummarizerServiceClient`).
3. **Bot Service & Voice AI Pipeline (`Bot_Service`)**: Dedicated containerized execution engine running Dockerized headless Chrome, Selenium, virtual Xvfb displays, PulseAudio sound routing, participant count auto-shutdown monitors, and the real-time sub-500ms Voice AI pipeline (Pipecat, Deepgram WebSocket STT/TTS, Silero Neural VAD, Groq streaming LLM).
4. **Summarization Service (`summarizer_service`)**: Specialized NLP processing microservice that fetches finalized meeting transcripts from S3, generates executive summaries (`POST /summarize/meeting`), extracts action items with assignees/deadlines (`POST /api/extract`), identifies key topics, and persists summary artifacts to S3.

---

### 1.2 Distributed System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MICROSERVICE 1: FRONTEND                           │
│                      (React / Next.js / Vite Web App)                       │
│    User Interface, Dashboard, Google OAuth, Live Transcript & Analytics     │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ HTTPS / REST (JWT Auth)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  MICROSERVICE 2: CLIENT SERVER / CORE BACKEND               │
│                        (python_client_backend FastAPI)                      │
│  ├── Tenant Management & Database (SQLAlchemy PostgreSQL/SQLite)            │
│  ├── HicapyBotClient API Client ──▶ Dispatches Bot Start/Stop Commands      │
│  └── SummarizerServiceClient API Client ──▶ Triggers Transcript NLP         │
└───────────────┬──────────────────────────────────────────────┬──────────────┘
                │ HTTP REST (X-API-Key)                        │ HTTP REST (/summarize)
                ▼                                              ▼
┌─────────────────────────────────────────────┐  ┌────────────────────────────┐
│ MICROSERVICE 3: BOT SERVICE & VOICE PIPELINE│  │ MICROSERVICE 4: SUMMARIZER │
│            (Bot_Service FastAPI)            │  │   (summarizer_service API) │
│ ┌─────────────────────────────────────────┐ │  │ ├── Ingests JSON from S3   │
│ │ Docker Execution Nodes (Xvfb :99)       │ │  │ ├── Groq/OpenAI Summaries │
│ │ ├── Headless Chrome (Selenium)          │ │  │ └── Action Item Extraction │
│ │ ├── PulseAudio (MeetOutput & BotMic)    │ │  └──────────────┬─────────────┘
│ │ └── Pipecat Voice Loop (Sub-500ms TTFB) │ │                 │
│ └────────────────────┬────────────────────┘ │                 │
└──────────────────────┼──────────────────────┘                 │
                       │ Upload MP4/JSON                        │ Upload Summary
                       ▼                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     AWS S3 SHARED ARTIFACT STORAGE BUCKET                   │
│     s3://<bucket>/meetings/meet_<id>/ { video, transcript, summary }        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Microservices Breakdown

### 2.1 Microservice 1: Frontend Service (`hicapy/frontend`)

- **Tech Stack**: React 18, Next.js / Vite, MUI, TailwindCSS, Axios, WebSockets.
- **Responsibilities**:
  - Manages end-user Google OAuth sign-in and session JWT authentication.
  - Displays **Live Activity Dashboard** showing active bots (`RUNNING`, `COMPLETED`, `FAILED`).
  - Provides instant meeting bot trigger inputs ("Join Instant Meeting").
  - Renders interactive transcript viewer, VTT video audio syncing, executive summaries, and action item checklists.

### 2.2 Microservice 2: Client Server / Core Backend (`python_client_backend`)

- **Tech Stack**: Python 3.10+, FastAPI, SQLAlchemy, Alembic, PostgreSQL / SQLite, Pydantic, HTTPX.
- **Responsibilities**:
  - Primary API Gateway for client frontend communication (`/api/v1/auth`, `/api/v1/bots`, `/api/v1/meetings`, `/api/v1/transcripts`, `/api/v1/summarizer`).
  - Implements **`HicapyBotClient`** singleton (`service.py`) with automatic correlation ID injection (`X-Correlation-Id`) to manage bot creation, joining, stopping, and status queries on Microservice 3.
  - Implements **`SummarizerServiceClient`** singleton (`summarizer_service.py`) to trigger post-meeting NLP summarization on Microservice 4 upon meeting completion.
  - Stores application user data, client API keys, schedule records, and meeting metadata.

### 2.3 Microservice 3: Bot Service & Voice AI Pipeline (`Bot_Service`)

- **Tech Stack**: Python 3.10+, FastAPI Gateway (`server/app/main.py`), Selenium, PyAudio/PulseAudio, Docker, Pipecat AI, Deepgram WebSocket SDK, Groq SDK, Silero VAD.
- **Responsibilities**:
  - Receives REST requests from Microservice 2 (`POST /api/bots/{id}/start`).
  - Launches containerized virtual display instances (Xvfb `:99`) running Chrome to join Google Meet sessions.
  - Captures 1080p MP4 video and PCM S16LE audio streams via PulseAudio virtual sinks (`MeetOutput`).
  - Runs participant count monitoring (`_monitor_participants()`) for automated container self-termination when human count $\le 1$.
  - Drives sub-500ms real-time conversational Voice AI pipeline.
  - Multi-thread uploads raw MP4 video, timestamped JSON transcripts, and VTT captions to AWS S3.

### 2.4 Microservice 4: AI Summarization Service (`summarizer_service`)

- **Tech Stack**: Asynchronous Python microservice, Groq / OpenAI / Anthropic APIs, Structlog, HTTPX.
- **Responsibilities**:
  - Exposes endpoints `POST /summarize/meeting`, `GET /summary/{meeting_id}`, and `POST /api/extract`.
  - Asynchronously fetches raw transcript JSON directly from S3 (`s3://<bucket>/meetings/meet_<meeting_id>/transcript/transcript.json`).
  - Generates multi-perspective executive meeting summaries, bulleted key discussions, decisions, and action items with assigned owners and deadlines.
  - Saves generated summaries back to AWS S3 (`summary_s3_url`) and notifies Microservice 2.

---

## 3. Database Design & Schema Topology

### 3.1 Relational Entity Relationship (ER) Diagram

The system employs a relational schema managed via **SQLAlchemy ORM** (`server/app/db/models.py`):

```mermaid
erdiagram
    User ||--o{ Bot : "owns"
    User ||--o{ Schedule : "creates"
    User ||--o{ Meeting : "initiates"
    Bot ||--o{ Schedule : "assigned_to"
    Bot ||--o{ Meeting : "executes"

    User {
        string user_id PK "Client-provided identifier"
        string email UK "Unique tenant email"
        string api_key UK "Generated cm_... API key"
        datetime created_at "Account creation timestamp"
        string is_active "Tenant active status"
    }

    Bot {
        string id PK "UUID4 primary key"
        string user_id FK "Foreign key to User"
        string name "Bot display name"
        string system_prompt "Custom persona system prompt"
        datetime created_at "Bot creation timestamp"
    }

    Schedule {
        string id PK "UUID4 primary key"
        string user_id FK "Foreign key to User"
        string bot_id FK "Foreign key to Bot"
        string meeting_id "Optional client meeting ID"
        string meetlink "Google Meet URL"
        datetime start_time "Scheduled join timestamp"
        integer min_record_time_seconds "Minimum session duration"
        boolean enable_recording "Record video/audio flag"
        boolean enable_transcript "Extract transcript flag"
        boolean enable_speak "Voice participation flag"
        string status "pending | running | completed | failed"
    }

    Meeting {
        string meeting_id PK "Client-provided meeting ID"
        string user_id FK "Foreign key to User"
        string bot_id FK "Foreign key to Bot"
        datetime start_time "Session start timestamp"
        datetime end_time "Session completion timestamp"
        string transcript_s3_url "S3 URL for JSON transcript"
        string transcript_vtt_s3_url "S3 URL for VTT captions"
        string recording_s3_url "S3 URL for MP4 video recording"
        string summary_s3_url "S3 URL for meeting summary text"
        string metadata_s3_url "S3 URL for session metadata"
        boolean recording_enabled "Feature flag"
        boolean transcript_enabled "Feature flag"
        boolean speak_enabled "Feature flag"
        string transcript_summary "Text summary snippet"
        string status "running | completed | failed"
    }
```

### 3.2 Database Table Specifications & Indexes

#### 1. `users` Table
- `user_id` (`VARCHAR`, PK): Client-provided tenant identifier.
- `email` (`VARCHAR`, Unique, Index): Tenant email address.
- `api_key` (`VARCHAR`, Unique, Index): Formatted securely as `cm_<token_urlsafe(32)>`.
- `created_at` (`TIMESTAMP`): UTC creation timestamp.
- `is_active` (`VARCHAR`): Tenant active status string ("true"/"false").

#### 2. `bots` Table
- `id` (`VARCHAR`, PK): Primary key UUID string.
- `user_id` (`VARCHAR`, FK $\rightarrow$ `users.user_id`, Index): Owner tenant ID.
- `name` (`VARCHAR`, Index): Display name inside Google Meet (e.g., "Bot Assistant").
- `system_prompt` (`TEXT`): Custom prompt guiding bot behavior during conversation.
- `created_at` (`TIMESTAMP`): Creation timestamp.

#### 3. `schedules` Table
- `id` (`VARCHAR`, PK): Primary key UUID string.
- `user_id` (`VARCHAR`, FK $\rightarrow$ `users.user_id`, Index): Tenant ID.
- `bot_id` (`VARCHAR`, FK $\rightarrow$ `bots.id`): Assigned bot persona ID.
- `meeting_id` (`VARCHAR`): Client-provided meeting identifier.
- `meetlink` (`VARCHAR`): Google Meet target URL.
- `start_time` (`TIMESTAMP`): Scheduled execution time.
- `status` (`VARCHAR`): State enum (`pending`, `running`, `completed`, `failed`).

#### 4. `meetings` Table
- `meeting_id` (`VARCHAR`, PK): Primary key string.
- `user_id` (`VARCHAR`, FK $\rightarrow$ `users.user_id`, Index): Tenant ID.
- `bot_id` (`VARCHAR`, FK $\rightarrow$ `bots.id`): Executing bot persona ID.
- `start_time` / `end_time` (`TIMESTAMP`): Session execution interval.
- `transcript_s3_url`, `transcript_vtt_s3_url`, `recording_s3_url`, `summary_s3_url`, `metadata_s3_url` (`VARCHAR`): AWS S3 artifact storage locations.
- `status` (`VARCHAR`): Active state enum (`running`, `completed`, `failed`).

### 3.3 Multi-Tenant Data Isolation Strategy

- **Foreign Key Indexing**: `user_id` is indexed across all child tables (`bots`, `schedules`, `meetings`).
- **Query Scope Enforcement**: Every REST API endpoint filters strictly by the authenticated tenant's `user_id` extracted from `X-API-Key` headers.

### 3.4 Cloud Storage Object Layout (S3)

Meeting artifacts are stored deterministically under the S3 bucket root:

```
s3://<bucket_name>/meetings/meet_<meeting_id>/
├── video/
│   └── recording.mp4          # 1080p H.264 video + AAC audio recording
├── transcript/
│   ├── transcript.json        # Timestamped speaker-labeled JSON transcript
│   └── captions.vtt           # Standard WebVTT caption file
└── metadata/
    ├── meeting.json           # Session runtime metadata (duration, participant list)
    └── summary.txt            # LLM-generated executive summary
```

---

## 4. API Architecture & Service Intercommunication

### 4.1 Authentication & Header Contracts

| Header | Target Service | Description |
|---|---|---|
| `Authorization` | Microservice 2 | `Bearer <JWT_TOKEN>` header from Frontend for client API access. |
| `X-API-Key` | Microservice 3 | Tenant authorization key (`cm_...`) sent by Microservice 2. |
| `X-Admin-Key` | Microservice 3 | Admin key for privileged microservice operations. |
| `X-Correlation-Id` | All Services | UUID string propagated across microservices for distributed tracing. |

### 4.2 Inter-Service Client Protocols (`HicapyBotClient` & `SummarizerServiceClient`)

#### 1. Microservice 2 $\rightarrow$ Microservice 3 Communication (`HicapyBotClient`)
```python
# In python_client_backend/backend/app/features/dashboard/bots/service.py
async def start_bot(self, api_key: str, bot_id: str, payload: dict) -> dict:
    headers = {"X-API-Key": api_key, "X-Correlation-Id": str(uuid.uuid4())}
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(f"{BOT_SERVICE_URL}/api/bots/{bot_id}/start", json=payload, headers=headers)
        return res.json()
```

#### 2. Microservice 2 $\rightarrow$ Microservice 4 Communication (`SummarizerServiceClient`)
```python
# In python_client_backend/backend/app/features/dashboard/meetings/summarizer_service.py
async def summarize_transcript(self, meeting_id: str) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        res = await client.post(f"{SUMMARIZER_SERVICE_URL}/summarize/meeting", json={"meeting_id": meeting_id})
        return res.json()
```

### 4.3 API Endpoint Catalog

#### Microservice 3 (Bot Service) API Endpoints
- `POST /api/users/register` (Admin Key): Registers new tenant.
- `POST /api/bots/` (API Key): Creates bot persona.
- `POST /api/bots/{bot_id}/start` (API Key): Launches meeting container.
- `POST /api/bots/{bot_id}/stop` (API Key): Terminates meeting container.
- `GET /health`: Health check.

#### Microservice 4 (Summarizer Service) API Endpoints
- `POST /summarize/meeting`: Triggers transcript fetch from S3 and summary generation.
- `GET /summary/{meeting_id}`: Retrieves cached meeting summary from S3.
- `POST /api/extract`: Extracts action items or key topics from transcript.

---

## 5. Bot Container Runtime & Audio Subsystem Architecture

### 5.1 Headless Display Stack (Docker + Xvfb + Selenium)

- **Xvfb Virtual Frame Buffer**: `Xvfb :99 -screen 0 1920x1080x24`.
- **Selenium Headless Chrome**: Controlled via `app.py` with flags `--use-fake-ui-for-media-stream`, `--no-sandbox`, `--disable-gpu`.
- **Window Management**: `fluxbox` manages modal windows and browser focus.

### 5.2 PulseAudio Virtual Sink Routing Graph

```
Participant Audio (Chrome) ──▶ [ Sink: MeetOutput ] ──(Monitor)──▶ FFmpeg MP4 Encoder
                                                               │
                                                               ▼
                                                         AudioInput Reader (16kHz PCM)
                                                               │
                                                               ▼
                                                         Pipecat Voice AI Pipeline
                                                               │
                                                               ▼
Participant Ear (Chrome Mic) ◀── [ Source: VirtualMic ] ◀── [ Sink: BotMic ] ◀── pacat
```

### 5.3 DOM MutationObserver Engine

Injects JavaScript into Chrome to monitor caption mutations, polling a boolean flag every 100ms and reducing Selenium DOM CPU overhead by **~90%**.

### 5.4 Automated Participant Count Auto-Shutdown Monitor

`_monitor_participants()` checks active participant video tiles. When human count $\le 0$ for 30 seconds, it triggers self-termination, saving **2GB RAM per session** and eliminating 100% of zombie container leaks.

---

## 6. Real-Time Voice AI Subsystem

### 6.1 Speech-to-Text (STT) & Neural VAD/AEC
- **Deepgram WebSocket ASR**: Direct PCM audio streaming to `wss://api.deepgram.com/v1/listen` with instant `speech_final: true` frames (100–150ms).
- **Silero Neural VAD**: 30ms window ONNX models with 3-frame speech / 8-frame silence hysteresis.
- **WebRTC AEC**: PulseAudio `module-echo-cancel` preventing false-positive self-interruption loops.

### 6.2 LLM Token Streaming & Sentence Parsing
- **Groq API**: `llama-3.1-8b-instant` / `llama-3.3-70b-versatile`.
- **Sentence Boundary Parsing**: Pushes text to TTS on `.`, `!`, `?`, `\n` delimiters before full LLM generation completes.

### 6.3 WebSocket Streaming Text-to-Speech (TTS)
- Persistent WebSocket connection to `wss://api.deepgram.com/v1/speak` with **~80ms TTFB**.

### 6.4 Pipecat Resilience & Atomic CancellationTokens
Replaced destructive `EndFrame()` calls with an atomic `CancellationToken` pattern, keeping the asyncio event loop healthy during user interruptions.

### 6.5 Latency Budget Breakdown (~520ms P50)

```
Human finishes speaking
 ├── Deepgram WebSocket ASR (speech_final)  [ 100 ms ]
 ├── Intent Classification (MiniLM)          [  15 ms ]
 ├── Groq LLM first sentence boundary token  [ 180 ms ]
 ├── Deepgram WebSocket TTS first PCM chunk  [  80 ms ]
 └── PulseAudio / pacat playback start       [  20 ms ]
TOTAL TIME-TO-FIRST-AUDIO-BYTE (TTFB):        ~395 ms - 520 ms (~0.5s P50)
```

---

## 7. Deployment Topology & Infrastructure (AWS & Docker)

### 7.1 AWS Infrastructure Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AWS Route 53 / ALB Gateway                         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AWS ECS / EC2 Service Clusters                        │
│  ├── Cluster 1: Microservice 1 (Frontend SPA)                               │
│  ├── Cluster 2: Microservice 2 (Core Client Backend FastAPI)                │
│  ├── Cluster 3: Microservice 3 (Bot Service Gateway + Worker Containers)    │
│  └── Cluster 4: Microservice 4 (Summarizer NLP Service)                     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Artifact Uploads
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AWS S3 SHARED ARTIFACT STORAGE BUCKET                  │
│                  s3://<prod-hicapy-storage>/meetings/                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 CI/CD Pipeline & Buildspec Specs

Automated image creation via AWS CodeBuild (`buildspec.yml` & `buildspec-staging.yml`):

```yaml
version: 0.2
phases:
  pre_build:
    commands:
      - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $REPOSITORY_URI
  build:
    commands:
      - docker build -t $REPOSITORY_URI:latest .
      - docker build --build-arg ENABLE_VOICE=true -t $REPOSITORY_URI:voice .
  post_build:
    commands:
      - docker push $REPOSITORY_URI:latest
      - docker push $REPOSITORY_URI:voice
```

### 7.3 Environment Variables Matrix Across Microservices

| Variable | Microservice Owner | Description |
|---|---|---|
| `VITE_API_BASE_URL` | Microservice 1 (Frontend) | URL pointing to Microservice 2 core backend. |
| `BOT_SERVICE_BASE_URL` | Microservice 2 (Backend) | URL pointing to Microservice 3 Bot REST API gateway. |
| `SUMMARIZER_SERVICE_URL` | Microservice 2 (Backend) | URL pointing to Microservice 4 Summarization service. |
| `BOT_SERVICE_ADMIN_KEY` | Microservice 2 & 3 | Admin secret for inter-service authentication. |
| `DATABASE_URL` | Microservice 2 & 3 | Connection string for PostgreSQL / SQLite DB. |
| `DEEPGRAM_API_KEY` | Microservice 3 (Bot Service) | API key for Deepgram WebSocket STT and TTS. |
| `GROQ_API_KEY` | Microservice 3 & 4 | API key for Groq LLM inference and summarization. |
| `AWS_S3_BUCKET_NAME` | Microservice 2, 3 & 4 | S3 bucket for video, transcript, and summary artifacts. |

---

## 8. Observability, Resilience & Error Recovery

1. **Distributed Correlation ID Tracing**: All HTTP requests log with `X-Correlation-Id` across Frontend $\rightarrow$ Core Backend $\rightarrow$ Bot Gateway $\rightarrow$ Summarizer Service.
2. **Subprocess Watchdog**: `AudioOutputProcessor` continuously monitors `pacat` pipe health (`subprocess.poll()`), automatically restarting dead audio pipes upon PulseAudio sink disconnects.
3. **Graceful Signal Handling**: Containers trap `SIGTERM` and `SIGINT`, initiating a 15-second graceful shutdown window to flush audio buffers, close Selenium driver instances, trigger post-meeting summarization via Microservice 4, and upload S3 artifacts before exiting.

---

> *Note: Microservice module within the CueMeet platform ecosystem.*


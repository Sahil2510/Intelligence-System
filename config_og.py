# SIT-aligned config for live_audio pipeline
# Sources: deployment-sit.yaml + JCAI_consumerai-intelligence-engine/.env
# DB password is NOT in repo — get from k8s secret (see MEMORY_DB_PASSWORD below)

# --- Dataset paths (pipeline-only) ---
DATASET_DIR=D:\GeminiLive\dataset\memory_test_data_v2
OUTPUT_DIR=D:\GeminiLive\output

# --- Gemini Live ---
GEMINI_API_KEY=AIzaSyBXbu8WrEfmo7c82HGYKD6NRIt_nJvRaKM
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview

# --- LiteLLM (Mem0 LLM/embedder + AutoGen agent) ---
LITELLM_OPENAI_API_KEY=sk-_1o87o1z9aUPiybaEQ7A6g
LITELLM_API_BASE_URL=http://50.0.20.150
LITELLM_MODEL=gpt-4.1-mini
MEM0_LLM_MODEL=gpt-4.1-mini
MEM0_EMBEDDER_MODEL=text-embedding-3-large

# --- Mem0 / pgvector (SIT deployment-sit.yaml) ---
EVAL_USER_ID=live_audio_eval_003
MEMORY_DB_HOST=50.0.64.5
MEMORY_DB_PORT=5432
MEMORY_DB_USER=postgres
# REQUIRED: not stored in git. Ask platform/DBA or run:
#   kubectl get secret consumerai-intelligence-secret-sit -o jsonpath='{.data.MEMORY-DB-PASSWORD-INT-SIT}' | base64 -d
MEMORY_DB_PASSWORD=MKw6u58Pb0YAA69aVUEYAUag
MEMORY_DB_NAME=memory_service_sit_db
MEMORY_COLLECTION_NAME=mem0
MEMORY_EMBEDDING_DIMS=3072
MEMORY_SEARCH_LIMIT=25
MEMORY_SEARCH_SCORE_THRESHOLD=0.4
MEMORY_PGVECTOR_USE_HALFVEC=true
MEMORY_PGVECTOR_HNSW=true
MEMORY_PGVECTOR_DISKANN=false

# --- MCP (SIT deployment-sit.yaml — NOT dev URLs) ---
# Optional: direct memory MCP SSE base (if registry discovery fails for search_memories)
MCP_MEMORY_SSE_URL=
TOOL_REGISTRY_URL=http://50.0.20.14
MCP_API_KEY=
MCP_INFORMATION_URL=http://50.0.20.22
MCP_CONNECTION_TIMEOUT=3
MCP_EXECUTION_TIMEOUT=10.0
MCP_REGISTRY_TIMEOUT=15

LANGFUSE_HOST=http://50.0.20.16
LANGFUSE_PATH=/api/public/ingestion
LANGFUSE_PUBLIC_KEY=pk-lf-37186f05-7496-4963-9cde-cc8ec7f671ed
LANGFUSE_SECRET_KEY=sk-lf-06245c82-0f46-4936-a5cc-e443547fe8d8
PROMPT_CACHE_TTL_SECONDS=120
PROMPT_TAG=sit
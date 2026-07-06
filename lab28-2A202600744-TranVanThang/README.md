# Lab #28 — Full Platform Integration Sprint

Nền tảng AI hybrid: hạ tầng dữ liệu và observability chạy bằng Docker Compose trên máy local; vLLM chạy trên Kaggle GPU và được truy cập qua ngrok.

## Kiến trúc

```text
Kafka ──> Prefect ──> Parquet data lake
                   ├─> Redis feature store
                   └─> Embedding API ──> Qdrant

Client ──> FastAPI Gateway ──> Qdrant retrieval
                         └───> Kaggle vLLM/ngrok

API metrics ──> Prometheus ──> Grafana + alert rules
Model metadata ──────────────> MLflow Registry
```

## Thành phần

| Service | URL | Vai trò |
|---|---|---|
| API Gateway | http://localhost:8000 | RAG và vLLM serving |
| Prefect | http://localhost:4200 | Orchestration, deployment mỗi 5 phút |
| MLflow | http://localhost:5000 | Experiment và model registry |
| Qdrant | http://localhost:6333/dashboard | Vector store |
| Embedding API | http://localhost:8002 | Local deterministic fallback embedding |
| Prometheus | http://localhost:9090 | Metrics và alerts |
| Grafana | http://localhost:3000 | Dashboard (`admin`/`admin`) |
| Kafka | localhost:9092 | Event ingestion |
| Redis | localhost:6379 | Online feature store |

## 1. Yêu cầu

- Docker Desktop đang chạy.
- Python 3.10+ để chạy scripts và smoke tests.
- Kaggle Notebook có GPU và vLLM đang chạy.
- ngrok tunnel đến vLLM còn online.

## 2. Cấu hình

Tạo `.env` từ file mẫu:

```powershell
Copy-Item .env.example .env
notepad .env
```

Đặt URL gốc của tunnel, không thêm `/v1`:

```env
VLLM_NGROK_URL=https://your-domain.ngrok-free.dev
```

LangSmith là tùy chọn:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_key
LANGCHAIN_PROJECT=lab28-platform
```

## 3. Khởi động platform

```powershell
docker compose up -d --build
docker compose ps
```

Chờ các service chuyển sang `healthy`. `prefect-deployer` chạy một lần rồi thoát với code `0`; đây là hành vi bình thường.

Kiểm tra nhanh:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
```

## 4. Chạy data pipeline

Cài dependency local một lần:

```powershell
python -m pip install -r requirements-dev.txt
```

Gửi dữ liệu vào Kafka:

```powershell
python scripts/01_ingest_to_kafka.py
```

Deployment Prefect tự chạy mỗi 5 phút. Để demo ngay:

```powershell
docker compose exec -T prefect-worker python /opt/prefect/flows/kafka_to_delta.py
```

Flow này thực hiện Kafka → Parquet → Redis và Embedding → Qdrant. Kết quả run xuất hiện trong Prefect UI.

Kiểm tra dữ liệu:

```powershell
python scripts/03_delta_to_feast.py
python scripts/05_embed_to_qdrant.py
```

## 5. MLflow model registry

```powershell
python scripts/07_register_model.py
```

Mở http://localhost:5000 để xem experiment `lab28-integration` và registered model `Qwen2.5-7B-Instruct-GPTQ-Int4`.

## 6. Gọi API Gateway

PowerShell:

```powershell
$body = @{
  query = "What is platform engineering?"
  embedding = @(0.1) * 384
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod `
  -Uri http://localhost:8000/api/v1/chat `
  -Method Post `
  -ContentType "application/json" `
  -Body $body `
  -TimeoutSec 150

$response
```

Gateway tiếp tục inference không có context khi Qdrant lỗi, và trả `503` có `request_id` khi Kaggle/vLLM không truy cập được.

## 7. Observability

Sinh traffic rồi xác minh:

```powershell
Invoke-RestMethod http://localhost:8000/health
python scripts/09_verify_observability.py
```

Grafana tự provision dashboard **Lab28 AI Platform**. Prometheus tự nạp các alert `ApiGatewayDown`, `ApiGatewayHighErrorRate`, `VllmUpstreamErrors`, và `KafkaBrokerDown`.

## 8. Smoke tests và readiness

Chuẩn bị một batch dữ liệu trước khi test:

```powershell
python scripts/01_ingest_to_kafka.py
docker compose exec -T prefect-worker python /opt/prefect/flows/kafka_to_delta.py
```

Chạy đúng 5 journeys:

```powershell
python -m pytest smoke-tests -v
```

Chạy readiness checklist:

```powershell
python scripts/production_readiness_check.py
```

Mục tiêu: `5 passed` và readiness score lớn hơn `80%`.

## 9. 10 integration points

1. Producer → Kafka (`scripts/01_ingest_to_kafka.py`).
2. Kafka → Prefect scheduled deployment.
3. Prefect → Parquet data lake.
4. Data lake → Redis feature store.
5. Embedding service → Qdrant.
6. Serving metadata → MLflow experiment.
7. MLflow experiment → Model Registry.
8. Kaggle vLLM → FastAPI Gateway.
9. Gateway/Kafka metrics → Prometheus/Grafana/alerts.
10. Structured request IDs locally; LangSmith remote tracing khi cấu hình API key.

## 10. Troubleshooting

```powershell
docker compose ps
docker compose logs --tail 100 api-gateway
docker compose logs --tail 100 prefect-worker prefect-deployer
docker compose logs --tail 100 kafka
```

- `/ready` báo `vllm: false`: giữ Kaggle session và ngrok tunnel chạy, kiểm tra lại URL trong `.env`, sau đó `docker compose up -d --force-recreate api-gateway`.
- Prefect không có deployment: `docker compose up prefect-deployer`.
- Pipeline không có record mới: producer group đã commit offset; chạy lại script ingest trước.
- Sau khi sửa Prometheus/Grafana config: `docker compose restart prometheus grafana`.

## 11. Artifacts nộp bài

Chụp các màn hình theo [SUBMISSION.md](SUBMISSION.md): Prefect flow run, API Gateway, Grafana dashboard, kết quả `5 passed`, và readiness score. Các câu trả lời thiết kế nằm trong [ANSWERS.md](ANSWERS.md).

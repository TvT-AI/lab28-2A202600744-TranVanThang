# Lab 28 — Câu trả lời thiết kế

## 1. Trade-offs kiến trúc

Kiến trúc hybrid tận dụng Kaggle GPU để giảm chi phí model serving, còn stateful services chạy local để dễ quan sát và phát triển. Đổi lại, inference phụ thuộc Internet và tunnel nên latency cao hơn một deployment cùng mạng. Maintainability được ưu tiên bằng Docker Compose, cấu hình qua environment, health checks và service boundaries rõ ràng. Reliability được cải thiện bằng retry ở Prefect, idempotent Qdrant IDs, Kafka consumer group, request validation và graceful degradation ở Gateway.

## 2. Mất kết nối Local ↔ Kaggle

Gateway đặt timeout rõ ràng, chuyển lỗi upstream thành HTTP `503` có `request_id`, và tăng Prometheus counter `gateway_upstream_errors_total`. Endpoint `/ready` kiểm tra cả Qdrant và vLLM để load balancer không gửi traffic đến instance chưa sẵn sàng. Qdrant có thể lỗi mà inference vẫn chạy với context rỗng. Hệ thống hiện không có model local tương đương vì chi phí RAM/GPU; rollback thực tế là khởi động lại Kaggle tunnel hoặc chuyển `VLLM_NGROK_URL` sang endpoint dự phòng rồi recreate Gateway.

## 3. Kafka và decoupling

Producer chỉ biết topic `data.raw`, không biết Prefect, Redis hay Qdrant. Consumer có thể dừng và tiếp tục từ committed offset mà producer không bị chặn. Cách này cho phép thêm consumer mới, replay dữ liệu và scale từng phần độc lập. Đổi lại, hệ thống phải xử lý eventual consistency, schema evolution và idempotency; flow dùng consumer group và UUID ổn định để tránh tạo vector trùng khi retry.

## 4. Observability

FastAPI xuất RED metrics qua `/metrics`; Gateway bổ sung inference histogram và upstream-error counter. Kafka exporter cung cấp broker/topic metrics. Prometheus scrape và đánh giá bốn alert rules, Grafana tự provision dashboard cho availability, request rate, p95 inference latency, upstream errors và Kafka offsets. Log có request ID để tương quan lỗi. Khi có `LANGCHAIN_API_KEY`, LangSmith bổ sung remote trace cho luồng model; khi không có credential, hệ thống vẫn có metrics và structured logs local.

## 5. Service crash và graceful degradation

Compose khai báo health check, dependency condition và `restart: unless-stopped`. Nếu Qdrant lỗi, Gateway log cảnh báo và tiếp tục gọi vLLM không có retrieval context. Nếu vLLM lỗi, Gateway trả `503` có cấu trúc thay vì crash. Kafka giữ event đến khi consumer phục hồi; Prefect task retry các integration tạm thời lỗi. Redis và Qdrant dùng volume để giữ state. Postgres thay SQLite cho Prefect nhằm tránh lock khi worker heartbeat và server cùng ghi metadata.

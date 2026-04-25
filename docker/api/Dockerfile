FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/api ./cmd/api

FROM alpine:3.21
RUN apk --no-cache add ca-certificates tzdata
COPY --from=builder /bin/api /api
EXPOSE 8080
CMD ["/api"]

FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/runner-agent ./cmd/runner-agent

FROM alpine:3.21
RUN apk --no-cache add ca-certificates tzdata
COPY --from=builder /bin/runner-agent /runner-agent
EXPOSE 8081
CMD ["/runner-agent"]
